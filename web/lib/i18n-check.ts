// SPDX-License-Identifier: Apache-2.0

// Message-catalog checks (messages/*.json), run by `pnpm i18n:check` and the
// unit test suite: no key may repeat inside an object (JSON.parse silently keeps
// the last one, hiding the other translation), and every locale must define
// exactly the same key paths.

type Json = string | number | boolean | null | Json[] | { [k: string]: Json };

/** Paths (`a.b`, `list[0].c`) of keys that appear more than once in the same
 *  object, in source order. Throws on malformed JSON. */
export function findDuplicateKeys(src: string): string[] {
  const dups: string[] = [];
  let i = 0;

  const fail = (what: string): never => {
    throw new SyntaxError(`i18n-check: ${what} at offset ${i}`);
  };
  const ws = () => {
    while (i < src.length && " \t\n\r".includes(src[i])) i += 1;
  };
  const expect = (ch: string) => {
    ws();
    if (src[i] !== ch) fail(`expected '${ch}'`);
    i += 1;
  };
  const string = (): string => {
    expect('"');
    const start = i;
    while (i < src.length && src[i] !== '"') i += src[i] === "\\" ? 2 : 1;
    if (i >= src.length) fail("unterminated string");
    const raw = src.slice(start, i);
    i += 1;
    return JSON.parse(`"${raw}"`) as string;
  };
  const join = (base: string, key: string) => (base ? `${base}.${key}` : key);

  const value = (p: string): void => {
    ws();
    const ch = src[i];
    if (ch === "{") {
      i += 1;
      const seen = new Set<string>();
      ws();
      if (src[i] === "}") {
        i += 1;
        return;
      }
      for (;;) {
        const key = string();
        if (seen.has(key)) dups.push(join(p, key));
        seen.add(key);
        expect(":");
        value(join(p, key));
        ws();
        if (src[i] === ",") {
          i += 1;
          continue;
        }
        expect("}");
        return;
      }
    }
    if (ch === "[") {
      i += 1;
      ws();
      if (src[i] === "]") {
        i += 1;
        return;
      }
      for (let n = 0; ; n += 1) {
        value(`${p}[${n}]`);
        ws();
        if (src[i] === ",") {
          i += 1;
          continue;
        }
        expect("]");
        return;
      }
    }
    if (ch === '"') {
      string();
      return;
    }
    const m = src.slice(i).match(/^(?:true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/);
    if (!m) fail("unexpected token");
    i += m![0].length;
  };

  value("");
  ws();
  if (i !== src.length) fail("trailing content");
  return dups;
}

/** Sorted leaf key paths of a parsed catalog. */
export function keyPaths(obj: Json, base = ""): string[] {
  if (obj === null || typeof obj !== "object" || Array.isArray(obj)) return base ? [base] : [];
  return Object.entries(obj)
    .flatMap(([k, v]) => keyPaths(v, base ? `${base}.${k}` : k))
    .sort();
}

export function diffKeyPaths(first: Json, second: Json): { onlyInFirst: string[]; onlyInSecond: string[] } {
  const a = new Set(keyPaths(first));
  const b = new Set(keyPaths(second));
  return {
    onlyInFirst: [...a].filter((k) => !b.has(k)),
    onlyInSecond: [...b].filter((k) => !a.has(k)),
  };
}
