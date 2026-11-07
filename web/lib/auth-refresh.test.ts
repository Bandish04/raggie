// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { createRefresher, type RefreshOutcome, tokenExpiresWithin } from "./auth-refresh.ts";

function jwt(payload: object): string {
  const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64(payload)}.sig`;
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

const ok = (n: number): RefreshOutcome => ({
  ok: true,
  tokens: { access_token: `a${n}`, refresh_token: `r${n}` },
});

describe("createRefresher", () => {
  test("concurrent refreshes with the same token hit the control plane once", async () => {
    let calls = 0;
    const gate = deferred<RefreshOutcome>();
    const refresh = createRefresher(async () => {
      calls += 1;
      return gate.promise;
    });
    const all = Promise.all([refresh("r0"), refresh("r0"), refresh("r0")]);
    gate.resolve(ok(1));
    const results = await all;
    assert.equal(calls, 1);
    for (const r of results) assert.deepEqual(r, ok(1));
  });

  test("a late request still carrying the rotated-out token reuses the new tokens (no reuse at the CP)", async () => {
    let now = 1_000;
    const seen: string[] = [];
    const refresh = createRefresher(
      async (t) => {
        seen.push(t);
        return ok(seen.length);
      },
      { graceMs: 60_000, now: () => now },
    );
    assert.deepEqual(await refresh("r0"), ok(1));
    now += 30_000; // another tab, old cookie, after rotation
    assert.deepEqual(await refresh("r0"), ok(1));
    assert.deepEqual(seen, ["r0"]);
  });

  test("after the grace window the old token is sent again (CP decides)", async () => {
    let now = 0;
    const seen: string[] = [];
    const refresh = createRefresher(
      async (t) => {
        seen.push(t);
        return ok(seen.length);
      },
      { graceMs: 1_000, now: () => now },
    );
    await refresh("r0");
    now += 1_001;
    await refresh("r0");
    assert.deepEqual(seen, ["r0", "r0"]);
  });

  test("different refresh tokens refresh independently", async () => {
    const seen: string[] = [];
    const refresh = createRefresher(async (t) => {
      seen.push(t);
      return ok(seen.length);
    });
    await Promise.all([refresh("ra"), refresh("rb")]);
    assert.deepEqual(seen.sort(), ["ra", "rb"]);
  });

  test("a transient failure is not cached, so the next request retries", async () => {
    let calls = 0;
    const refresh = createRefresher(async () => {
      calls += 1;
      return calls === 1 ? { ok: false, reason: "unavailable" } : ok(2);
    });
    assert.deepEqual(await refresh("r0"), { ok: false, reason: "unavailable" });
    assert.deepEqual(await refresh("r0"), ok(2));
    assert.equal(calls, 2);
  });

  test("an invalid (revoked) token result is shared, not retried in a burst", async () => {
    let calls = 0;
    const refresh = createRefresher(async () => {
      calls += 1;
      return { ok: false, reason: "invalid" };
    });
    await refresh("r0");
    await refresh("r0");
    assert.equal(calls, 1);
  });

  test("a throwing refresher becomes 'unavailable' and is not cached", async () => {
    let calls = 0;
    const refresh = createRefresher(async () => {
      calls += 1;
      throw new Error("ECONNREFUSED");
    });
    assert.deepEqual(await refresh("r0"), { ok: false, reason: "unavailable" });
    await refresh("r0");
    assert.equal(calls, 2);
  });
});

describe("tokenExpiresWithin", () => {
  const now = 1_700_000_000_000;
  const exp = (s: number) => jwt({ sub: "u", exp: Math.floor(now / 1000) + s });

  test("true when expired or inside the skew window", () => {
    assert.equal(tokenExpiresWithin(exp(-10), 60, now), true);
    assert.equal(tokenExpiresWithin(exp(30), 60, now), true);
  });

  test("false when comfortably valid", () => {
    assert.equal(tokenExpiresWithin(exp(3600), 60, now), false);
  });

  test("false for tokens we cannot read (let the upstream decide)", () => {
    assert.equal(tokenExpiresWithin("not-a-jwt", 60, now), false);
    assert.equal(tokenExpiresWithin(jwt({ sub: "u" }), 60, now), false);
    assert.equal(tokenExpiresWithin("a.%%%.c", 60, now), false);
  });
});
