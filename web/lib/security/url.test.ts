// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { markdownImageView, safeHttpsHref, safeImageSrc, safeLinkHref } from "./url.ts";

const ORIGIN = "https://raggie.example.com";

describe("safeImageSrc", () => {
  test("accepts same-origin paths and absolute same-origin URLs", () => {
    assert.equal(safeImageSrc("/branding-icon?v=1", ORIGIN), "/branding-icon?v=1");
    assert.equal(safeImageSrc("img/a.png", ORIGIN), "img/a.png");
    assert.equal(
      safeImageSrc("https://raggie.example.com/a.png", ORIGIN),
      "https://raggie.example.com/a.png",
    );
  });

  test("rejects protocol-relative URLs that escape the origin", () => {
    assert.equal(safeImageSrc("//evil.tld/?d=secret", ORIGIN), null);
    assert.equal(safeImageSrc("/\\evil.tld/?d=secret", ORIGIN), null);
    assert.equal(safeImageSrc("\\\\evil.tld/x.png", ORIGIN), null);
  });

  test("rejects cross-origin URLs, including other schemes/ports of the same host", () => {
    assert.equal(safeImageSrc("https://evil.tld/x.png?d=1", ORIGIN), null);
    assert.equal(safeImageSrc("http://raggie.example.com/a.png", ORIGIN), null);
    assert.equal(safeImageSrc("https://raggie.example.com:8443/a.png", ORIGIN), null);
  });

  test("accepts inline raster data images but not SVG or other data", () => {
    assert.equal(safeImageSrc("data:image/png;base64,iVBORw0K", ORIGIN), "data:image/png;base64,iVBORw0K");
    assert.equal(safeImageSrc("data:image/svg+xml;base64,PHN2Zz4=", ORIGIN), null);
    assert.equal(safeImageSrc("data:text/html,<script>1</script>", ORIGIN), null);
  });

  test("rejects script schemes and empty input", () => {
    assert.equal(safeImageSrc("javascript:alert(1)", ORIGIN), null);
    assert.equal(safeImageSrc("", ORIGIN), null);
    assert.equal(safeImageSrc(undefined, ORIGIN), null);
  });
});

describe("safeLinkHref", () => {
  test("accepts http(s), mailto, relative paths and fragments", () => {
    assert.equal(safeLinkHref("https://docs.example.org/a", ORIGIN), "https://docs.example.org/a");
    assert.equal(safeLinkHref("http://intranet/a", ORIGIN), "http://intranet/a");
    assert.equal(safeLinkHref("mailto:help@example.org", ORIGIN), "mailto:help@example.org");
    assert.equal(safeLinkHref("/chat", ORIGIN), "/chat");
    assert.equal(safeLinkHref("#src-1-2", ORIGIN), "#src-1-2");
  });

  test("rejects script-capable and local schemes, even when obfuscated", () => {
    assert.equal(safeLinkHref("javascript:alert(1)", ORIGIN), null);
    assert.equal(safeLinkHref("JaVaScRiPt:alert(1)", ORIGIN), null);
    assert.equal(safeLinkHref(" java\tscript:alert(1)", ORIGIN), null);
    assert.equal(safeLinkHref("data:text/html,<script>1</script>", ORIGIN), null);
    assert.equal(safeLinkHref("vbscript:msgbox(1)", ORIGIN), null);
    assert.equal(safeLinkHref("file:///etc/passwd", ORIGIN), null);
  });

  test("rejects empty input", () => {
    assert.equal(safeLinkHref("", ORIGIN), null);
    assert.equal(safeLinkHref(undefined, ORIGIN), null);
  });
});

// What a markdown image (model answer, widget-visitor conversation) renders as.
// Only this decision may yield an <img>, so it must carry the allowlist.
describe("markdownImageView", () => {
  test("same-origin and inline raster images become an <img>", () => {
    assert.deepEqual(markdownImageView("/icon.svg", "logo", ORIGIN), { kind: "img", src: "/icon.svg", alt: "logo" });
    assert.deepEqual(markdownImageView("data:image/png;base64,AAAA", undefined, ORIGIN), {
      kind: "img",
      src: "data:image/png;base64,AAAA",
      alt: "",
    });
  });

  test("external images are never an <img>: a link the user must click instead", () => {
    for (const src of [
      "https://evil.tld/pixel.png?d=secret",
      "//evil.tld/?d=secret",
      "/\\evil.tld/x.png",
      "http://raggie.example.com/a.png",
    ]) {
      const view = markdownImageView(src, "leak", ORIGIN);
      assert.notEqual(view?.kind, "img", src);
    }
    assert.deepEqual(markdownImageView("https://evil.tld/p.png", "leak", ORIGIN), {
      kind: "link",
      href: "https://evil.tld/p.png",
      label: "leak",
    });
  });

  test("unsafe schemes fall back to inert text, or nothing", () => {
    assert.deepEqual(markdownImageView("javascript:alert(1)", "x", ORIGIN), { kind: "text", label: "x" });
    assert.deepEqual(markdownImageView("data:image/svg+xml,<svg onload=alert(1)>", "", ORIGIN), {
      kind: "text",
      label: "data:image/svg+xml,<svg onload=alert(1)>",
    });
    assert.equal(markdownImageView(undefined, undefined, ORIGIN), null);
  });
});

// Links from remote data (the release manifest's url): absolute https only.
describe("safeHttpsHref", () => {
  test("accepts absolute https URLs", () => {
    assert.equal(safeHttpsHref("https://github.com/raggie/releases/v0.2.0"), "https://github.com/raggie/releases/v0.2.0");
  });

  test("rejects every other scheme, relative and malformed values", () => {
    for (const bad of [
      "javascript:alert(1)",
      " JavaScript:alert(1)",
      "data:text/html,<script>alert(1)</script>",
      "http://releases.example.com/v0.2.0",
      "//evil.example/x",
      "/admin/updates",
      "mailto:a@example.com",
      "vbscript:msgbox(1)",
      "https://",
      "",
      undefined,
      null,
      42,
    ]) {
      assert.equal(safeHttpsHref(bad as string | null | undefined), null, String(bad));
    }
  });
});
