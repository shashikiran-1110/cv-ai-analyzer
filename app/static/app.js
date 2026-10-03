"use strict";
const $ = (id) => document.getElementById(id);
const state = { cfg: {}, searchId: null, jobs: [], selected: new Set(), file: null, report: null, timeRange: "week", step: 1 };

// Safe DOM builder: text is always set via textContent/createTextNode, never innerHTML.
function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "style") e.style.cssText = v;
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) e.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return e;
}
const clear = (el) => { el.replaceChildren(); return el; };
const show = (el, on = true) => { el.hidden = !on; };

function goto(step) {
  state.step = step;
  for (let i = 1; i <= 4; i++) show($("step" + i), i === step);
  document.querySelectorAll("#stepper li").forEach((li) => {
    const n = +li.dataset.step;
    li.classList.toggle("active", n === step);
    li.classList.toggle("done", n < step);
    if (n === step) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}
document.querySelectorAll("[data-goto]").forEach((b) => b.addEventListener("click", () => goto(+b.dataset.goto)));

async function api(url, opts) {
  let res;
  try { res = await fetch(url, opts); } catch { throw new Error("Can't reach the server. Is it still running?"); }
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON error body */ }
  if (!res.ok) {
    let msg = body && body.detail;
    if (Array.isArray(msg)) msg = msg.map((d) => (d.loc ? d.loc.slice(-1)[0] + ": " : "") + d.msg).join("; ");
    throw new Error(msg || `Request failed (${res.status}).`);
  }
  return body;
}

/* ---------- Step 1: search ---------- */
const countEl = $("count"), rangeEl = $("countRange");
rangeEl.addEventListener("input", () => (countEl.value = rangeEl.value));
countEl.addEventListener("input", () => { if (countEl.value) rangeEl.value = Math.min(100, Math.max(5, countEl.value)); });
$("timeSeg").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-v]"); if (!b) return;
  state.timeRange = b.dataset.v;
  $("timeSeg").querySelectorAll("button").forEach((x) => x.setAttribute("aria-checked", x === b));
  show($("customRow"), state.timeRange === "custom");
});

$("searchForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = $("searchError"); show(err, false);
  const title = $("title").value.trim();
  const count = Math.round(+countEl.value);
  if (title.length < 2) return fail(err, "Enter a job title (at least 2 characters).", $("title"));
  if (!(count >= 1 && count <= (state.cfg.max_jobs || 100))) return fail(err, `Number of posts must be between 1 and ${state.cfg.max_jobs || 100}.`, countEl);
  const body = { title, location: $("location").value.trim(), count, time_range: state.timeRange };
  if (state.timeRange === "custom") {
    body.custom_hours = Math.round(+$("customHours").value);
    if (!(body.custom_hours >= 1 && body.custom_hours <= 2160)) return fail(err, "Custom hours must be between 1 and 2160.", $("customHours"));
  }
  $("searchBtn").disabled = true;
  setProgress("Starting search…", 0);
  show($("progress"));
  try {
    const { search_id } = await api("/api/search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    state.searchId = search_id;
    const res = await pollSearch(search_id);
    state.jobs = res.jobs;
    state.selected = new Set(res.jobs.map((j) => j.id));
    renderJobs(res);
    goto(2);
  } catch (ex) {
    fail(err, ex.message);
  } finally {
    $("searchBtn").disabled = false;
    show($("progress"), false);
  }
});

function fail(el, msg, focus) { el.textContent = msg; show(el); if (focus) focus.focus(); }
function setProgress(text, pct) { $("progressText").textContent = text; $("progressPct").textContent = pct + "%"; $("progressBar").style.width = pct + "%"; }

async function pollSearch(id) {
  let misses = 0;
  for (;;) {
    await new Promise((r) => setTimeout(r, 900));
    let s;
    try { s = await api("/api/search/" + id); misses = 0; }
    catch (ex) { if (++misses >= 5) throw ex; continue; }
    if (s.status === "error") throw new Error(s.error || "Search failed.");
    if (s.status === "done") {
      if (!s.jobs.length) throw new Error("LinkedIn returned no jobs for that search. Try a broader title, another location, or a longer time range.");
      return s;
    }
    const total = Math.max(1, s.total);
    if (s.stage === "details") setProgress(`Reading job descriptions (${s.done}/${total})…`, 30 + Math.round((s.done / total) * 70));
    else setProgress(`Searching LinkedIn… found ${s.done} of ${total}`, Math.round((s.done / total) * 30));
  }
}

/* ---------- Step 2: job list ---------- */
const RANGE_LABEL = { "24h": "past 24 hours", week: "past week", month: "past month", any: "any time", custom: "custom range" };
function renderJobs(res) {
  const q = res.query;
  $("jobsMeta").textContent = `${state.jobs.length} postings for “${q.title}”${q.location ? " in " + q.location : ""} · ${RANGE_LABEL[q.time_range] || ""}`;
  $("selAll").checked = true;
  $("jobFilter").value = "";
  drawJobList();
}
function drawJobList() {
  const f = $("jobFilter").value.trim().toLowerCase();
  const list = clear($("jobList"));
  const rows = state.jobs.filter((j) => !f || (j.title + " " + j.company).toLowerCase().includes(f));
  if (!rows.length) list.append(h("li", { class: "empty" }, "No jobs match that filter."));
  for (const j of rows) {
    const cb = h("input", { type: "checkbox", id: "j" + j.id, "aria-label": `Include ${j.title} at ${j.company}` });
    cb.checked = state.selected.has(j.id);
    cb.addEventListener("change", () => { cb.checked ? state.selected.add(j.id) : state.selected.delete(j.id); updateSel(); });
    list.append(h("li", {},
      cb,
      h("div", { class: "job-main" },
        h("div", { class: "job-title" },
          h("a", { href: safeUrl(j.url), target: "_blank", rel: "noopener noreferrer" }, j.title),
          j.description_missing ? h("span", { class: "pill", title: "No description could be loaded; match will be a rough estimate" }, "no description") : null),
        h("div", { class: "job-sub" }, [j.company, j.location, j.posted].filter(Boolean).join(" · ")))));
  }
  updateSel();
}
function updateSel() {
  $("selCount").textContent = state.selected.size;
  $("toResume").disabled = state.selected.size === 0;
  $("selAll").checked = state.selected.size === state.jobs.length;
  $("selAll").indeterminate = state.selected.size > 0 && state.selected.size < state.jobs.length;
}
function safeUrl(u) { try { const x = new URL(u); return /^https?:$/.test(x.protocol) ? x.href : "#"; } catch { return "#"; } }
$("selAll").addEventListener("change", (e) => { state.selected = new Set(e.target.checked ? state.jobs.map((j) => j.id) : []); drawJobList(); });
$("jobFilter").addEventListener("input", drawJobList);
$("toResume").addEventListener("click", () => goto(3));

/* ---------- Step 3: resume ---------- */
const drop = $("drop"), fileEl = $("file");
function setFile(f) {
  const err = $("analyzeError"); show(err, false);
  state.file = null; drop.classList.remove("has");
  $("dropText").replaceChildren(h("b", {}, "Drop your PDF here"), " or click to browse");
  if (f) {
    if (!(f.type === "application/pdf" || /\.pdf$/i.test(f.name))) fail(err, "Please choose a PDF file.");
    else if (f.size > 10 * 1024 * 1024) fail(err, "That PDF is larger than 10 MB.");
    else if (f.size === 0) fail(err, "That file is empty.");
    else {
      state.file = f; drop.classList.add("has");
      $("dropText").replaceChildren(h("b", {}, f.name), ` · ${(f.size / 1024).toFixed(0)} KB · click to replace`);
    }
  }
  $("analyzeBtn").disabled = !state.file;
}
fileEl.addEventListener("change", () => setFile(fileEl.files[0]));
drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileEl.click(); } });
["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => setFile(e.dataTransfer.files[0]));
$("threshold").addEventListener("input", (e) => { $("thrVal").textContent = e.target.value; $("threshold2").value = e.target.value; });

$("analyzeBtn").addEventListener("click", async () => {
  const err = $("analyzeError"); show(err, false);
  const btn = $("analyzeBtn"); btn.disabled = true; btn.textContent = "Analyzing…";
  const fd = new FormData();
  fd.append("search_id", state.searchId);
  fd.append("resume", state.file);
  fd.append("threshold", $("threshold").value);
  fd.append("use_ai", state.cfg.ai_available && $("useAi").checked ? "true" : "false");
  fd.append("job_ids", JSON.stringify([...state.selected]));
  try {
    state.report = await api("/api/analyze", { method: "POST", body: fd });
    renderReport();
    goto(4);
  } catch (ex) {
    fail(err, ex.message);
  } finally {
    btn.disabled = !state.file; btn.textContent = "Analyze match";
  }
});

/* ---------- Step 4: report ---------- */
const scoreClass = (s, t) => (s >= t ? "hi" : s >= t - 20 ? "mid" : "lo");

function renderReport() {
  const r = state.report, s = r.summary, ins = r.insights;
  $("reportMeta").textContent = `${s.job_count} postings for “${r.query.title}”${r.query.location ? " in " + r.query.location : ""}`;
  $("threshold2").value = s.threshold; $("thrVal2").textContent = s.threshold;
  $("avgScore").textContent = s.avg_score;
  $("bestScore").textContent = r.jobs.length ? r.jobs[0].score : 0;
  $("yrs").textContent = s.resume_years ? s.resume_years : "?";
  $("qualTotal").textContent = s.job_count;

  show($("aiNotice"), !!ins.ai_error);
  $("aiNotice").textContent = ins.ai_error || "";
  const sum = $("summaryBox");
  show(sum, !!ins.summary);
  sum.replaceChildren(h("b", {}, "Overall: "), ins.summary || "", ins.source === "claude" ? h("div", { class: "fine" }, "Advice written by Claude from your resume and the posting analysis.") : null);

  const bullets = (el, items, empty) => { clear(el); (items.length ? items : [empty]).forEach((t) => el.append(h("li", {}, t))); };
  bullets($("strengths"), ins.strengths, "Nothing stands out yet.");
  bullets($("improvements"), ins.improvements, "No major issues detected.");

  const learn = clear($("learn"));
  if (!ins.skills_to_learn.length) learn.append(h("div", { class: "empty" }, "No recurring skill gaps found. Nice."));
  const maxJobs = Math.max(1, ...ins.skills_to_learn.map((x) => x.jobs || 0));
  ins.skills_to_learn.forEach((x, i) => learn.append(h("div", { class: "learn-item" },
    h("div", { class: "learn-head" }, h("span", {}, `${i + 1}. ${x.skill}`), x.jobs != null ? h("small", {}, `${x.jobs} of ${s.job_count} postings`) : null),
    x.jobs != null ? h("div", { class: "meter", "aria-hidden": "true" }, h("i", { style: `width:${Math.round((x.jobs / maxJobs) * 100)}%` })) : null,
    x.why ? h("p", {}, x.why) : null,
    x.how ? h("p", {}, h("b", {}, "How: "), x.how) : null)));

  const total = Math.max(1, ...s.distribution);
  const labels = ["0–19", "20–39", "40–59", "60–79", "80+"];
  clear($("dist")).append(...s.distribution.map((n, i) => h("div", {}, h("b", {}, n), h("i", { style: `height:${Math.max(3, Math.round((n / total) * 70))}px` }), labels[i])));

  updateThreshold();
  drawResults();
}

function updateThreshold() {
  const r = state.report, t = +$("threshold2").value;
  const q = r.jobs.filter((j) => j.score >= t).length, n = r.jobs.length;
  $("thrVal2").textContent = t;
  $("qualCount").textContent = q;
  const pct = n ? Math.round((q / n) * 100) : 0, C = 2 * Math.PI * 54;
  clear($("gauge")).append(
    h("div", { class: "g-label" }, pct + "%"));
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 130 130");
  for (const [cls, off] of [["g-track", 0], ["g-fill", C * (1 - pct / 100)]]) {
    const c = document.createElementNS(svg.namespaceURI, "circle");
    Object.entries({ cx: 65, cy: 65, r: 54, fill: "none", "stroke-width": 12, class: cls, "stroke-linecap": "round", "stroke-dasharray": C, "stroke-dashoffset": off }).forEach(([k, v]) => c.setAttribute(k, v));
    svg.append(c);
  }
  $("gauge").prepend(svg);
  $("gauge").setAttribute("aria-label", `You qualify for ${q} of ${n} jobs (${pct}%)`);
}
$("threshold2").addEventListener("input", () => { updateThreshold(); drawResults(); });
$("onlyQual").addEventListener("change", drawResults);
$("sortBy").addEventListener("change", drawResults);

function drawResults() {
  const t = +$("threshold2").value;
  let rows = [...state.report.jobs];
  if ($("onlyQual").checked) rows = rows.filter((j) => j.score >= t);
  const sort = $("sortBy").value;
  rows.sort(sort === "score-asc" ? (a, b) => a.score - b.score : sort === "company" ? (a, b) => a.company.localeCompare(b.company) : (a, b) => b.score - a.score);
  const ul = clear($("results"));
  if (!rows.length) ul.append(h("li", { class: "empty" }, "No jobs at this threshold."));
  for (const j of rows) {
    const q = j.score >= t;
    const body = h("div", { class: "r-body", hidden: true },
      ...[["Skills", j.components.skills], ["Role fit", j.components.role], ["Experience", j.components.experience]].map(([k, v]) =>
        h("div", { class: "comp" }, h("span", {}, k), h("div", { class: "meter" }, h("i", { style: `width:${v}%` })), h("span", {}, v + "%"))),
      chipBlock("You have", j.matched_skills.concat(j.matched_keywords || []), "ok"),
      chipBlock("Required, missing", j.required_missing, "miss"),
      chipBlock("Preferred, missing", j.missing_skills.filter((s) => !j.required_missing.includes(s)), "pref"),
      chipBlock("Posting keywords you lack", j.missing_keywords || [], "miss"),
      j.required_years != null ? h("div", { class: "job-sub" }, `Experience asked: ${j.required_years}+ years${j.required_years_inferred ? " (inferred from title)" : ""}`) : null,
      j.confidence === "low" ? h("div", { class: "alert info" }, "Little or no description text was available, so this score is a rough estimate.") : null,
      h("a", { href: safeUrl(j.url), target: "_blank", rel: "noopener noreferrer" }, "View on LinkedIn ↗"));
    const head = h("button", { class: "r-head", "aria-expanded": "false", type: "button" },
      h("span", { class: "score " + scoreClass(j.score, t) }, j.score + "%"),
      h("span", {}, h("div", { class: "job-title" }, j.title, h("span", { class: "tag " + (q ? "q" : "nq") }, q ? "Qualified" : "Below")),
        h("div", { class: "job-sub" }, [j.company, j.location].filter(Boolean).join(" · "))),
      h("span", { class: "chev", "aria-hidden": "true" }, "›"));
    const li = h("li", {}, head, body);
    head.addEventListener("click", () => {
      const open = body.hidden; body.hidden = !open; li.classList.toggle("open", open); head.setAttribute("aria-expanded", open);
    });
    ul.append(li);
  }
}
function chipBlock(label, items, cls) {
  if (!items || !items.length) return null;
  return h("div", {}, h("h4", {}, label), h("div", { class: "chips" }, items.map((s) => h("span", { class: "chip " + cls }, s))));
}

$("exportCsv").addEventListener("click", () => {
  const t = +$("threshold2").value;
  const esc = (v) => { v = String(v ?? ""); if (/^[=+\-@]/.test(v)) v = "'" + v; return `"${v.replace(/"/g, '""')}"`; };
  const rows = [["Title", "Company", "Location", "Match %", "Qualified", "Missing required skills", "Missing preferred skills", "URL"]];
  state.report.jobs.forEach((j) => rows.push([j.title, j.company, j.location, j.score, j.score >= t ? "yes" : "no", j.required_missing.join("; "),
    j.missing_skills.filter((s) => !j.required_missing.includes(s)).join("; "), j.url]));
  const blob = new Blob([rows.map((r) => r.map(esc).join(",")).join("\n")], { type: "text/csv" });
  const a = h("a", { href: URL.createObjectURL(blob), download: "cv-match-report.csv" });
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});

/* ---------- init ---------- */
(async function init() {
  try {
    state.cfg = await api("/api/config");
    show($("aiRow"), !!state.cfg.ai_available);
    if (state.cfg.default_threshold) { $("threshold").value = state.cfg.default_threshold; $("thrVal").textContent = state.cfg.default_threshold; }
  } catch { /* UI still works; server errors surface on use */ }
  goto(1);
})();
