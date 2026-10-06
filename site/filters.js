/* Pure filter/sort logic for the Funding Radar site. No DOM access.
 * Works as a browser global (FundingFilters) and as a CommonJS module.
 * Missing contract fields mean "unknown": such rows are never excluded by a
 * filter they cannot answer; they get an "unverified" flag instead. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.FundingFilters = api;
})(typeof self !== "undefined" ? self : this, function () {
  const DAY = 86400000;

  function isoToUtc(s) {
    if (typeof s !== "string") return null;
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
    if (!m) return null;
    const t = Date.UTC(+m[1], +m[2] - 1, +m[3]);
    return Number.isNaN(t) ? null : t;
  }
  function toDate(now) {
    return now instanceof Date ? now : new Date(now == null ? Date.now() : now);
  }
  function todayUtc(now) {
    const d = toDate(now);
    return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
  }
  function deadlineOf(g) {
    return (g.timeline && g.timeline.deadlineDate) || g.deadlineDate || null;
  }
  function deadlineTypeOf(g) {
    return (g.timeline && g.timeline.deadlineType) || g.deadlineType || null;
  }
  function geographyOf(g) {
    const e = g.eligibilityDetail;
    if (!e || e.geography == null || e.geography === "") return null;
    return Array.isArray(e.geography) ? e.geography : [e.geography];
  }

  function isExpired(g, now) {
    if (g.deadlineStatus === "expired") return true;
    const t = isoToUtc(deadlineOf(g));
    const type = deadlineTypeOf(g);
    if (t == null || type === "rolling" || type === "recurring") return false;
    return t < todayUtc(now);
  }

  /* Which contract fields are unknown for this grant. */
  function unknownFields(g) {
    const out = [];
    const e = g.eligibilityDetail;
    if (!e || typeof e !== "object") out.push("eligibility");
    else {
      if (geographyOf(g) == null) out.push("geography");
      if (e.entityRequired == null) out.push("entity");
      if (!Array.isArray(e.applicantTypes) || !e.applicantTypes.length) out.push("applicantTypes");
    }
    const type = deadlineTypeOf(g);
    if (isoToUtc(deadlineOf(g)) == null && type !== "rolling" && type !== "recurring") out.push("deadline");
    if (g.amountMin == null && g.amountMax == null) out.push("amount");
    return out;
  }
  /* "Verified" = structured eligibility present (geography + entity known). */
  function isVerified(g) {
    const e = g.eligibilityDetail;
    return !!(e && typeof e === "object" && geographyOf(g) != null && e.entityRequired != null);
  }

  /* Matchers return true / false / null (null = unknown, keep the row). */
  function matchCountry(g, cc) {
    if (!cc) return true;
    const geo = geographyOf(g);
    if (!geo) return null;
    cc = cc.toUpperCase();
    let unknown = false;
    for (const raw of geo) {
      const v = String(raw);
      if (v === "global") return true;
      if (v.startsWith("country:")) {
        if (v.slice(8).toUpperCase() === cc) return true;
      } else if (v.startsWith("restricted:")) {
        if (v.slice(11).toUpperCase().split(",").map(s => s.trim()).includes(cc)) return true;
      } else unknown = true; // region:name - no region table, cannot answer
    }
    return unknown ? null : false;
  }
  function matchEntity(g, status) {
    if (!status) return true;
    const e = g.eligibilityDetail;
    const req = e && e.entityRequired;
    if (req == null) return null;
    if (req === "none" || req === "fiscal-sponsor") return true;
    if (req === status) return true;
    if (req === "org" && status === "ngo") return true; // an NGO is an organisation
    return false;
  }
  function matchApplicant(g, type) {
    if (!type) return true;
    const e = g.eligibilityDetail;
    const t = e && e.applicantTypes;
    if (!Array.isArray(t) || !t.length) return null;
    return t.includes(type);
  }
  function matchWindow(g, days, now) {
    if (!days) return true;
    const t = isoToUtc(deadlineOf(g));
    const type = deadlineTypeOf(g);
    if (t == null || type === "rolling") return null;
    const today = todayUtc(now);
    return t >= today && t <= today + days * DAY;
  }
  function matchAmount(g, min) {
    if (!min) return true;
    const top = g.amountMax != null ? g.amountMax : g.amountMin;
    if (top == null) return null;
    return top >= min;
  }
  function matchFunding(g, kind) {
    if (!kind) return true;
    const f = g.fundingType;
    if (!f) return null;
    if (f === "mixed") return kind === "cash" || kind === "credits";
    return f === kind;
  }
  function matchSearch(g, q) {
    q = (q || "").trim().toLowerCase();
    if (!q) return true;
    const hay = [g.name, g.organization, g.description, g.category,
      typeof g.eligibility === "string" ? g.eligibility : "", (g.tags || []).join(" ")]
      .join(" ").toLowerCase();
    return q.split(/\s+/).every(w => hay.includes(w));
  }

  /* f: {q, country, entity, applicant, window, minAmount, funding, onlyVerified, showExpired} */
  function filterGrants(grants, f, now) {
    f = f || {};
    return grants.filter(g => {
      if (!f.showExpired && isExpired(g, now)) return false;
      if (f.onlyVerified && !isVerified(g)) return false;
      if (!matchSearch(g, f.q)) return false;
      return matchCountry(g, f.country) !== false
        && matchEntity(g, f.entity) !== false
        && matchApplicant(g, f.applicant) !== false
        && matchWindow(g, f.window, now) !== false
        && matchAmount(g, f.minAmount) !== false
        && matchFunding(g, f.funding) !== false;
    });
  }

  /* Sort keys: deadline (soonest first, undated last), amount (largest first), name. */
  function sortGrants(grants, key) {
    const byName = (a, b) => String(a.name).localeCompare(String(b.name));
    const topAmount = a => (a.amountMax != null ? a.amountMax : a.amountMin);
    const cmp = {
      deadline: (a, b) => {
        const x = isoToUtc(deadlineOf(a)), y = isoToUtc(deadlineOf(b));
        if (x == null && y == null) return byName(a, b);
        if (x == null) return 1;
        if (y == null) return -1;
        return x - y || byName(a, b);
      },
      amount: (a, b) => {
        const x = topAmount(a), y = topAmount(b);
        if (x == null && y == null) return byName(a, b);
        if (x == null) return 1;
        if (y == null) return -1;
        return y - x || byName(a, b);
      },
      name: byName,
    }[key] || byName;
    return grants.slice().sort(cmp);
  }

  function daysUntil(g, now) {
    const t = isoToUtc(deadlineOf(g));
    return t == null ? null : Math.round((t - todayUtc(now)) / DAY);
  }

  /* RFC 5545 all-day event for the deadline; null if no valid date. */
  function icsEscape(s) {
    return String(s == null ? "" : s).replace(/\\/g, "\\\\").replace(/;/g, "\\;")
      .replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");
  }
  function fold(line) {
    const out = [];
    while (line.length > 74) { out.push(line.slice(0, 74)); line = " " + line.slice(74); }
    out.push(line);
    return out.join("\r\n");
  }
  function buildIcs(g, now) {
    const t = isoToUtc(deadlineOf(g));
    if (t == null) return null;
    const ymd = ms => new Date(ms).toISOString().slice(0, 10).replace(/-/g, "");
    const stamp = toDate(now).toISOString().replace(/[-:]/g, "").replace(/\.\d+/, "");
    const lines = [
      "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//AI Funding Radar//EN", "CALSCALE:GREGORIAN",
      "BEGIN:VEVENT",
      "UID:grant-" + g.id + "-" + ymd(t) + "@funding-radar",
      "DTSTAMP:" + stamp,
      "DTSTART;VALUE=DATE:" + ymd(t),
      "DTEND;VALUE=DATE:" + ymd(t + DAY),
      "SUMMARY:" + icsEscape("Deadline: " + g.name),
      "DESCRIPTION:" + icsEscape([g.organization, g.amount, g.url].filter(Boolean).join(" | ")),
    ];
    if (g.url) lines.push("URL:" + g.url);
    lines.push("BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:" + icsEscape(g.name + " deadline in 3 days"),
      "TRIGGER:-P3D", "END:VALARM", "END:VEVENT", "END:VCALENDAR");
    return lines.map(fold).join("\r\n") + "\r\n";
  }

  // Accepts a bare array or {grants: [...]}; anything else yields [].
  function parseGrants(data) {
    return Array.isArray(data) ? data : (data && Array.isArray(data.grants) ? data.grants : []);
  }

  return { parseGrants, filterGrants, sortGrants, isExpired, isVerified, unknownFields, daysUntil,
    deadlineOf, deadlineTypeOf, buildIcs, isoToUtc };
});
