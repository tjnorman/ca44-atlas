// CA-44 Atlas: one page that reads data/*.json and draws the district under both plans.
// Every number shown comes from a data file with its source; estimates by the atlas are marked "est."

import { int, one, pct, usd, longDate, esc } from "./format.js";

const params = new URLSearchParams(location.search);
const BASE = params.get("data") || "data/";
const $ = (s) => document.querySelector(s);
const get = (f) => fetch(`${BASE}${f}.json`).then((r) => (r.ok ? r.json() : null)).catch(() => null);
const D = (x) => (x && x.data) || null;
const EST = '<span class="est" title="Estimate by the atlas, not a Census Bureau tabulation">est.</span>';

function table(head, rows, numeric = []) {
  if (!rows.length) return '<p class="sub">Not available in this build.</p>';
  const th = head.map((h, i) => `<th class="${numeric.includes(i) ? "num" : ""}">${h}</th>`).join("");
  const tr = rows.map((r) => `<tr>${r.map((c, i) => `<td class="${numeric.includes(i) ? "num" : ""}">${c ?? "n/a"}</td>`).join("")}</tr>`).join("");
  return `<table><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table>`;
}

function srcLink(id) {
  return id ? `<a class="src" href="#src-${esc(id)}">${esc(id)}</a>` : "";
}

async function main() {
  const names = ["summary", "plans", "acs", "acs_plan", "laus", "ports", "projects", "cameras", "airports", "integrity", "legislators", "elections", "fec", "votes", "usaspending", "irs", "colleges", "broadcast", "manifest"];
  const raw = Object.fromEntries(await Promise.all(names.map(async (n) => [n, await get(n)])));
  const topo = await fetch(`${BASE}geo/district.topo.json`).then((r) => (r.ok ? r.json() : null)).catch(() => null);
  const S = raw.summary || {};
  const P = D(raw.plans);
  if (!P) {
    $("#main").insertAdjacentHTML("afterbegin", '<p class="panel">The plans data file is missing; run the pipeline first.</p>');
    return;
  }
  const plans = P.plans;
  const ids = Object.keys(plans);
  const primary = P.primary;
  const other = ids.find((i) => i !== primary);
  const label = (pid) => (pid === primary ? "New lines" : "2021 lines");

  drawGlance(S, P, D(raw.acs), D(raw.legislators));
  drawBridge(D(raw.projects), D(raw.cameras));
  drawMap(topo, P, D(raw.ports), D(raw.cameras), D(raw.airports));
  drawOverlap(P);
  drawPlans(P);
  drawPlaces(P);
  drawPeople(D(raw.acs), D(raw.acs_plan), P);
  drawWork(D(raw.laus));
  drawPorts(D(raw.ports));
  drawAround(D(raw.cameras), D(raw.airports));
  drawSeat(D(raw.legislators), D(raw.elections), D(raw.votes), D(raw.fec));
  drawMoney(D(raw.usaspending), D(raw.irs));
  drawInstitutions(D(raw.colleges), D(raw.broadcast), P);
  drawChecks(raw.integrity);
  drawSources(S.sources || []);
  $("#footer").innerHTML = `CA-44 Atlas · Published by ${esc(S.district?.publisher || "Thomas J. Norman")} as a personal, nonpartisan project. `
    + `Not a product of the Northwest San Pedro Neighborhood Council, California State University, Dominguez Hills, or any campaign, party, or officeholder. `
    + `Data built ${longDate(S.built_at)} from the public records listed under <a href="#sources">Sources</a>. `
    + `Code MIT; text and tables CC BY 4.0. <a href="#about">About</a> · <a href="https://github.com/tjnorman/ca44-atlas">Repository</a>.`;

  function drawGlance(S, P, acs, leg) {
    const pr = plans[primary], ol = plans[other];
    const m = acs?.district?.metrics || {};
    const cells = [
      [int(pr.pop_2020), `People in 2020, new lines`, "2020 Census blocks"],
      [int(P.overlap?.pop_both), `People in both versions`, `${pct(100 * P.overlap.pop_both / pr.pop_2020, 0)} of the new district`],
      [one(pr.land_sq_mi), `Square miles of land, new lines`, `${one(ol.land_sq_mi)} under the 2021 lines`],
      [leg?.current ? `<span class="name">${esc(leg.current.name)}</span>` : "n/a", "Member of Congress", leg?.current ? `${esc(leg.current.party)}, since ${leg.terms?.find((t) => t.name === leg.current.name)?.start?.slice(0, 4) || ""}` : ""],
    ];
    if (m.median_household_income) cells.push([usd(m.median_household_income), "Median household income, 2021 lines", `ACS ${acs.vintage.acs1} 1-year`]);
    $("#glance").innerHTML = cells.slice(0, 4).map(([n, l, s]) => `<div class="stat"><div class="num">${n}</div><div class="lab">${l}</div><div class="moe">${s}</div></div>`).join("");
  }

  function drawMap(topo, P, ports, cams, airports) {
    const el = $("#map");
    if (!topo || !window.d3 || !window.topojson) { el.innerHTML = '<p class="sub">Map data unavailable.</p>'; return; }
    const W = 900, H = 820;
    const obj = (k) => (topo.objects[k] ? topojson.feature(topo, topo.objects[k]) : { type: "FeatureCollection", features: [] });
    const layers = Object.fromEntries(ids.map((pid) => [pid, obj(`plan_${pid}`)]));
    const both = { type: "FeatureCollection", features: ids.flatMap((pid) => layers[pid].features) };
    const proj = d3.geoMercator().fitExtent([[20, 20], [W - 20, H - 20]], both);
    const path = d3.geoPath(proj);
    const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img")
      .attr("aria-label", "CA-44 under the new lines (solid) and the 2021 lines (dashed), with city outlines");
    svg.append("g").selectAll("path").data(obj("counties").features).join("path").attr("class", "county").attr("d", path);
    const places = obj("places").features;
    svg.append("g").selectAll("path").data(places).join("path").attr("class", "place").attr("d", path);
    for (const pid of [other, primary]) {
      svg.append("g").attr("class", `plan plan-${pid}`).attr("data-plan", pid).selectAll("path").data(layers[pid].features).join("path").attr("d", path);
    }
    // Labels at each place's population center inside the district (from 2020 blocks), largest first;
    // a label is skipped when it would overlap one already drawn.
    const pts = new Map();
    for (const pid of [primary, other]) for (const r of plans[pid].places) {
      if (!r.place || r.label_lon == null || r.pop_in_district < 10000) continue;
      const prev = pts.get(r.place);
      if (!prev || r.pop_in_district > prev.pop) pts.set(r.place, { name: r.short, pop: r.pop_in_district, lon: r.label_lon, lat: r.label_lat });
    }
    const placed = [];
    const g = svg.append("g");
    for (const p of [...pts.values()].sort((a, b) => b.pop - a.pop)) {
      const [x, y] = proj([p.lon, p.lat]);
      const w = p.name.length * 6.6 + 8, h = 15;
      const box = [x - w / 2, y - h / 2, x + w / 2, y + h / 2];
      if (placed.some((b) => !(box[2] < b[0] || box[0] > b[2] || box[3] < b[1] || box[1] > b[3]))) continue;
      placed.push(box);
      g.append("text").attr("class", "plabel").attr("x", x).attr("y", y + 4).text(p.name);
    }
    if (ports?.docks?.length) {
      svg.append("g").selectAll("circle").data(ports.docks.filter((x) => x.lon != null)).join("circle")
        .attr("class", (x) => `dock dock-${x.port}`).attr("r", 2.6)
        .attr("cx", (x) => proj([x.lon, x.lat])[0]).attr("cy", (x) => proj([x.lon, x.lat])[1])
        .append("title").text((x) => `${x.name} (${x.port === "pola" ? "Port of Los Angeles" : "Port of Long Beach"})`);
    }
    if (cams?.cameras?.length) {
      svg.append("g").selectAll("rect").data(cams.cameras).join("rect").attr("class", "cam")
        .attr("width", 4).attr("height", 4).attr("x", (c) => proj([c.lon, c.lat])[0] - 2).attr("y", (c) => proj([c.lon, c.lat])[1] - 2)
        .append("title").text((c) => `Caltrans camera: ${c.name}`);
    }
    if (airports?.facilities?.length) {
      svg.append("g").selectAll("path.apt").data(airports.facilities).join("path").attr("class", "apt")
        .attr("d", (a) => { const [x, y] = proj([a.lon, a.lat]); return `M${x},${y - 5}L${x + 4.5},${y + 3.5}L${x - 4.5},${y + 3.5}Z`; })
        .append("title").text((a) => `${a.type}: ${a.name}`);
    }
    $("#map-legend").innerHTML = (cams?.cameras?.length ? `<span><i class="dot-k cam-k"></i>Caltrans cameras</span>` : "")
      + (airports?.facilities?.length ? `<span><i class="tri-k"></i>Airports and heliports</span>` : "")
      + (ports?.docks?.length ? `<span><i class="dot-k pola"></i>Port of Los Angeles docks</span><span><i class="dot-k polb"></i>Port of Long Beach docks</span>` : "") + `<span><i class="swatch"></i>New lines (from Jan. 3, 2027)</span><span><i class="swatch old"></i>2021 lines (through Jan. 3, 2027)</span><span>Gray lines: city and place boundaries (Census cartographic boundary file). Each label sits at the population center of that place\'s part of the district; places with more than 10,000 residents in either version.</span>`;
    document.querySelectorAll("#plan-toggle button").forEach((b) => b.addEventListener("click", () => {
      document.querySelectorAll("#plan-toggle button").forEach((x) => x.classList.toggle("on", x === b));
      const show = b.dataset.show;
      svg.selectAll("g.plan").classed("off", function () { return show !== "both" && this.dataset.plan !== show; });
    }));
  }

  function drawOverlap(P) {
    const o = P.overlap;
    if (!o) return;
    const pr = plans[primary], ol = plans[other];
    $("#maps-lede").innerHTML = `California redrew its congressional map for 2026. Of the ${int(pr.pop_2020)} people in the new CA-44 in 2020, `
      + `${int(o.pop_both)} also lived in the 2021 version. About ${int(o.pop_only_a)} join and ${int(o.pop_only_b)} leave.`;
    const rows = (list) => list.filter((r) => r.pop > 0).map((r) => [esc(r.name), int(r.pop)]);
    $("#joining").innerHTML = table(["Place", "People (2020)"], rows(o.places_only_a), [1]);
    $("#leaving").innerHTML = table(["Place", "People (2020)"], rows(o.places_only_b), [1]);
  }

  function drawPlans(P) {
    const rows = [primary, other].map((pid) => {
      const p = plans[pid];
      return [`<span class="tag ${pid === primary ? "new" : "old"}">${label(pid)}</span>${esc(p.label)}`,
        int(p.pop_2020), one(p.land_sq_mi), one(p.water_sq_mi), int(p.blocks),
        p.effective ? longDate(p.effective) : "n/a", esc(p.law)];
    });
    $("#plan-table").innerHTML = table(["Plan", "People (2020)", "Land (sq mi)", "Water (sq mi)", "Census blocks", "In effect", "Basis"], rows, [1, 2, 3, 4]);
    $("#plan-note").innerHTML = `Both plans are read from the Census Bureau's block equivalency files ${srcLink("census-bef-120")} ${srcLink("census-bef-119")}, with 2020 block populations ${srcLink("census-pl")} and block areas ${srcLink("census-tiger-blocks")}. Both versions lie entirely within Los Angeles County.`;
  }

  function drawPlaces(P) {
    const tog = $("#places-toggle");
    tog.innerHTML = [primary, other].map((pid, i) => `<button data-plan="${pid}" class="${i === 0 ? "on" : ""}">${label(pid)}</button>`).join("");
    const render = (pid) => {
      const p = plans[pid];
      const max = Math.max(...p.places.map((r) => r.pop_in_district));
      $("#places-table").innerHTML = table(["Place", "Type", "People in district (2020)", "Share of the place in the district"],
        p.places.map((r) => [`${esc(r.short)}<span class="bar" style="width:${Math.round(80 * r.pop_in_district / max)}px"></span>`,
          r.type === "CDP" ? "Unincorporated community (CDP)" : r.type === "city" ? "City" : "Unincorporated",
          int(r.pop_in_district), r.share_of_place == null ? "n/a" : pct(100 * r.share_of_place, r.share_of_place < 0.1 ? 1 : 0)]), [2, 3]);
      $("#places-title").textContent = `Places, ${label(pid).toLowerCase()}`;
    };
    tog.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
      tog.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
      render(b.dataset.plan);
    }));
    render(primary);
  }

  function drawPeople(acs, ap, P) {
    if (!acs && !ap) { $("#people-table").innerHTML = '<p class="sub">ACS data not available in this build.</p>'; return; }
    const cur = acs?.district?.metrics || {};
    const cur5 = acs?.district_5yr?.metrics || {};
    const st = acs?.state?.metrics || {};
    const us = acs?.us?.metrics || {};
    const nw = ap?.plans?.[primary]?.metrics || {};
    const y1 = acs?.vintage?.acs1, y5 = ap?.vintage?.acs5 || acs?.vintage?.acs5;
    const defs = (acs?.metrics || []).filter((m) => m.id !== "seasonal_homes_pct");
    const fmt = (v, unit) => (v == null ? "n/a" : unit === "usd" ? usd(v) : unit === "pct" ? pct(v) : unit === "count" ? int(v) : unit === "minutes" ? `${one(v)} min` : one(v));
    const rows = defs.map((m) => [esc(m.label), fmt(cur[m.id], m.unit), fmt(cur5[m.id], m.unit),
      nw[m.id] == null ? '<span class="sub">not estimated</span>' : fmt(nw[m.id], m.unit) + EST, fmt(st[m.id], m.unit), fmt(us[m.id], m.unit)]);
    $("#people-table").innerHTML = table(["Measure", `2021 lines, ACS ${y1} 1-year`, `2021 lines, ACS ${y5 ? `${y5 - 4}–${y5}` : ""} 5-year`,
      `New lines, ACS ${y5 ? `${y5 - 4}–${y5}` : ""} 5-year`, "California", "United States"], rows, [1, 2, 3, 4, 5]);
    $("#people-lede").innerHTML = "The Census Bureau publishes survey figures for the district as it is drawn today (the 2021 lines). "
      + "For the new lines, the atlas estimates the same measures from census tracts.";
    $("#people-note").innerHTML = `American Community Survey ${srcLink("acs1")} ${srcLink("acs5")} ${srcLink("acs5-tracts")}. Figures are survey estimates; small differences may not be meaningful. `
      + `"est.": computed by the atlas from tract figures weighted by 2020 block population. Medians and averages cannot be added across tracts and are not estimated for the new lines.`;
    const mc = ap?.method_check;
    if (mc) {
      const kindFmt = (v, k) => (k === "count" ? int(v) : pct(v));
      $("#method-table").innerHTML = table(["Measure", "Census Bureau, 2021 lines", "Tract method, 2021 lines", "Difference", "Within tolerance"],
        mc.comparisons.map((c) => [esc((acs?.metrics || []).find((m) => m.id === c.metric)?.label || c.metric), kindFmt(c.census, c.kind), kindFmt(c.method, c.kind),
          c.kind === "count" ? pct(100 * c.gap, 2) : `${c.gap >= 0 ? "+" : ""}${c.gap.toFixed(2)} pts`, c.ok ? "Yes" : "No"]), [1, 2, 3]);
      $("#method-note").innerHTML = "To test the estimate, the atlas runs the same tract calculation for the 2021 lines, which the Census Bureau does tabulate, and compares the two. Tolerance: 1% for counts, 1.5 percentage points for shares.";
    } else {
      $("#method-table").innerHTML = '<p class="sub">The method check did not run in this build.</p>';
    }
  }

  function spark(points, key = "rate") {
    const pts = (points || []).filter((p) => p[key] != null).slice(-48);
    if (pts.length < 2) return "";
    const W = 120, H = 26, vals = pts.map((p) => p[key]);
    const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
    const d = pts.map((p, i) => `${i ? "L" : "M"}${(i / (pts.length - 1) * W).toFixed(1)},${(H - 2 - (p[key] - lo) / span * (H - 4)).toFixed(1)}`).join("");
    return `<svg class="spark" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" aria-hidden="true"><path d="${d}"/></svg>`;
  }

  function drawWork(laus) {
    if (!laus) { $("#laus-table").innerHTML = '<p class="sub">Unemployment data not available in this build.</p>'; return; }
    const m = laus.latest_month;
    const [y, mm] = m.split("-").map(Number);
    const prev = `${y - 1}-${String(mm).padStart(2, "0")}`;
    const at = (s, date) => (s || []).find((p) => p.date === date);
    const monthName = new Date(y, mm - 1, 15).toLocaleDateString("en-US", { month: "long", year: "numeric" });
    $("#work-lede").innerHTML = `Monthly unemployment for the cities in either version of the district, ${esc(monthName)}, not seasonally adjusted. `
      + "City rates describe whole cities; the Bureau of Labor Statistics publishes no figures for congressional districts.";
    const tags = (r) => (r.in_plans || []).map((pid) => `<span class="tag ${pid === primary ? "new" : "old"}">${label(pid)}</span>`).join("");
    const row = (name, s, extra = "") => {
      const a = at(s, m), b = at(s, prev);
      const ch = a?.rate != null && b?.rate != null ? a.rate - b.rate : null;
      return [name + extra, a?.rate != null ? pct(a.rate) : "n/a", b?.rate != null ? pct(b.rate) : "n/a",
        ch == null ? "n/a" : `${ch >= 0 ? "+" : "−"}${Math.abs(ch).toFixed(1)} pts`, a?.labor_force != null ? int(a.labor_force) : "", spark(s)];
    };
    const rows = laus.places.filter((p) => p.published).map((p) => row(`${esc(p.name)} ${tags(p)}`, laus.series[p.place]));
    for (const [k, v] of Object.entries(laus.series)) if (k.startsWith("county:")) rows.push(row("<b>Los Angeles County</b>", v));
    rows.push(row("<b>California</b>", laus.series.state), row("<b>United States</b>", laus.series.us));
    $("#laus-table").innerHTML = table(["Area", esc(monthName), "A year earlier", "Change", "Labor force", "Last four years"], rows, [1, 2, 3, 4]);
    const np = laus.places.filter((p) => !p.published).map((p) => esc(p.name));
    $("#laus-note").innerHTML = `Bureau of Labor Statistics, Local Area Unemployment Statistics ${srcLink("bls-laus")}. ${esc(laus.scope_note)}`
      + (np.length ? ` BLS publishes no monthly series for ${np.join(", ")}.` : "")
      + (laus.gap_months?.length ? ` No estimates exist for ${laus.gap_months.join(", ")}. ${Object.values(laus.gap_notes || {}).map(esc).join(" ")}` : "")
      + " The latest month is preliminary.";
  }

  function drawBridge(pj, cams) {
    const p = (pj?.projects || [])[0];
    if (!p) { $("#bridge-lede").textContent = "Bridge data not available in this build."; return; }
    const f = Object.fromEntries(p.facts.map((x) => [x.label, x]));
    const srcs = (id) => srcLink(id);
    // Days closed and days to go, counted from today's date in Los Angeles against Caltrans's dates.
    const today = new Date(new Date().toLocaleString("en-US", { timeZone: "America/Los_Angeles" }));
    const ymd = (v) => { const [y, m, dd] = String(v || "").split("-").map(Number); return y ? new Date(y, m - 1, dd) : null; };
    const closed = ymd(p.dates?.closed), reopen = ymd(p.dates?.expected_reopening);
    if (!closed || !reopen) { $("#bridge-kpis").innerHTML = ""; }
    const day = 86400000;
    const since = Math.max(0, Math.floor((today - closed) / day)), left = Math.max(0, Math.ceil((reopen - today) / day));
    $("#bridge-lede").innerHTML = `${esc(p.summary)}`;
    $("#bridge-kpis").innerHTML = [
      [String(since), "Days closed", `Since ${esc(f["Closed to traffic"]?.value || "")}`],
      [String(left), "Days to expected reopening", esc(f["Expected to reopen"]?.value || "")],
      [esc(f["Vehicles a day"]?.value || ""), "Vehicles a day before the closure", esc(f["Vehicles a day"]?.note || "")],
    ].map(([n, l, s]) => `<div class="stat"><div class="num">${n}</div><div class="lab">${l}</div><div class="moe">${s}</div></div>`).join("");
    $("#bridge-facts").innerHTML = table(["", "", "Source"], p.facts.map((x) => [`<b>${esc(x.label)}</b>`, `${esc(x.value)}${x.note ? `<div class="sub">${esc(x.note)}</div>` : ""}`, srcs(x.source)]));
    $("#bridge-timeline").innerHTML = p.timeline.map((t) => `<li><b>${esc(t.date)}</b> ${esc(t.text)} ${srcs(t.source)}</li>`).join("");
    $("#bridge-links").innerHTML = (p.links || []).map((l) => `<li><a href="${esc(l.url)}">${esc(l.label)}</a></li>`).join("");
    const bc = (cams?.cameras || []).filter((c) => c.route === "SR-47");
    $("#bridge-cams").innerHTML = bc.length ? bc.map((c) => `<li>${esc(c.name)}${c.in_service ? "" : " (out of service)"}: `
      + `${c.image_url ? `<a href="${esc(c.image_url)}">current image</a>` : ""}${c.video_url ? ` · <a href="${esc(c.video_url)}">live video</a>` : ""}</li>`).join("")
      : '<li class="sub">No Route 47 cameras in this build.</li>';
    $("#bridge-note").innerHTML = `Every fact above comes from a Caltrans release or project page, read ${longDate(pj.verified_on)}; schedules can change. `
      + "Day counts are computed on this page from today's date and Caltrans's dates. Caltrans highway camera links "
      + srcLink("caltrans-cctv") + "; the video links are HLS streams, which play in Safari and most video players.";
  }

  function drawAround(cams, airports) {
    const cs = cams?.cameras || [];
    const af = airports?.facilities || [];
    const nA = af.filter((a) => a.type === "Airport").length, nH = af.filter((a) => a.type === "Heliport").length;
    $("#around-lede").innerHTML = `${int(cs.length)} Caltrans highway cameras and ${int(af.length)} FAA-listed landing facilities `
      + `(${nA} airport${nA === 1 ? "" : "s"}, ${nH} heliport${nH === 1 ? "" : "s"}) lie inside either version of the district.`;
    const tags = (r) => (r.in_plans || []).map((pid) => `<span class="tag ${pid === primary ? "new" : "old"}">${label(pid)}</span>`).join("");
    $("#cams-table").innerHTML = table(["Camera", "Route", "Near", "Links", "In"], cs.map((c) => [
      esc(c.name) + (c.in_service ? "" : ' <span class="sub">(out of service)</span>'), esc(c.route || ""), esc(c.nearby || ""),
      `${c.image_url ? `<a href="${esc(c.image_url)}">image</a>` : ""}${c.video_url ? ` · <a href="${esc(c.video_url)}">video</a>` : ""}`, tags(c)]));
    $("#cams-note").innerHTML = cams ? `Caltrans Commercial Wholesale Web Portal ${srcLink("caltrans-cctv")}. ${esc(cams.note)}` : "";
    $("#airports-table").innerHTML = table(["Facility", "Type", "FAA ID", "Ownership and use", "Status", "In"], af.map((a) => [
      esc(a.name), esc(a.type), esc(a.id || ""), `${esc(a.ownership || "")}; ${esc(a.use || "")}`, esc(a.status || ""), tags(a)]));
    $("#airports-note").innerHTML = airports ? `FAA records through the National Transportation Atlas Database ${srcLink("faa-ntad-aviation")}, record date ${esc(airports.faa_record_date || "")}. ${esc(airports.note)}` : "";
  }

  function drawPorts(pd) {
    if (!pd) { $("#ports-kpis").innerHTML = '<p class="sub">Port data not available in this build.</p>'; return; }
    const m = pd.latest_common_month;
    const name = (k) => (k === "pola" ? "Port of Los Angeles" : "Port of Long Beach");
    const mon = m ? new Date(+m.slice(0, 4), +m.slice(5) - 1, 15).toLocaleDateString("en-US", { month: "long", year: "numeric" }) : "";
    const last = (k) => (pd[k].months || []).find((x) => x.month === m);
    const ds = pd.dock_summary || {};
    const inNew = (k) => ds[k]?.[`in_${primary}`] ?? 0;
    const where = (k) => (!ds[k] ? "" : inNew(k) === ds[k].docks ? `all ${int(ds[k].docks)} of the ${name(k)}'s listed docks lie inside the new lines`
      : inNew(k) === 0 ? `none of the ${name(k)}'s ${int(ds[k].docks)} listed docks do`
      : `${int(inNew(k))} of the ${name(k)}'s ${int(ds[k].docks)} listed docks lie inside the new lines`);
    $("#ports-lede").innerHTML = `The two ports share San Pedro Bay, but only one is in CA-44: ${where("pola")}, and ${where("polb")}. `
      + `Both are shown because they work as one harbor. Container counts are the ports' own monthly reports, through ${esc(mon)}.`;
    const yt = (k) => pd.ytd?.[k] || {};
    const chg = (k) => (yt(k).this_year && yt(k).last_year ? 100 * (yt(k).this_year / yt(k).last_year - 1) : null);
    const kpi = (k) => `<div class="stat"><div class="num">${int(last(k)?.total)}</div><div class="lab">TEUs at the ${name(k)}, ${esc(mon)}</div>`
      + `<div class="moe">Year to date ${int(yt(k).this_year)}${chg(k) == null ? "" : ` (${chg(k) >= 0 ? "+" : "−"}${Math.abs(chg(k)).toFixed(1)}% from a year earlier)`}</div></div>`;
    const both = (last("pola")?.total || 0) + (last("polb")?.total || 0);
    $("#ports-kpis").innerHTML = kpi("pola") + kpi("polb") + `<div class="stat"><div class="num">${int(both)}</div><div class="lab">TEUs at both ports, ${esc(mon)}</div><div class="moe">A TEU is one twenty-foot container or its equivalent</div></div>`;
    const months = [...new Set([...(pd.pola.months || []), ...(pd.polb.months || [])].map((x) => x.month))].sort().reverse().slice(0, 12);
    const get = (k, mo) => (pd[k].months || []).find((x) => x.month === mo);
    $("#teu-months").innerHTML = table(["Month", "Los Angeles", "Long Beach", "Both"], months.map((mo) => {
      const a = get("pola", mo)?.total, b = get("polb", mo)?.total;
      return [new Date(+mo.slice(0, 4), +mo.slice(5) - 1, 15).toLocaleDateString("en-US", { month: "short", year: "numeric" }), int(a), int(b), a != null && b != null ? int(a + b) : "n/a"];
    }), [1, 2, 3]);
    $("#teu-note").innerHTML = `Port of Los Angeles container statistics ${srcLink("pola-teu")}; Port of Long Beach container trade ${srcLink("polb-teu")}, whose latest figures the port calls preliminary. Includes loaded and empty containers.`
      + (pd.polb.note ? ` ${esc(pd.polb.note)}` : "");
    $("#docks-table").innerHTML = table(["Port", "Docks listed", "In new lines", "In 2021 lines", "In neither"],
      ["pola", "polb"].filter((k) => ds[k]).map((k) => [name(k), int(ds[k].docks), int(ds[k][`in_${primary}`]), int(ds[k][`in_${other}`]), int(ds[k].outside_all)]), [1, 2, 3, 4]);
    $("#docks-note").innerHTML = `U.S. Army Corps of Engineers navigation facility records ${srcLink("usace-docks")}. ${esc(pd.dock_note)}`;
    $("#pola-years").innerHTML = table(["Calendar year", "TEUs"], (pd.pola.years || []).slice().reverse().map((y) => [y.year + (y.year === +m?.slice(0, 4) ? " (to date)" : ""), int(y.calendar_year_total)]), [1]);
  }

  function drawSeat(leg, ele, votes, fec) {
    const cur = leg?.current;
    $("#seat-lede").innerHTML = cur ? `${esc(cur.name)} (${esc(cur.party)}) holds the seat; the current term ends ${longDate(cur.end)}. `
      + "Results below are for the district numbered 44 from 2012 on; before 2012 that number belonged to a district in Riverside County." : "";
    const res = (ele?.results || []).slice().reverse();
    $("#elections").innerHTML = table(["Year", "Winner", "Share", "Runner-up", "Share"], res.map((r) => {
      const [a, b] = r.candidates;
      return [`${r.year}${r.new_lines ? ' <span class="tag" title="First election on newly drawn lines">redrawn</span>' : ""}`, a ? `${esc(a.name)} (${esc(a.party || "")})` : "", a ? pct(a.pct) : "",
        b ? `${esc(b.name)} (${esc(b.party || "")})` : "—", b ? pct(b.pct) : ""];
    }), [2, 4]);
    $("#elections-note").innerHTML = `Certified general election results ${srcLink("medsl-house")} ${srcLink("fec-results")}. The Nov. 3, 2026 election, the first on the new lines, is not shown until results are certified and published in these sources.`;
    if (votes) {
      $("#votes").innerHTML = `<div class="kpis"><div><b>${pct(votes.missed_pct)}</b><span>Yes-or-no roll calls missed, ${votes.congress}th Congress (all House members on the same roll calls: ${pct(votes.house_missed_pct)})</span></div>`
        + `<div><b>${pct(votes.with_party_majority_pct)}</b><span>Votes with the majority of the member's party</span></div>`
        + `<div><b>${int(votes.votes_cast)}</b><span>Yes or no votes cast</span></div><div><b>${int(votes.period?.roll_calls_parsed)}</b><span>Roll calls read, ${votes.period?.from_year}–${votes.period?.to_year}</span></div></div>`
        + `<p class="fine">Clerk of the House roll calls ${srcLink("clerk-votes")}, through ${longDate(votes.period?.through)}. ${esc(votes.definitions?.not_voting || "")}</p>`;
    } else $("#votes").innerHTML = '<p class="sub">Roll calls not available in this build.</p>';
    const cycles = Object.keys(fec?.cycles || {}).sort().reverse();
    $("#fec").innerHTML = table(["Cycle", "Candidate", "Party", "Raised", "Spent", "Cash on hand"],
      cycles.flatMap((c) => fec.cycles[c].slice(0, 4).map((x) => [c, `<a href="${esc(x.url)}">${esc(x.name)}</a>`, esc(x.party || ""), usd(x.receipts), usd(x.disbursements), usd(x.cash_on_hand)])), [3, 4, 5]);
    $("#fec-note").innerHTML = `Federal Election Commission candidate totals for California's 44th District, by two-year cycle ${srcLink("fec")}. The 2026 cycle was run on the new lines.`;
  }

  function drawMoney(usa, irs) {
    $("#usaspending").innerHTML = table(["Fiscal year", "Total", "Grants", "Contracts", "Direct payments"],
      (usa?.years || []).slice().reverse().map((y) => [`FY${y.fy}`, usd(y.total), usd(y.grants), usd(y.contracts), usd(y.direct)]), [1, 2, 3, 4]);
    $("#usa-note").innerHTML = usa ? `USAspending.gov obligations by place of performance in CA-44 as USAspending draws it ${srcLink("usaspending")}, as of ${longDate(usa.as_of)}. Payments reported only at county or state level are not included.` : "";
    $("#agencies").innerHTML = table(["Agency", `FY${usa?.last_complete_fy ?? ""}`], (usa?.top_agencies || []).map((a) => [esc(a.name), usd(a.amount)]), [1]);
    const dI = irs?.district, sI = irs?.state;
    $("#irs").innerHTML = dI ? table(["", "CA-44", "California"], [
      ["Returns filed", int(dI.returns), int(sI?.returns)],
      ["Adjusted gross income per return", usd(dI.agi_per_return), usd(sI?.agi_per_return)],
      ["Total tax liability", usd(dI.total_tax_liability), usd(sI?.total_tax_liability)],
      ["Tax as a share of income", pct(dI.tax_share_of_agi_pct), pct(sI?.tax_share_of_agi_pct)],
    ], [1, 2]) : '<p class="sub">Not available in this build.</p>';
    $("#irs-note").innerHTML = irs ? `IRS Statistics of Income, individual returns by congressional district, tax year ${irs.tax_year} ${srcLink("irs-soi-cd")}. 2021 lines.` : "";
  }

  function drawInstitutions(col, bc, P) {
    const tags = (r) => (r.in_plans || []).map((pid) => `<span class="tag ${pid === primary ? "new" : "old"}">${label(pid)}</span>`).join("");
    $("#colleges").innerHTML = table(["Institution", "City", "Type", "In"], (col?.institutions || []).map((c) =>
      [c.website ? `<a href="${esc(c.website)}">${esc(c.name)}</a>` : esc(c.name), esc(c.city || ""), esc([c.control, c.level].filter(Boolean).join(", ")), tags(c)]));
    $("#colleges-note").innerHTML = col ? `NCES IPEDS directory, HD${col.directory_year} ${srcLink("nces-ipeds-hd")}. ${esc(col.coverage_note)}` : "";
    $("#stations").innerHTML = table(["Station", "Band", "Licensed to", "In"], (bc?.stations || []).map((s) =>
      [esc(s.call), `${esc(s.band)} ${s.frequency ? esc(s.frequency) : s.channel ? `ch. ${esc(s.channel)}` : ""}`, esc(s.city), tags(s)]));
    $("#stations-note").innerHTML = bc ? `FCC licensing records ${srcLink("fcc-queries")}. ${esc(bc.rule)}` : "";
  }

  function drawChecks(integ) {
    const list = integ?.checks || [];
    const sum = integ?.summary || {};
    $("#checks-lede").innerHTML = list.length ? `${sum.pass || 0} of ${sum.total} checks pass in this build${sum.fail ? `, ${sum.fail} fail` : ""}${sum.warn ? `, ${sum.warn} need a look` : ""}${sum.skip ? `, ${sum.skip} did not run` : ""}.` : "";
    const icon = { pass: "✓", warn: "!", fail: "×", skip: "–" };
    $("#checks-list").innerHTML = list.map((c) => `<li class="${esc(c.status)}"><span class="icon">${icon[c.status] || "?"}</span><div><div class="ct">${esc(c.title)}</div><div class="cd">${esc(c.detail)}</div></div></li>`).join("");
  }

  function drawSources(list) {
    $("#sources-list").innerHTML = list.map((s) => `<li id="src-${esc(s.id)}">${esc(s.apa || s.title)}${s.notes ? ` <span class="sub">${esc(s.notes)}</span>` : ""}${s.query ? `<span class="q">${esc(s.query)}</span>` : ""}</li>`).join("");
  }
}

main();
