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

    const sys = `You are the matching assistant for "Funding Radar", a curated list of real funding opportunities.

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

CANDIDATES: ${JSON.stringify(candidates)}`;

    const payload = {
      model: body.model || "glm-5.1",
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
        },
        body: JSON.stringify(payload),
      });
      data = await r.json();
    } catch (e) {
      return json({ error: "upstream failed", detail: String(e) }, 502, cors);
    }
    const text = data?.choices?.[0]?.message?.content || data?.error?.message || "Sorry, I couldn't generate a reply just now.";
    return json({ text }, 200, cors);
  },
};
