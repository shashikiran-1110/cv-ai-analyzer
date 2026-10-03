const out = document.getElementById("out");
const h = (tag, attrs = {}, ...kids) => { const e = document.createElement(tag); Object.assign(e, attrs); kids.forEach((k) => e.append(k)); return e; };

async function settings() { return chrome.storage.local.get({ server: "http://localhost:8000", token: "" }); }

async function call(path, body) {
  const { server, token } = await settings();
  const r = await fetch(server.replace(/\/$/, "") + path, { method: "POST", headers: { "Content-Type": "application/json", "X-Ext-Token": token }, body: JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
  return data;
}

function show(job, s) {
  out.replaceChildren();
  const tone = s.score >= 60 ? "hi" : s.score >= 40 ? "mid" : "lo";
  out.append(h("div", {}, h("div", { className: `score ${tone}`, textContent: `${s.score}%` }), h("div", { textContent: job.title }),
                h("small", { className: "muted", textContent: [job.company, job.location].filter(Boolean).join(" · ") })));
  if (s.missing_required.length) out.append(h("div", {}, h("small", { className: "muted", textContent: "Required skills you don't show:" }),
    h("div", { className: "chips" }, ...s.missing_required.map((m) => h("span", { className: "chip", textContent: m })))));
  if (s.gates.length) out.append(h("ul", {}, ...s.gates.map((g) => h("li", { className: `gate ${g.status}`, textContent: `${g.label}: ${g.status} – ${g.reason}` }))));
  const save = h("button", { textContent: "☆ Save to tracker" });
  save.onclick = async () => {
    save.disabled = true;
    try { await call("/api/ext/save", { ...job, score: s.score }); save.textContent = "✓ Saved"; }
    catch (e) { save.textContent = "Save failed: " + e.message; }
  };
  out.append(save, h("small", { className: "muted", textContent: `Read via ${job.method}; scored against your latest resume.` }));
}

(async () => {
  const { token } = await settings();
  if (!token) { out.replaceChildren(h("p", { textContent: "Add your extension token first: in the app open Settings → Browser extension → Create token, then paste it in this extension's settings." })); return; }
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  let job;
  try {
    const [{ result }] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["extract.js"] })
      .then(() => chrome.scripting.executeScript({ target: { tabId: tab.id }, func: () => cvmExtractJob() }));
    job = result;
  } catch (e) { out.replaceChildren(h("p", { className: "err", textContent: "Can't read this page: " + e.message })); return; }
  if (!job || (job.description || "").length < 50) { out.replaceChildren(h("p", { textContent: "No job posting found on this page. Select the posting text and try again." })); return; }
  const go = h("button", { textContent: `Score “${(job.title || "this job").slice(0, 40)}”` });
  out.replaceChildren(h("small", { className: "muted", textContent: "Only this posting's text is sent to your CV Match server." }), go);
  go.onclick = async () => {
    go.disabled = true; go.textContent = "Scoring…";
    try { show(job, await call("/api/ext/score", job)); }
    catch (e) { out.append(h("p", { className: "err", textContent: e.message })); go.disabled = false; go.textContent = "Try again"; }
  };
})();
