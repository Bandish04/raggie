// SPDX-License-Identifier: Apache-2.0
//
// promptfoo HTTP-provider transform for the edge chat stream
// (POST /api/v1/chat/stream, Server-Sent Events). It folds the stream into the
// answer text followed by machine-readable trailers the assertions read:
//
//   <answer text>
//
//   [SOURCES] Employee_Handbook_2026.md | Travel_Policy_v3.pdf
//   [TOOLS] jira_search:ok
//   [ERROR] stream_error
//
// Trailers are always present (possibly empty) so assertions can rely on them.

function parseEvents(text) {
  const events = [];
  for (const block of String(text || "").split(/\r?\n\r?\n/)) {
    let name = "message";
    const data = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith(":")) continue;
      const i = line.indexOf(":");
      if (i < 0) continue;
      const field = line.slice(0, i);
      const value = line.slice(i + 1).replace(/^ /, "");
      if (field === "event") name = value;
      if (field === "data") data.push(value);
    }
    if (data.length) events.push({ name, data: data.join("\n") });
  }
  return events;
}

function safeJSON(s) {
  try {
    return JSON.parse(s);
  } catch {
    return null;
  }
}

module.exports = (json, text) => {
  // A pre-stream error (401/403/429/503) arrives as plain JSON.
  if (json && typeof json === "object" && json.code) {
    return `\n\n[SOURCES] \n[TOOLS] \n[ERROR] ${json.code}`;
  }
  let answer = "";
  const sources = [];
  const tools = [];
  const errors = [];
  for (const ev of parseEvents(text)) {
    const d = safeJSON(ev.data);
    if (ev.name === "message" && d && typeof d.delta === "string") answer += d.delta;
    if (ev.name === "sources" && d && Array.isArray(d.sources)) {
      for (const s of d.sources) sources.push(s.filename || s.title || s.url || "?");
    }
    if (ev.name === "tool_result" && d) tools.push(`${d.name}:${d.ok ? "ok" : "refused"}`);
    if (ev.name === "error") errors.push((d && d.code) || "stream_error");
  }
  return `${answer}\n\n[SOURCES] ${sources.join(" | ")}\n[TOOLS] ${tools.join(" ")}\n[ERROR] ${errors.join(" ")}`;
};

module.exports.parseEvents = parseEvents;
