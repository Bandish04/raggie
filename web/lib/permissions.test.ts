// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { isPlatformAdmin, PLATFORM_ONLY_NAV, platformAdminError } from "./permissions.ts";

describe("isPlatformAdmin", () => {
  test("true only for an explicit is_platform_admin flag", () => {
    assert.equal(isPlatformAdmin({ is_platform_admin: true }), true);
    assert.equal(isPlatformAdmin({ is_platform_admin: false }), false);
    assert.equal(isPlatformAdmin({}), false);
    assert.equal(isPlatformAdmin(null), false);
  });

  test("an org SUPER_ADMIN is not a platform admin by role alone", () => {
    assert.equal(isPlatformAdmin({ role: "SUPER_ADMIN" }), false);
  });

  test("an inactive user is never treated as platform admin", () => {
    assert.equal(isPlatformAdmin({ is_platform_admin: true, is_active: false }), false);
  });
});

test("platform-only admin sections", () => {
  assert.deepEqual([...PLATFORM_ONLY_NAV].sort(), ["ai", "branding", "updates"]);
});

describe("platformAdminError", () => {
  test("maps the control-plane 409 reasons", () => {
    assert.equal(platformAdminError(409, "cannot revoke the last platform admin"), "lastAdmin");
    assert.equal(
      platformAdminError(409, "only an active SUPER_ADMIN can be a platform admin"),
      "requiresSuperAdmin",
    );
  });

  test("maps 403 and falls back to generic", () => {
    assert.equal(platformAdminError(403, "forbidden"), "forbidden");
    assert.equal(platformAdminError(409, "something else"), "generic");
    assert.equal(platformAdminError(500, undefined), "generic");
    assert.equal(platformAdminError(0, undefined), "generic");
  });
});
