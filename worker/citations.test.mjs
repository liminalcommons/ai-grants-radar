import test from "node:test";
import assert from "node:assert/strict";
import {
  buildSystemPrompt,
  extractUrls,
  fallbackReply,
  normalizeUrl,
  verifyCitations,
} from "./src/index.js";

const CANDS = [
  { name: "Alpha Fund", amount: "$10k", deadline: "2026-12-01", url: "https://example.org/alpha" },
  { name: "Beta Prize", amount: "$5k", deadline: "Rolling", url: "https://example.org/beta/" },
];

test("system prompt carries the verbatim-URL citation rules + candidates", () => {
  const sys = buildSystemPrompt(CANDS);
  assert.ok(sys.includes("copied verbatim from CANDIDATES"));
  assert.ok(sys.includes("character-for-character"));
  assert.ok(sys.includes("https://example.org/alpha"));
  assert.ok(sys.includes("Recommend ONLY from the CANDIDATES JSON"));
});

test("extractUrls finds bare + markdown URLs, strips trailing punctuation", () => {
  const urls = extractUrls(
    "See https://example.org/alpha. Or [Beta](https://example.org/beta/)!"
  );
  assert.deepEqual(urls, ["https://example.org/beta/", "https://example.org/alpha"]);
});

test("normalizeUrl ignores trailing slash so 'beta/' matches 'beta'", () => {
  assert.equal(normalizeUrl("https://example.org/beta/"), normalizeUrl("https://example.org/beta"));
});

test("verifyCitations passes when every URL is a candidate URL", () => {
  const text = "**Alpha Fund** — fits\n💰 $10k · 📅 2026-12-01 · https://example.org/alpha\n\n**Beta Prize** — fits\n💰 $5k · 📅 Rolling · https://example.org/beta/";
  const r = verifyCitations(text, CANDS);
  assert.equal(r.ok, true);
  assert.deepEqual(r.bad, []);
  assert.equal(r.urls.length, 2);
});

test("verifyCitations flags an invented URL", () => {
  const r = verifyCitations("Try https://evil.example/steal instead", CANDS);
  assert.equal(r.ok, false);
  assert.deepEqual(r.bad, ["https://evil.example/steal"]);
});

test("verifyCitations passes text with no URLs at all", () => {
  assert.equal(verifyCitations("No open matches, sorry.", CANDS).ok, true);
});

test("fallbackReply lists candidates with exact URLs and nothing else", () => {
  const t = fallbackReply(CANDS);
  assert.ok(t.includes("**Alpha Fund**"));
  assert.ok(t.includes("https://example.org/alpha"));
  assert.ok(t.includes("https://example.org/beta/"));
  assert.ok(t.startsWith("Here are your best matches:"));
  assert.ok(!/evil\.example/.test(t));
});

test("fallbackReply with no candidates says so in one sentence", () => {
  assert.equal(
    fallbackReply([]),
    "No open matches in the current list — try “Any field”, or tell me more about your work."
  );
});
