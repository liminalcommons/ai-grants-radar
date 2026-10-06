import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const F = createRequire(import.meta.url)("./filters.js");

const NOW = new Date("2026-10-05T12:00:00Z");
const g = (id, o = {}) => ({ id, name: "G" + id, ...o });
const ids = a => a.map(x => x.id);
const el = o => ({ eligibilityDetail: { geography: "global", entityRequired: "none", applicantTypes: ["team"], restrictions: [], ...o } });

test("expired hidden by default, shown on request", () => {
  const rows = [g(1, { deadlineDate: "2026-09-01", deadlineType: "fixed" }),
    g(2, { deadlineDate: "2026-10-05", deadlineType: "fixed" }),
    g(3, { deadlineStatus: "expired" }),
    g(4, { deadlineDate: "2026-01-01", deadlineType: "rolling" })];
  assert.deepEqual(ids(F.filterGrants(rows, {}, NOW)), [2, 4]);
  assert.equal(F.filterGrants(rows, { showExpired: true }, NOW).length, 4);
});

test("country: global, country, restricted, region unknown", () => {
  const rows = [g(1, el({ geography: "global" })), g(2, el({ geography: "country:US" })),
    g(3, el({ geography: "restricted:DE,FR" })), g(4, el({ geography: "region:EU" })), g(5)];
  assert.deepEqual(ids(F.filterGrants(rows, { country: "de" }, NOW)), [1, 3, 4, 5]);
  assert.deepEqual(ids(F.filterGrants(rows, { country: "US" }, NOW)), [1, 2, 4, 5]);
});

test("entity status", () => {
  const rows = [g(1, el({ entityRequired: "none" })), g(2, el({ entityRequired: "company" })),
    g(3, el({ entityRequired: "ngo" })), g(4, el({ entityRequired: "fiscal-sponsor" })), g(5)];
  assert.deepEqual(ids(F.filterGrants(rows, { entity: "none" }, NOW)), [1, 4, 5]);
  assert.deepEqual(ids(F.filterGrants(rows, { entity: "company" }, NOW)), [1, 2, 4, 5]);
  assert.deepEqual(ids(F.filterGrants(rows, { entity: "ngo" }, NOW)), [1, 3, 4, 5]);
});

test("applicant type", () => {
  const rows = [g(1, el({ applicantTypes: ["individual"] })), g(2, el({ applicantTypes: ["org"] })), g(3)];
  assert.deepEqual(ids(F.filterGrants(rows, { applicant: "individual" }, NOW)), [1, 3]);
});

test("deadline window keeps rolling and undated rows", () => {
  const rows = [g(1, { deadlineDate: "2026-10-20", deadlineType: "fixed" }),
    g(2, { deadlineDate: "2026-12-30", deadlineType: "fixed" }),
    g(3, { deadlineType: "rolling" }), g(4, { timeline: { deadlineDate: "2026-10-10" } })];
  assert.deepEqual(ids(F.filterGrants(rows, { window: 30 }, NOW)), [1, 3, 4]);
  assert.deepEqual(ids(F.filterGrants(rows, { window: 90 }, NOW)), [1, 2, 3, 4]);
  assert.deepEqual(ids(F.filterGrants(rows, { window: 7 }, NOW)), [3, 4]);
});

test("min amount uses max then min; unknown kept", () => {
  const rows = [g(1, { amountMax: 100000 }), g(2, { amountMin: 5000 }), g(3, { amountMin: 1, amountMax: 20 }), g(4)];
  assert.deepEqual(ids(F.filterGrants(rows, { minAmount: 50000 }, NOW)), [1, 4]);
});

test("cash vs credits", () => {
  const rows = [g(1, { fundingType: "cash" }), g(2, { fundingType: "credits" }),
    g(3, { fundingType: "mixed" }), g(4, { fundingType: "equity" }), g(5)];
  assert.deepEqual(ids(F.filterGrants(rows, { funding: "credits" }, NOW)), [2, 3, 5]);
  assert.deepEqual(ids(F.filterGrants(rows, { funding: "cash" }, NOW)), [1, 3, 5]);
});

test("only verified + unknownFields", () => {
  const rows = [g(1, el({})), g(2)];
  assert.deepEqual(ids(F.filterGrants(rows, { onlyVerified: true }, NOW)), [1]);
  assert.ok(F.unknownFields(rows[1]).includes("eligibility"));
  assert.ok(!F.unknownFields(g(3, { deadlineType: "rolling" })).includes("deadline"));
});

test("search is AND over words, case-insensitive", () => {
  const rows = [g(1, { description: "Open Source AI fund" }), g(2, { description: "AI only" })];
  assert.deepEqual(ids(F.filterGrants(rows, { q: "open ai" }, NOW)), [1]);
});

test("sort deadline puts undated last; amount desc", () => {
  const rows = [g(1), g(2, { deadlineDate: "2026-12-01" }), g(3, { deadlineDate: "2026-11-01" })];
  assert.deepEqual(ids(F.sortGrants(rows, "deadline")), [3, 2, 1]);
  const a = [g(1, { amountMax: 5 }), g(2, { amountMax: 9 }), g(3)];
  assert.deepEqual(ids(F.sortGrants(a, "amount")), [2, 1, 3]);
});

test("ics", () => {
  assert.equal(F.buildIcs(g(1), NOW), null);
  const ics = F.buildIcs(g(7, { name: "A, B; C", deadlineDate: "2026-12-31", url: "https://x.org" }), NOW);
  assert.match(ics, /^BEGIN:VCALENDAR\r\n/);
  assert.match(ics, /DTSTART;VALUE=DATE:20261231\r\n/);
  assert.match(ics, /DTEND;VALUE=DATE:20270101\r\n/);
  assert.match(ics, /SUMMARY:Deadline: A\\, B\\; C\r\n/);
  assert.match(ics, /END:VCALENDAR\r\n$/);
});
