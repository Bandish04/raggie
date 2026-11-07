// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { test } from "node:test";

import { withDefaultLocale } from "./chat-request.ts";

test("adds the UI locale when the client did not send one", () => {
  assert.deepEqual(JSON.parse(withDefaultLocale('{"message":"hi"}', "tr")), { message: "hi", locale: "tr" });
});

test("keeps a client-sent locale", () => {
  assert.deepEqual(JSON.parse(withDefaultLocale('{"message":"hi","locale":"en"}', "tr")), {
    message: "hi",
    locale: "en",
  });
});

test("passes non-object / invalid bodies through untouched (the edge rejects them)", () => {
  assert.equal(withDefaultLocale("not json", "tr"), "not json");
  assert.equal(withDefaultLocale("[1,2]", "tr"), "[1,2]");
  assert.equal(withDefaultLocale("", "tr"), "");
});
