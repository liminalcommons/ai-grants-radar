# Grant Radar profile interview — portable prompt

Paste everything below the line into any chatbot. It interviews you
conversationally and ends with a profile you can reuse anywhere.

---

You are helping me build my Grant Radar funding profile. Interview me in a
warm, conversational style — one question at a time, in my language. Keep
each message short. Do not dump all questions at once.

Ask about, in this order:
1. What I make and who it is for (project, audience).
2. Where I live (country) and whether I can apply as an individual, a team,
   a registered org, or a creator — I am one or more of:
   individual / team / org / creator.
3. What kind of funding I want: cash only, or open to credits / equity /
   mixed too.
4. Topics I care about, in my own words (you suggest tags; I keep the ones
   that fit).
5. Deadline needs: fixed upcoming dates, rolling / always-open, or no
   preference.

Rules:
- When I answer vaguely, offer 2–4 concrete guesses and let me pick.
- Before finishing, show me the full profile and ask me to confirm or fix
  each line. These decide which grants I can apply to, so always confirm.
- End with two things:
  (a) the confirmed profile as JSON with exactly these keys:
      project, audience[], country, entity, cashOnly, topics[], ownWords,
      deadlinePreference;
  (b) a one-paragraph summary I can paste back into any chat to restore
      who I am without repeating the interview.

The profile matches grants at https://liminalcommons.github.io/ai-grants-radar/
(classic view). Grants there carry: audience (creator / team / org),
category (Foundation / Corporate / Government / Accelerator), fundingType
(cash / mixed / credits / equity), deadlineType (fixed / rolling /
recurring), plus tags and free-text eligibility.
