import { describe, expect, it } from "vitest";
import vectors from "../../tests/vectors/params.json";
import { normalizeHost, parseRedirect, safeHttpUrl } from "../src/guest/params";

// The same vectors run against wispr/params.py in tests/test_unit.py.
describe("params parity with wispr/params.py", () => {
  for (const v of vectors.vectors) {
    it(v.query.slice(0, 90) || "(empty query)", () => {
      const { ok, values, unknown, rejected, missing, aliases } = parseRedirect(new URLSearchParams(v.query));
      expect({ values, unknown, rejected, missing, aliases, ok }).toEqual(v.expect);
    });
  }

  it("matches the Python helpers", () => {
    expect(safeHttpUrl("https://a.example/x?y=1")).toBe("https://a.example/x?y=1");
    for (const bad of ["javascript:alert(1)", "//x/", "https://u@x/", "ftp://x/", "data:text/html,x", " "]) {
      expect(safeHttpUrl(bad)).toBeNull();
    }
    expect(normalizeHost("192.168.37.6")).toBe("192.168.37.6");
    expect(normalizeHost("192.168.37.6:9443")).toBe("192.168.37.6");
    expect(normalizeHost("[fd00::6]")).toBe("fd00::6");
    expect(normalizeHost("ftp://x/")).toBeNull();
  });
});
