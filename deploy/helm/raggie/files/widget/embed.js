// SPDX-License-Identifier: Apache-2.0

/*
 * Raggie external chat widget — embed loader. Widget tokens never reach the
 * admin APIs (see docs/security-model.md).
 *
 * Drop-in, dependency-free, Shadow-DOM isolated. One line on any site:
 *   <script src="https://EDGE_HOST/widgets/embed.js?id=WORKSPACE_ID"></script>
 *
 * Everything renders inside a closed-ish Shadow root so host-page CSS can never
 * leak in or out. The widget talks ONLY to the public edge:
 *   POST /api/v1/widget/token   -> { token, primary_color, name }  (EXTERNAL + CORS gated)
 *   POST /api/v1/chat/stream    -> SSE answer (Authorization: Bearer <widget token>)
 * It never sees the admin surface — that is the A4 boundary.
 *
 * Errors follow the edge contract: JSON {error, code, message} before the
 * stream, SSE `event: error` {code, message} during it. `message` is already
 * localized from the browser's Accept-Language, so it is shown as-is. When an
 * edge replica drains: a pre-stream 503 "draining" re-sends the turn once
 * (after Retry-After); a mid-stream `event: reconnect` {retry_after_ms,
 * conversation_id, message_id} RESUMES the interrupted answer once with
 * {conversation_id, resume_message_id} and the SAME widget token (the
 * conversation is bound to its session), so no question is stored twice.
 */
(function () {
  "use strict";

  // ── Pure helpers (also exported for unit tests, see below) ────────────────
  var DEFAULT_RETRY_MS = 2000;
  var MAX_RETRY_MS = 10000;
  var UNAVAILABLE = "Sorry — the assistant is unavailable right now.";

  function clampDelay(ms) {
    return Math.min(Math.max(ms, 0), MAX_RETRY_MS);
  }

  // One SSE frame → {event, data}; null for empty frames and [DONE].
  function parseFrame(raw) {
    var event = "message";
    var data = "";
    raw.split("\n").forEach(function (line) {
      if (line.indexOf("event:") === 0) event = line.slice(6).trim();
      else if (line.indexOf("data:") === 0) data += line.slice(5).trim();
    });
    if (!data || data === "[DONE]") return null;
    return { event: event, data: data };
  }

  // Retry-After (whole seconds) → ms, capped; null when absent/unparseable.
  // Cross-origin, the header is only readable if the edge exposes it.
  function retryAfterMs(header) {
    var v = header == null ? "" : String(header).trim();
    if (!/^\d+$/.test(v)) return null;
    return clampDelay(Number(v) * 1000);
  }

  function reconnectDelayMs(data) {
    try {
      var ms = JSON.parse(data).retry_after_ms;
      return typeof ms === "number" && isFinite(ms) ? clampDelay(ms) : DEFAULT_RETRY_MS;
    } catch (e) {
      return DEFAULT_RETRY_MS;
    }
  }

  function errorText(body, fallback) {
    var m = body && typeof body === "object" ? body.message : null;
    return typeof m === "string" && m.trim() ? m.trim() : fallback;
  }

  function errorCode(body) {
    return body && typeof body === "object" ? body.code || body.error || null : null;
  }

  // Only a draining replica is retried, and only on the first attempt.
  function shouldRetryPreStream(status, body, attempt) {
    return attempt === 0 && status === 503 && errorCode(body) === "draining";
  }

  // Resume request for an interrupted turn (no `message`: the edge must not
  // store a second user turn); null when the turn cannot be identified.
  function resumeBody(workspaceId, reconnectData, fallbackConversationId, locale) {
    var d;
    try {
      d = JSON.parse(reconnectData);
    } catch (e) {
      return null;
    }
    var conversationId = (d && d.conversation_id) || fallbackConversationId;
    if (!d || !d.message_id || !conversationId) return null;
    return {
      workspace_id: workspaceId,
      conversation_id: conversationId,
      resume_message_id: d.message_id,
      locale: locale,
    };
  }

  // `locale` for the chat request (edge prompt template): tr or en.
  function pickLocale(lang) {
    return String(lang || "").toLowerCase().indexOf("tr") === 0 ? "tr" : "en";
  }

  // ── Answer formatting (safe minimal markdown) ─────────────────────────────
  // The model's answer is untrusted text. It is parsed into a tiny AST and
  // rendered with createElement/createTextNode only (never innerHTML), so any
  // markup in it stays inert text. Supported: paragraphs, - / 1. lists,
  // **bold**, *italic*, `code`, [label](http(s) url) and [n] source markers.
  // Underscores are never emphasis, so file names like Load_Test_2026.docx stay intact.

  // Absolute http(s) URL, normalized; anything else (javascript:, data:,
  // protocol-relative, relative) is refused.
  function safeHttpUrl(url) {
    try {
      var u = new URL(String(url || "").trim());
      return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
    } catch (e) {
      return null;
    }
  }

  var INLINE_RULES = [
    { re: /^`([^`\n]+)`/, make: function (m) { return [{ t: "code", v: m[1] }]; } },
    { re: /^\*\*(\S(?:[^\n]*?\S)?)\*\*/, make: function (m, n) { return [{ t: "strong", c: parseInline(m[1], n) }]; } },
    { re: /^\*([^*\s](?:[^*\n]*?[^*\s])?)\*/, make: function (m, n) { return [{ t: "em", c: parseInline(m[1], n) }]; } },
    {
      re: /^\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]/,
      make: function (m, n) {
        return m[1].split(",").map(function (s) {
          var k = parseInt(s, 10);
          return k >= 1 && k <= n ? { t: "cite", n: k } : { t: "drop" };
        });
      },
    },
    {
      re: /^\[([^\]\n]+)\]\(([^)\s]+)\)/,
      make: function (m, n) {
        var href = safeHttpUrl(m[2]);
        var label = parseInline(m[1], n);
        return href ? [{ t: "link", href: href, c: label }] : label; // unsafe: label only
      },
    },
  ];

  // Inline AST for one block. `n` is how many sources the answer has: [k] with
  // 1 <= k <= n becomes a cite, any other marker is dropped.
  function parseInline(s, n) {
    var out = [];
    function text(v) {
      var last = out[out.length - 1];
      if (last && last.t === "text") last.v += v;
      else out.push({ t: "text", v: v });
    }
    function add(node) {
      if (node.t === "text") return text(node.v);
      if (node.t === "drop" || node.t === "cite") {
        // A chip hugs its word like a footnote mark ("minutes¹"), and a dropped
        // marker leaves no gap: "minutes [9]." reads as "minutes.".
        var last = out[out.length - 1];
        if (last && last.t === "text") {
          last.v = last.v.replace(/[ \t]+$/, "");
          if (!last.v) out.pop();
        }
      }
      if (node.t !== "drop") out.push(node);
    }
    var i = 0;
    while (i < s.length) {
      var ch = s.charAt(i);
      var hit = null;
      if (ch === "`" || ch === "*" || ch === "[") {
        var rest = s.slice(i);
        for (var r = 0; r < INLINE_RULES.length && !hit; r++) {
          var m = rest.match(INLINE_RULES[r].re);
          if (m) hit = { len: m[0].length, nodes: INLINE_RULES[r].make(m, n) };
        }
      }
      if (hit) {
        hit.nodes.forEach(add);
        i += hit.len;
      } else {
        text(ch);
        i++;
      }
    }
    return out;
  }

  // Block AST: [{type:'p', c}] | [{type:'ul'|'ol', items:[inline[]]}].
  function parseAnswer(text, sourceCount) {
    var n = Math.max(0, sourceCount | 0);
    var blocks = [];
    var para = null; // lines of the open paragraph
    var list = null; // {type, items: [string]}
    function close() {
      if (para) blocks.push({ type: "p", c: parseInline(para.join("\n"), n) });
      if (list)
        blocks.push({
          type: list.type,
          items: list.items.map(function (it) { return parseInline(it, n); }),
        });
      para = list = null;
    }
    String(text || "").replace(/\r\n?/g, "\n").split("\n").forEach(function (line) {
      var ul = line.match(/^\s*[-*•]\s+(.*)$/);
      var ol = ul ? null : line.match(/^\s*\d{1,3}[.)]\s+(.*)$/);
      var heading = line.match(/^\s*#{1,6}\s+(.*)$/);
      if (!line.trim()) return close();
      if (ul || ol) {
        var type = ul ? "ul" : "ol";
        if (!list || list.type !== type) {
          close();
          list = { type: type, items: [] };
        }
        list.items.push((ul || ol)[1]);
      } else if (heading) {
        close();
        blocks.push({ type: "p", c: [{ t: "strong", c: parseInline(heading[1], n) }] });
      } else if (list && /^\s/.test(line)) {
        list.items[list.items.length - 1] += " " + line.trim(); // wrapped list item
      } else {
        if (list) close();
        (para = para || []).push(line);
      }
    });
    close();
    return blocks;
  }

  var SOURCES_LABEL = { en: "Sources", tr: "Kaynaklar" };

  // DOM for one answer, built only with createElement/createTextNode/
  // setAttribute. `sources` are the edge's `sources` chunks ({filename, ...});
  // the cited ones are listed under the answer, numbered as in the text.
  function renderAnswer(doc, text, sources, locale) {
    sources = Array.isArray(sources) ? sources : [];
    var cited = {};
    function node(tag, cls) {
      var e = doc.createElement(tag);
      if (cls) e.className = cls;
      return e;
    }
    function filename(k) {
      var s = sources[k - 1];
      return s && typeof s === "object" ? String(s.filename || s.title || "#" + k) : "#" + k;
    }
    function inline(parent, nodes) {
      nodes.forEach(function (x) {
        var e;
        if (x.t === "text") e = doc.createTextNode(x.v);
        else if (x.t === "code") {
          e = node("code");
          e.appendChild(doc.createTextNode(x.v));
        } else if (x.t === "strong" || x.t === "em") {
          e = node(x.t);
          inline(e, x.c);
        } else if (x.t === "link") {
          e = node("a");
          e.setAttribute("href", x.href);
          e.setAttribute("rel", "noopener noreferrer nofollow");
          e.setAttribute("target", "_blank");
          inline(e, x.c);
        } else if (x.t === "cite") {
          cited[x.n] = true;
          e = node("sup", "cite");
          e.setAttribute("title", filename(x.n));
          e.appendChild(doc.createTextNode(String(x.n)));
        }
        if (e) parent.appendChild(e);
      });
    }
    var box = node("div", "ans");
    parseAnswer(text, sources.length).forEach(function (b) {
      if (b.type === "p") {
        var p = node("p");
        inline(p, b.c);
        box.appendChild(p);
      } else {
        var l = node(b.type);
        b.items.forEach(function (it) {
          var li = node("li");
          inline(li, it);
          l.appendChild(li);
        });
        box.appendChild(l);
      }
    });
    var nums = Object.keys(cited).map(Number).sort(function (a, b) { return a - b; });
    if (nums.length) {
      var srcs = node("div", "srcs");
      var title = node("div", "srcs-t");
      title.appendChild(doc.createTextNode(SOURCES_LABEL[locale] || SOURCES_LABEL.en));
      srcs.appendChild(title);
      var ol = node("ol");
      nums.forEach(function (k) {
        var li = node("li");
        li.setAttribute("value", String(k));
        li.appendChild(doc.createTextNode(filename(k)));
        ol.appendChild(li);
      });
      srcs.appendChild(ol);
      box.appendChild(srcs);
    }
    return box;
  }

  if (typeof module === "object" && module && module.exports) {
    module.exports = {
      safeHttpUrl: safeHttpUrl,
      parseAnswer: parseAnswer,
      renderAnswer: renderAnswer,
      parseFrame: parseFrame,
      retryAfterMs: retryAfterMs,
      reconnectDelayMs: reconnectDelayMs,
      errorText: errorText,
      pickLocale: pickLocale,
      shouldRetryPreStream: shouldRetryPreStream,
      resumeBody: resumeBody,
    };
    return;
  }

  // ── Resolve our own <script> tag: workspace id + edge origin ──────────────
  var self =
    document.currentScript ||
    (function () {
      var s = document.getElementsByTagName("script");
      return s[s.length - 1];
    })();
  var src = self && self.src ? new URL(self.src) : null;
  if (!src) return;
  var workspaceId = src.searchParams.get("id");
  var edge = src.origin; // the edge that served this loader is the API origin
  if (!workspaceId) {
    console.error("[raggie] embed.js: missing ?id=<workspace_id>");
    return;
  }

  if (window.__raggieWidgetMounted) return; // idempotent
  window.__raggieWidgetMounted = true;

  // ── Shadow host ───────────────────────────────────────────────────────────
  var host = document.createElement("div");
  host.id = "raggie-widget-root";
  host.style.cssText = "position:fixed;z-index:2147483000;bottom:0;right:0;";
  document.body.appendChild(host);
  var root = host.attachShadow({ mode: "open" });

  var state = {
    open: false,
    token: null,
    primary: "#6d5efc",
    name: "Raggie",
    messages: [], // {role:'user'|'bot', text, sources?}
    streaming: false,
    conversationId: null, // round-tripped so the conversation keeps its memory
    locale: pickLocale(navigator.language),
    tokenError: null, // the edge's (localized) reason the token was refused
  };

  // ── Styles (scoped to the shadow root) ────────────────────────────────────
  function css() {
    return (
      "*{box-sizing:border-box;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif}" +
      ".fab{position:fixed;bottom:20px;right:20px;width:60px;height:60px;border:none;border-radius:50%;" +
      "background:var(--p);color:#fff;font-size:26px;cursor:pointer;box-shadow:0 8px 24px rgba(0,0,0,.25);" +
      "transition:transform .15s ease}.fab:hover{transform:scale(1.06)}.fab:active{transform:scale(.96)}" +
      ".panel{position:fixed;bottom:92px;right:20px;width:370px;max-width:calc(100vw - 40px);height:560px;" +
      "max-height:calc(100vh - 120px);background:#fff;border-radius:18px;box-shadow:0 18px 60px rgba(0,0,0,.28);" +
      "display:flex;flex-direction:column;overflow:hidden;opacity:0;transform:translateY(12px);pointer-events:none;" +
      "transition:opacity .18s ease,transform .18s ease}.panel.open{opacity:1;transform:translateY(0);pointer-events:auto}" +
      ".hdr{background:var(--p);color:#fff;padding:16px 18px;font-weight:600;font-size:15px;display:flex;align-items:center;gap:8px}" +
      ".hdr .dot{width:8px;height:8px;border-radius:50%;background:#4ade80}" +
      ".msgs{flex:1;overflow-y:auto;padding:16px;background:#f7f8fb;display:flex;flex-direction:column;gap:10px}" +
      ".m{max-width:84%;padding:10px 13px;border-radius:14px;font-size:14px;line-height:1.45;white-space:pre-wrap;word-wrap:break-word}" +
      ".m.user{align-self:flex-end;background:var(--p);color:#fff;border-bottom-right-radius:4px}" +
      ".m.bot{align-self:flex-start;background:#fff;color:#1a1f2b;border:1px solid #e7e9f0;border-bottom-left-radius:4px}" +
      ".m.bot p{margin:0 0 6px}.m.bot p:last-child{margin-bottom:0}" +
      ".m.bot ul,.m.bot ol{margin:4px 0 6px;padding-left:20px}.m.bot li{margin:2px 0}" +
      ".m.bot code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;background:#f1f3f8;border-radius:4px;padding:1px 4px}" +
      ".m.bot a{color:var(--p);text-decoration:underline}" +
      ".m.bot sup.cite{display:inline-block;min-width:14px;height:14px;margin-left:1px;padding:0 3px;border-radius:7px;" +
      "background:#eceff6;color:#2b3242;font-size:10px;font-weight:600;line-height:14px;text-align:center;vertical-align:super}" +
      ".srcs{margin-top:8px;padding-top:7px;border-top:1px solid #eceef3;font-size:12px;color:#4a5263;white-space:normal}" +
      ".srcs-t{font-weight:600;margin-bottom:2px}.srcs ol{margin:0;padding-left:20px}.srcs li{word-break:break-all}" +
      ".empty{margin:auto;text-align:center;color:#8a92a6;font-size:14px;padding:20px}" +
      ".bar{display:flex;gap:8px;padding:12px;border-top:1px solid #eceef3;background:#fff}" +
      ".bar input{flex:1;border:1px solid #dfe3ec;border-radius:999px;padding:10px 15px;font-size:14px;outline:none}" +
      ".bar input:focus{border-color:var(--p)}" +
      ".bar button{border:none;background:var(--p);color:#fff;width:40px;height:40px;border-radius:50%;cursor:pointer;font-size:17px}" +
      ".bar button:disabled{opacity:.45;cursor:default}" +
      ".foot{text-align:center;font-size:11px;color:#aab0c0;padding:6px 0 9px}" +
      ".foot a{color:#8a92a6;text-decoration:none}"
    );
  }

  function el(tag, cls, txt) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (txt != null) n.textContent = txt;
    return n;
  }

  // ── Render ────────────────────────────────────────────────────────────────
  var ui = {};
  function build() {
    var style = el("style");
    style.textContent = css();
    root.appendChild(style);

    var wrap = el("div");
    wrap.style.setProperty("--p", state.primary);
    ui.wrap = wrap;

    var fab = el("button", "fab");
    fab.setAttribute("aria-label", "Open chat");
    fab.textContent = "\uD83D\uDCAC"; // speech balloon
    fab.onclick = toggle;
    ui.fab = fab;

    var panel = el("div", "panel");
    var hdr = el("div", "hdr");
    hdr.appendChild(el("span", "dot"));
    ui.title = el("span", null, state.name);
    hdr.appendChild(ui.title);
    panel.appendChild(hdr);

    ui.msgs = el("div", "msgs");
    panel.appendChild(ui.msgs);

    var bar = el("div", "bar");
    ui.input = el("input");
    ui.input.placeholder = "Type a message…";
    ui.input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") send();
    });
    ui.sendBtn = el("button", null, "↑");
    ui.sendBtn.onclick = send;
    bar.appendChild(ui.input);
    bar.appendChild(ui.sendBtn);
    panel.appendChild(bar);

    var foot = el("div", "foot");
    var brand = el("a", null, "Raggie \uD83D\uDC3E");
    brand.setAttribute("href", "https://github.com/alicangunduz/raggie");
    brand.setAttribute("target", "_blank");
    brand.setAttribute("rel", "noopener");
    foot.appendChild(document.createTextNode("Powered by "));
    foot.appendChild(brand);
    panel.appendChild(foot);

    ui.panel = panel;
    wrap.appendChild(panel);
    wrap.appendChild(fab);
    root.appendChild(wrap);
    renderMessages();
  }

  function renderMessages() {
    ui.msgs.textContent = "";
    if (!state.messages.length) {
      ui.msgs.appendChild(el("div", "empty", "👋 Hi! Ask me anything."));
      return;
    }
    state.messages.forEach(function (m) {
      if (m.role !== "bot") return ui.msgs.appendChild(el("div", "m " + m.role, m.text));
      var b = el("div", "m bot");
      b.appendChild(renderAnswer(document, m.text, m.sources, state.locale));
      ui.msgs.appendChild(b);
    });
    ui.msgs.scrollTop = ui.msgs.scrollHeight;
  }

  function toggle() {
    state.open = !state.open;
    ui.panel.classList.toggle("open", state.open);
    if (state.open) {
      ui.input.focus();
      if (!state.token) ensureToken();
    }
  }

  // ── API ─────────────────────────────────────────────────────────────────--
  function ensureToken() {
    return fetch(edge + "/api/v1/widget/token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace_id: workspaceId }),
    })
      .then(function (r) {
        if (!r.ok) {
          // e.g. 403 origin not allowed, 429 rate_limited, 503 draining.
          return r
            .json()
            .catch(function () {
              return null;
            })
            .then(function (body) {
              state.tokenError = errorText(body, UNAVAILABLE);
              return null;
            });
        }
        return r.json();
      })
      .then(function (d) {
        if (!d) return;
        state.tokenError = null;
        state.token = d.token;
        if (d.primary_color) {
          state.primary = d.primary_color;
          ui.wrap.style.setProperty("--p", state.primary);
        }
        if (d.name) {
          state.name = d.name;
          ui.title.textContent = d.name;
        }
      })
      .catch(function (e) {
        console.error("[raggie] token error", e);
      });
  }

  function send() {
    var q = ui.input.value.trim();
    if (!q || state.streaming) return;
    ui.input.value = "";

    var go = state.token ? Promise.resolve() : ensureToken();
    go.then(function () {
      if (!state.token) {
        push("bot", state.tokenError || UNAVAILABLE);
        return;
      }
      state.messages.push({ role: "user", text: q });
      var bot = { role: "bot", text: "" };
      state.messages.push(bot);
      renderMessages();
      stream(
        bot,
        {
          workspace_id: workspaceId,
          message: q,
          conversation_id: state.conversationId || undefined,
          locale: state.locale,
        },
        { drainRetried: false, resumed: false },
      );
    });
  }

  function push(role, text) {
    state.messages.push({ role: role, text: text });
    renderMessages();
  }

  // One chat request into `bot`. flags.drainRetried: a pre-stream "draining"
  // 503 was already retried; flags.resumed: this request is the (single) resume
  // of an interrupted answer. The partial answer stays until fresh tokens come.
  function stream(bot, body, flags) {
    state.streaming = true;
    ui.sendBtn.disabled = true;
    var turn = { reconnect: null, fresh: flags.resumed };
    fetch(edge + "/api/v1/chat/stream", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        // The SAME token for a resume: the conversation is bound to its session.
        Authorization: "Bearer " + state.token,
      },
      body: JSON.stringify(body),
    })
      .then(function (res) {
        if (!res.ok || !res.body) {
          return res
            .json()
            .catch(function () {
              return null;
            })
            .then(function (err) {
              if (!flags.resumed && !flags.drainRetried && shouldRetryPreStream(res.status, err, 0)) {
                var wait = retryAfterMs(res.headers.get("Retry-After")) || DEFAULT_RETRY_MS;
                return { delayMs: wait, body: body, flags: { drainRetried: true, resumed: false } };
              }
              // 429 / 503 / 4xx — or a refused resume (400/404) — the edge's
              // localized explanation, after any partial answer.
              var msg = errorText(err, UNAVAILABLE);
              bot.text = bot.text ? bot.text + "\n\n" + msg : msg;
              renderMessages();
              return null;
            });
        }
        var reader = res.body.getReader();
        var dec = new TextDecoder();
        var buf = "";
        return (function read() {
          return reader.read().then(function (r) {
            if (r.done) return nextAfterStream(bot, turn, flags);
            buf += dec.decode(r.value, { stream: true });
            var idx;
            while ((idx = buf.indexOf("\n\n")) !== -1) {
              frame(buf.slice(0, idx), bot, turn);
              buf = buf.slice(idx + 2);
            }
            return read();
          });
        })();
      })
      .catch(function () {
        bot.text += bot.text ? "" : "Connection lost.";
        renderMessages();
        return null;
      })
      .then(function (next) {
        if (next) {
          setTimeout(function () {
            stream(bot, next.body, next.flags);
          }, next.delayMs);
          return; // still busy: the retry owns the send button
        }
        state.streaming = false;
        ui.sendBtn.disabled = false;
      });
  }

  // After a stream ends: resume once if the edge asked us to reconnect.
  function nextAfterStream(bot, turn, flags) {
    if (!turn.reconnect) return null;
    var resume = flags.resumed
      ? null
      : resumeBody(workspaceId, turn.reconnect, state.conversationId, state.locale);
    if (!resume) {
      // Drained again after a resume (or the turn is unknown): keep the partial.
      var msg = errorText(safeJSON(turn.reconnect), UNAVAILABLE);
      bot.text = bot.text ? bot.text + "\n\n" + msg : msg;
      renderMessages();
      return null;
    }
    return {
      delayMs: reconnectDelayMs(turn.reconnect),
      body: resume,
      flags: { drainRetried: flags.drainRetried, resumed: true },
    };
  }

  function safeJSON(data) {
    try {
      return JSON.parse(data);
    } catch (e) {
      return null;
    }
  }

  function frame(raw, bot, turn) {
    var f = parseFrame(raw);
    if (!f) return;
    var d;
    try {
      d = JSON.parse(f.data);
    } catch (e) {
      return;
    }
    if (f.event === "meta") {
      if (d.conversation_id) state.conversationId = d.conversation_id;
    } else if (f.event === "reconnect") {
      // Replica draining: keep the partial answer; resume once after the delay.
      turn.reconnect = f.data;
      if (d.conversation_id) state.conversationId = d.conversation_id;
      // Nothing streamed yet: show the edge's (localized) note meanwhile; the
      // resumed stream's first token replaces it.
      if (!bot.text) {
        bot.text = errorText(d, "");
        renderMessages();
      }
    } else if (f.event === "sources") {
      // Retrieved chunks, numbered as the answer's [n] markers.
      bot.sources = Array.isArray(d.sources) ? d.sources : [];
      renderMessages();
    } else if (f.event === "error") {
      var msg = errorText(d, UNAVAILABLE);
      bot.text = bot.text ? bot.text + "\n\n" + msg : msg;
      renderMessages();
    } else if (f.event === "message" && d.delta) {
      if (turn.fresh) {
        bot.text = "";
        turn.fresh = false;
      }
      bot.text += d.delta;
      renderMessages();
    }
  }

  if (document.body) build();
  else window.addEventListener("DOMContentLoaded", build);
})();
