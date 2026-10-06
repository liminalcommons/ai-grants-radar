/* Funding Radar UI. Reads ../grants.json (resolves to /grants.json at the site root,
 * or the repo-root file under /site/) or ./grants.json (copy).
 * All text is inserted via textContent - no innerHTML with data. */
(function () {
  const F = window.FundingFilters;
  const SOURCES = ["../grants.json", "grants.json"];
  const UNKNOWN_LABEL = {
    eligibility: "structured eligibility", geography: "geography", entity: "entity requirement",
    applicantTypes: "applicant types", deadline: "deadline date", amount: "amount range",
  };
  let grants = [];
  const $ = id => document.getElementById(id);

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid != null) el.append(kid);
    return el;
  }
  const safeUrl = u => (typeof u === "string" && /^https?:\/\//i.test(u) ? u : null);
  const money = (n, cur) => (n == null ? null :
    (cur && cur !== "USD" ? cur + " " : "$") + Number(n).toLocaleString("en-US"));
  function amountText(g) {
    if (g.amountMin != null || g.amountMax != null) {
      const a = money(g.amountMin, g.currency), b = money(g.amountMax, g.currency);
      return a && b && a !== b ? a + " – " + b : (b || a);
    }
    return g.amount || null;
  }
  function deadlineText(g) {
    const d = F.deadlineOf(g);
    const type = F.deadlineTypeOf(g);
    if (d) return d + (type && type !== "fixed" ? " (" + type + ")" : "");
    return g.deadline || (type === "rolling" ? "Rolling" : null);
  }
  function unknownSpan(t) { return h("span", { class: "unknown", text: t || "unknown" }); }

  function badges(g) {
    const out = [];
    const unk = F.unknownFields(g);
    if (!F.isVerified(g)) {
      out.push(h("span", { class: "badge unverified",
        title: "Unknown: " + unk.map(k => UNKNOWN_LABEL[k] || k).join(", ") }, "unverified"));
    } else out.push(h("span", { class: "badge ok" }, "verified"));
    const days = F.daysUntil(g);
    if (F.isExpired(g)) out.push(h("span", { class: "badge bad" }, "expired"));
    else if (days != null && days <= 14 && F.deadlineTypeOf(g) !== "rolling")
      out.push(h("span", { class: "badge soon" }, days === 0 ? "today" : days + "d left"));
    if (g.fundingType) out.push(h("span", { class: "badge" }, g.fundingType));
    if (g.page && g.page.status && g.page.status !== "ok")
      out.push(h("span", { class: "badge bad" }, "page " + g.page.status));
    return out;
  }

  function readFilters() {
    const f = $("filters"), v = n => f.elements[n].value.trim();
    return {
      q: v("q"), country: v("country").toUpperCase(), entity: v("entity"), applicant: v("applicant"),
      window: +v("window") || 0, minAmount: +v("minAmount") || 0, funding: v("funding"),
      onlyVerified: f.elements.onlyVerified.checked, showExpired: f.elements.showExpired.checked,
    };
  }

  function renderList() {
    const rows = F.sortGrants(F.filterGrants(grants, readFilters()), $("filters").elements.sort.value);
    $("count").textContent = rows.length + " of " + grants.length + " grants";
    const ul = $("grants");
    ul.replaceChildren();
    const frag = document.createDocumentFragment();
    for (const g of rows.slice(0, 300)) {
      const amt = amountText(g), dl = deadlineText(g);
      frag.append(h("li", { class: "grant" + (F.isVerified(g) ? "" : " unverified") },
        h("h2", {}, h("a", { href: "#/grant/" + encodeURIComponent(g.id) }, g.name || "(unnamed)")),
        h("div", { class: "meta" }, g.organization || "", " · ",
          h("span", { class: "amt", text: amt || "amount unknown" }), " · deadline: ", dl || unknownSpan()),
        h("div", { class: "badges" }, badges(g))));
    }
    ul.append(frag);
    if (rows.length > 300) ul.append(h("li", { class: "meta", text: "Showing first 300 – narrow the filters." }));
  }

  function kv(label, value) {
    return [h("dt", { text: label }), h("dd", {}, value == null || value === "" ? unknownSpan() : value)];
  }
  function list(arr) { return Array.isArray(arr) && arr.length ? arr.join(", ") : null; }

  function timelineStep(label, date, cls) {
    return h("li", { class: date ? cls || "" : "unk" },
      h("div", { class: "lbl", text: label }), date ? h("div", { text: date }) : unknownSpan());
  }

  function renderDetail(g) {
    const v = $("detail-view");
    v.replaceChildren();
    const e = g.eligibilityDetail, tl = g.timeline || {}, pg = g.page || {};
    const src = safeUrl(g.url), unk = F.unknownFields(g);
    v.append(
      h("a", { class: "back", href: "#/" }, "← all grants"),
      h("h2", { text: g.name }),
      h("div", { class: "meta", text: [g.organization, g.category].filter(Boolean).join(" · ") }),
      h("div", { class: "badges" }, badges(g)));
    if (unk.length) v.append(h("div", { class: "why",
      text: "Unverified – not yet extracted: " + unk.map(k => UNKNOWN_LABEL[k] || k).join(", ") +
        ". This grant is shown because unknown never means excluded." }));
    if (g.description) v.append(h("p", { text: g.description }));

    v.append(h("h3", { text: "Amount" }),
      h("dl", { class: "kv" }, kv("Amount", amountText(g)), kv("Funding type", g.fundingType)));

    v.append(h("h3", { text: "Eligibility" }), h("dl", { class: "kv" },
      kv("Summary", typeof g.eligibility === "string" ? g.eligibility : null),
      kv("Geography", e && e.geography != null ? [].concat(e.geography).join(", ") : null),
      kv("Entity required", e && e.entityRequired),
      kv("Applicants", e && list(e.applicantTypes)),
      kv("Restrictions", e && list(e.restrictions))));

    v.append(h("h3", { text: "Requirements checklist" }));
    const reqs = Array.isArray(g.requirements) ? g.requirements : [];
    if (reqs.length) {
      v.append(h("ul", { class: "checklist" }, reqs.map(r => {
        const item = typeof r === "string" ? r : r.item, quote = r && r.quote;
        return h("li", { title: quote ? "“" + quote + "”" : null }, item || "", quote ? h("div", { class: "q", text: "“" + quote + "”" }) : null);
      })));
    } else v.append(h("p", {}, unknownSpan("No requirements extracted yet – check the source page.")));

    v.append(h("h3", { text: "Timeline" }), h("ol", { class: "timeline" },
      timelineStep("Opens", tl.opensDate),
      timelineStep("Deadline", F.deadlineOf(g) || (F.deadlineTypeOf(g) === "rolling" ? "Rolling" : null), "dl"),
      timelineStep("Decision", tl.decisionDate)));
    if (tl.durationMonths != null) v.append(h("p", { class: "meta", text: "Duration: " + tl.durationMonths + " months" }));

    v.append(h("h3", { text: "Source" }), h("dl", { class: "kv" },
      kv("Page status", pg.status), kv("Last checked", pg.lastChecked || g._updated && g._updated + " (record updated)"),
      kv("Link", src ? h("a", { href: src, target: "_blank", rel: "noopener noreferrer", text: src }) : null)));

    const actions = h("div", { class: "actions" });
    if (src) actions.append(h("a", { class: "btn", href: src, target: "_blank", rel: "noopener noreferrer" }, "Open source page"));
    if (F.buildIcs(g)) {
      const b = h("button", { class: "btn alt", type: "button" }, "Add to calendar (.ics)");
      b.addEventListener("click", () => downloadIcs(g));
      actions.append(b);
    }
    v.append(actions);
  }

  function downloadIcs(g) {
    const ics = F.buildIcs(g);
    if (!ics) return;
    const url = URL.createObjectURL(new Blob([ics], { type: "text/calendar;charset=utf-8" }));
    const a = h("a", { href: url, download: "grant-" + g.id + "-deadline.ics" });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function route() {
    const m = /^#\/grant\/(.+)$/.exec(location.hash);
    const g = m && grants.find(x => String(x.id) === decodeURIComponent(m[1]));
    $("list-view").hidden = !!g;
    $("detail-view").hidden = !g;
    if (g) { renderDetail(g); window.scrollTo(0, 0); }
  }

  async function load() {
    for (const src of SOURCES) {
      try {
        const r = await fetch(src);
        if (!r.ok) continue;
        const data = await r.json();
        return F.parseGrants(data);
      } catch (_) { /* try next */ }
    }
    throw new Error("Could not load grants.json (serve the repo root over HTTP).");
  }

  load().then(data => {
    grants = data;
    const open = F.filterGrants(grants, {}).length;
    $("summary").textContent = grants.length + " grants · " + open + " open or rolling · " +
      grants.filter(F.isVerified).length + " verified";
    $("filters").addEventListener("input", renderList);
    $("filters").addEventListener("submit", ev => ev.preventDefault());
    window.addEventListener("hashchange", route);
    renderList();
    route();
  }).catch(err => { $("summary").textContent = err.message; });
})();
