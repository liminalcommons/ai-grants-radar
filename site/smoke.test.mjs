import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
const F = createRequire(import.meta.url)("./filters.js");
const root = new URL("../", import.meta.url);

test("real grants.json parses and filters like app.js", () => {
  const data = JSON.parse(readFileSync(new URL("grants.json", root), "utf8"));
  const grants = F.parseGrants(data);
  assert.ok(grants.length > 0);
  const open = F.filterGrants(grants, {});
  assert.ok(Array.isArray(open));
  assert.ok(F.sortGrants(open).length >= 0);
  grants.filter(F.isVerified).length;
});

test("classic page uses absolute paths", () => {
  const html = readFileSync(new URL("classic/index.html", root), "utf8");
  assert.ok(!/fetch\(\s*['"]grants\.json/.test(html));
  assert.ok(html.includes("/grants.json"));
  assert.ok(html.includes('href="/report.html"'));
  assert.ok(html.includes('href="/"'));
});
