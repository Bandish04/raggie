// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  isPasswordPolicyRejection,
  PASSWORD_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
  passwordPolicyError,
} from "./password-policy.ts";

test("mirrors the control-plane policy bounds", () => {
  assert.equal(PASSWORD_MIN_LENGTH, 12);
  assert.equal(PASSWORD_MAX_LENGTH, 1024);
});

test("accepts passwords from 12 up to 1024 characters", () => {
  assert.equal(passwordPolicyError("a".repeat(12)), null);
  assert.equal(passwordPolicyError("correct horse battery"), null);
  assert.equal(passwordPolicyError("x".repeat(1024)), null);
});

test("rejects short, overlong and blank passwords", () => {
  assert.equal(passwordPolicyError("elevenchars"), "short");
  assert.equal(passwordPolicyError("x".repeat(1025)), "long");
  assert.equal(passwordPolicyError(" ".repeat(16)), "blank");
  assert.equal(passwordPolicyError(""), "blank");
});

test("counts characters, not UTF-16 code units", () => {
  // 11 emoji = 22 UTF-16 units but only 11 characters → still too short.
  assert.equal(passwordPolicyError("🔒".repeat(11)), "short");
  assert.equal(passwordPolicyError("ğüşiöçĞÜŞİÖÇ"), null);
});

test("recognises a control-plane 422 that is about the password field", () => {
  const detail = (field: string) => ({
    detail: [{ loc: ["body", field], msg: "Value error, password must be at least 12 characters" }],
  });
  assert.equal(isPasswordPolicyRejection(422, detail("password")), true);
  assert.equal(isPasswordPolicyRejection(422, detail("new_password")), true);
  // A 422 about some other field, another status, or an unknown body is not.
  assert.equal(isPasswordPolicyRejection(422, detail("email")), false);
  assert.equal(isPasswordPolicyRejection(400, detail("password")), false);
  assert.equal(isPasswordPolicyRejection(422, { detail: "bad" }), false);
  assert.equal(isPasswordPolicyRejection(422, undefined), false);
});
