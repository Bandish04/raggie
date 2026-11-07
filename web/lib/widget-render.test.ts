// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { describe, test } from "node:test";

// The widget's answer renderer (widget/embed.js), exported for tests when loaded
// via require. renderAnswer only uses createElement/createTextNode/appendChild/
// setAttribute/className/textContent, so a tiny fake document is enough.
const require = createRequire(import.meta.url);
type Inline =
  | { t: "text"; v: string }
  | { t: "strong" | "em"; c: Inline[] }
  | { t: "code"; v: string }
  | { t: "link"; href: string; c: Inline[] }
  | { t: "cite"; n: number };
type Block = { type: "p"; c: Inline[] } | { type: "ul" | "ol"; items: Inline[][] };
const widget = require(path.join(import.meta.dirname, "..", "..", "widget", "embed.js")) as {
  parseAnswer(text: string, sourceCount: number): Block[];
  safeHttpUrl(url: string): string | null;
  renderAnswer(doc: FakeDocument, text: string, sources: unknown[], locale: "en" | "tr"): FakeNode;
};

class FakeNode {
  children: FakeNode[] = [];
  attributes: Record<string, string> = {};
  className = "";
  private text = "";
  readonly tagName: string;
  readonly nodeType: 1 | 3;
  constructor(tagName: string, nodeType: 1 | 3 = 1) {
    this.tagName = tagName;
    this.nodeType = nodeType;
  }
  set textContent(v: string) {
    this.children = [];
    this.text = v;
  }
  get textContent(): string {
    return this.text + this.children.map((c) => c.textContent).join("");
  }
  appendChild(n: FakeNode) {
    this.children.push(n);
    return n;
  }
  setAttribute(k: string, v: string) {
    this.attributes[k] = String(v);
  }
}
class FakeDocument {
  createElement(tag: string) {
    return new FakeNode(tag.toLowerCase());
  }
  createTextNode(text: string) {
    const n = new FakeNode("#text", 3);
    n.textContent = text;
    return n;
  }
}

// Serialize with escaping, so markup that survives as TEXT is visible as &lt;.
const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
function html(n: FakeNode): string {
  if (n.nodeType === 3) return esc(n.textContent);
  const attrs = Object.entries(n.attributes)
    .map(([k, v]) => ` ${k}="${esc(v)}"`)
    .join("");
  const cls = n.className ? ` class="${n.className}"` : "";
  return `<${n.tagName}${cls}${attrs}>${n.children.map(html).join("")}</${n.tagName}>`;
}
function walk(n: FakeNode, out: FakeNode[] = []) {
  out.push(n);
  n.children.forEach((c) => walk(c, out));
  return out;
}
const render = (text: string, sources: unknown[] = []) => widget.renderAnswer(new FakeDocument(), text, sources, "en");

describe("widget parseAnswer", () => {
  test("paragraphs, bold, italic, code and lists", () => {
    assert.deepEqual(widget.parseAnswer("Hi **there** and *you*, run `make`.\n\n- one\n- two\n\n1. first\n2) second", 0), [
      {
        type: "p",
        c: [
          { t: "text", v: "Hi " },
          { t: "strong", c: [{ t: "text", v: "there" }] },
          { t: "text", v: " and " },
          { t: "em", c: [{ t: "text", v: "you" }] },
          { t: "text", v: ", run " },
          { t: "code", v: "make" },
          { t: "text", v: "." },
        ],
      },
      { type: "ul", items: [[{ t: "text", v: "one" }], [{ t: "text", v: "two" }]] },
      { type: "ol", items: [[{ t: "text", v: "first" }], [{ t: "text", v: "second" }]] },
    ]);
  });
  test("[n] markers become cites when the source exists, otherwise they are dropped", () => {
    assert.deepEqual(widget.parseAnswer("Fifteen minutes [1] and [3].", 2), [
      // A chip hugs its word like a footnote mark: "minutes¹", not "minutes ¹".
      { type: "p", c: [{ t: "text", v: "Fifteen minutes" }, { t: "cite", n: 1 }, { t: "text", v: " and." }] },
    ]);
    assert.deepEqual(widget.parseAnswer("No sources [1].", 0), [{ type: "p", c: [{ t: "text", v: "No sources." }] }]);
  });
  test("underscores in file names are not italic", () => {
    assert.deepEqual(widget.parseAnswer("See Load_Test_Report_2026_Q2.docx", 0), [
      { type: "p", c: [{ t: "text", v: "See Load_Test_Report_2026_Q2.docx" }] },
    ]);
  });
  test("only http(s) links become links", () => {
    assert.deepEqual(widget.parseAnswer("[docs](https://example.org/a?b=1) [x](javascript:alert(1))", 0), [
      {
        type: "p",
        c: [
          { t: "link", href: "https://example.org/a?b=1", c: [{ t: "text", v: "docs" }] },
          // The javascript: URL is dropped; only the label (and the stray ")") stays.
          { t: "text", v: " x)" },
        ],
      },
    ]);
    assert.equal(widget.safeHttpUrl("https://example.org"), "https://example.org/");
    for (const bad of ["javascript:alert(1)", "data:text/html,<b>", "//evil.example", "vbscript:x", " JAVASCRIPT:alert(1)", ""]) {
      assert.equal(widget.safeHttpUrl(bad), null, bad);
    }
  });
});

describe("widget renderAnswer (DOM)", () => {
  test("formats and links safely", () => {
    const out = html(render("**15 minutes** [1]\n\n- P1\n- [SLA](https://example.org/sla)", [{ filename: "Destek_SLA_Matrisi_2026.xlsx" }]));
    assert.match(out, /<strong>15 minutes<\/strong>/);
    assert.match(out, /<sup class="cite" title="Destek_SLA_Matrisi_2026.xlsx">1<\/sup>/);
    assert.match(out, /<ul><li>P1<\/li><li><a href="https:\/\/example.org\/sla" rel="noopener noreferrer nofollow" target="_blank">SLA<\/a><\/li><\/ul>/);
    // Cited sources are listed under the answer.
    assert.match(out, /<div class="srcs"><div class="srcs-t">Sources<\/div><ol><li value="1">Destek_SLA_Matrisi_2026.xlsx<\/li><\/ol><\/div>/);
  });

  test("XSS payloads stay inert text", () => {
    const payloads = [
      "<script>alert(1)</script>",
      '<img src=x onerror="alert(1)">',
      "[click](javascript:alert(document.cookie))",
      '<a href="javascript:alert(1)">x</a>',
      "&lt;script&gt;alert(1)&lt;/script&gt; &#x3C;img&#x3E;",
      "**<svg onload=alert(1)>**",
      "`<iframe src=//evil>`",
      "[1](javascript:alert(1)) [ok](https://example.org/\"onmouseover=\"alert(1))",
    ];
    for (const p of payloads) {
      const node = render(p, [{ filename: '<img src=x onerror="alert(1)">' }]);
      for (const n of walk(node)) {
        assert.ok(["div", "p", "strong", "em", "code", "a", "sup", "ul", "ol", "li", "#text"].includes(n.tagName), `${p}: <${n.tagName}>`);
        for (const [k, v] of Object.entries(n.attributes)) {
          assert.ok(!k.toLowerCase().startsWith("on"), `${p}: ${k}`);
          if (k === "href") assert.match(v, /^https?:\/\//, `${p}: href ${v}`);
        }
      }
    }
    // Markup arrives as text, entities are not decoded.
    assert.match(html(render("<script>alert(1)</script>")), /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
    assert.match(html(render("&lt;b&gt;")), /&amp;lt;b&amp;gt;/);
  });

  test("Turkish sources label", () => {
    const tr = widget.renderAnswer(new FakeDocument(), "Evet [1]", [{ filename: "a.pdf" }], "tr");
    assert.match(html(tr), /<div class="srcs-t">Kaynaklar<\/div>/);
  });
});
