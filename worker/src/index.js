// grants-bot — Cloudflare Worker that proxies the Funding Radar chat to the
// OpenCode Zen "Go" plan (OpenAI-compatible). The API key lives ONLY here as a
// Worker secret (OPENCODE_GO_API_KEY) — never in the static page.
//
// The browser POSTs { messages:[{role,content}], candidates:[...] }. We ground the
// model on the supplied candidates so it can only recommend real, listed grants.
//
// Deploy:  npx wrangler deploy
// Secret:  echo $OPENCODE_GO_API_KEY | npx wrangler secret put OPENCODE_GO_API_KEY

const UPSTREAM = "https://opencode.ai/zen/go/v1/chat/completions";
const ALLOW = "https://liminalcommons.github.io";

// ---- citations: every URL in a reply must be a verbatim candidate URL ----

/** Normalise for comparison: host case + trailing slash must not break a match. */
export function normalizeUrl(u) {
  try {
    const x = new URL(String(u).trim());
    x.hash = "";
    let s = x.toString();
    if (s.endsWith("/") && x.pathname === "/") s = s.slice(0, -1);
    if (s.length > 1 && s.endsWith("/")) s = s.slice(0, -1);
    return s;
  } catch {
    return String(u || "").trim().replace(/\/+$/, "");
  }
}

/** Pull markdown-link targets and bare http(s) URLs out of model text. */
export function extractUrls(text) {
  const found = [];
  const md = String(text || "").match(/\[[^\]]*\]\((https?:\/\/[^)\s]+)\)/g) || [];
  for (const m of md) {
    const u = m.slice(m.lastIndexOf("(") + 1, -1).trim();
    if (u) found.push(u);
  }
  const bare = String(text || "").match(/https?:\/\/[^\s<>"')\]]+/g) || [];
  for (let u of bare) {
    u = u.replace(/[).,;:!?]+$/, "");
    if (u && !found.includes(u)) found.push(u);
  }
  return found;
}

/** Check every URL in the reply against the candidate apply URLs. */
export function verifyCitations(text, candidates) {
  const allowed = new Set(
    (Array.isArray(candidates) ? candidates : [])
      .map((c) => c && normalizeUrl(c.url))
      .filter(Boolean)
  );
  const urls = extractUrls(text);
  const bad = urls.filter((u) => !allowed.has(normalizeUrl(u)));
  return { urls, bad, ok: bad.length === 0 };
}

/** Deterministic no-LLM fallback: list the candidates with exact URLs only. */
export function fallbackReply(candidates) {
  const list = (candidates || []).slice(0, 5);
  if (!list.length) {
    return "No open matches in the current list — try “Any field”, or tell me more about your work.";
  }
  const lines = list.map((g) => {
    const name = g && g.name ? String(g.name) : "Unnamed grant";
    const amt = g && g.amount ? ` — ${g.amount}` : "";
    const dl = g && g.deadline ? ` · ${g.deadline}` : "";
    return `**${name}**${amt}${dl}\n${(g && g.url) || ""}`;
  });
  return (
    "Here are your best matches:\n\n" +
    lines.join("\n\n") +
    "\n\nTip: open each link to confirm you fit before applying."
  );
}

export function buildSystemPrompt(candidates) {
  return `You are the matching assistant for "Funding Radar", a curated list of real funding opportunities.

CRITICAL OUTPUT RULES:
- Reply with ONLY the final message to the user. Do NOT think out loud, do NOT restate or analyze the candidates, do NOT explain your process. Start immediately with the answer.
- Recommend ONLY from the CANDIDATES JSON below. Never invent programs, amounts, deadlines, or URLs.

Priorities when choosing: (1) deadline NOT expired — open/rolling first; (2) real cash over cloud credits; (3) low-effort applications; (4) fit to the user.

FORMAT exactly like this:
Here are your best matches:

**<Name>** — <one line on why it fits>
💰 <amount> · 📅 <deadline> · <apply URL>

(3 to 5 of these, best first)

Then one short practical tip starting with "Tip:". Keep the whole reply under 220 words. If nothing fits, say so in one sentence.

CITATIONS (must follow — replies with other URLs are rejected automatically):
- The ONLY links or URLs in your reply are the exact apply URLs copied verbatim from CANDIDATES below.
- Every grant you name MUST show its exact URL on its 💰 line. Copy it character-for-character: never shorten, reformat, paraphrase, or invent a URL.
- Never link or mention any site, program, or URL that is not in CANDIDATES.

CANDIDATES: ${JSON.stringify(candidates)}`;
}

function corsHeaders(origin) {
  const allow = origin && origin.startsWith(ALLOW) ? origin : ALLOW;
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Vary": "Origin",
  };
}
function json(obj, status, cors) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { ...cors, "Content-Type": "application/json" },
  });
}

export default {
  async fetch(req, env) {
    const cors = corsHeaders(req.headers.get("Origin"));
    if (req.method === "OPTIONS") return new Response(null, { headers: cors });
    if (req.method !== "POST") return json({ error: "POST only" }, 405, cors);

    let body;
    try { body = await req.json(); } catch { return json({ error: "bad json" }, 400, cors); }

    const history = (Array.isArray(body.messages) ? body.messages : [])
      .filter(m => m && (m.role === "user" || m.role === "assistant") && typeof m.content === "string")
      .slice(-8);
    const candidates = (Array.isArray(body.candidates) ? body.candidates : []).slice(0, 24);

    // OpenCode Go routes on a stable per-conversation session id (+ identifying UA).
    const session = (typeof body.session === "string" && /^[A-Za-z0-9-]{8,64}$/.test(body.session))
      ? body.session
      : crypto.randomUUID();

    const sys = buildSystemPrompt(candidates);

    const payload = {
      model: body.model || "deepseek-v4.1-flash",
      max_tokens: 800,
      temperature: 0.4,
      messages: [{ role: "system", content: sys }, ...history],
    };

    let data;
    try {
      const r = await fetch(UPSTREAM, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": "Bearer " + env.OPENCODE_GO_API_KEY,
          "x-opencode-session": session,
          "User-Agent": "grants-bot/1.0",
        },
        body: JSON.stringify(payload),
      });
      data = await r.json();
    } catch (e) {
      return json({ error: "upstream failed", detail: String(e) }, 502, cors);
    }
    let text = data?.choices?.[0]?.message?.content || data?.error?.message || "Sorry, I couldn't generate a reply just now.";
    // Citation guard: no extra LLM call — an uncited/invented URL fails
    // closed into the deterministic candidate list instead.
    const check = verifyCitations(text, candidates);
    if (!check.ok) {
      text = fallbackReply(candidates.length ? candidates : []);
      return json({ text, fallback: true, rejectedUrls: check.bad }, 200, cors);
    }
    return json({ text }, 200, cors);
  },
};
