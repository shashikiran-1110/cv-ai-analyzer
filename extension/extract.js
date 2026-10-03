// Runs in the page the user is viewing (injected on click only). Reads schema.org JobPosting JSON-LD when present,
// else falls back to the visible title and main text. Nothing leaves the browser until the user presses "Score".
function cvmExtractJob() {
  const clean = (h) => { const d = document.createElement("div"); d.innerHTML = h || ""; return (d.innerText || d.textContent || "").trim(); };
  const flat = (x) => (Array.isArray(x) ? x.flatMap(flat) : x && x["@graph"] ? flat(x["@graph"]) : [x]);
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    let data; try { data = JSON.parse(s.textContent || ""); } catch { continue; }
    const job = flat(data).find((o) => o && (o["@type"] === "JobPosting" || (Array.isArray(o["@type"]) && o["@type"].includes("JobPosting"))));
    if (job) {
      const loc = flat(job.jobLocation || []).map((l) => (l && l.address ? [l.address.addressLocality, l.address.addressCountry].filter(Boolean).join(", ") : "")).filter(Boolean)[0] || "";
      return { title: String(job.title || "").trim(), company: (job.hiringOrganization && job.hiringOrganization.name) || "",
               location: loc || (job.jobLocationType === "TELECOMMUTE" ? "Remote" : ""), url: location.href,
               description: clean(job.description).slice(0, 40000), method: "jobposting" };
    }
  }
  const sel = String(window.getSelection() || "").trim();
  const main = document.querySelector("main, [role=main], article") || document.body;
  return { title: (document.querySelector("h1") || {}).innerText || document.title, company: "", location: "", url: location.href,
           description: (sel.length > 200 ? sel : main.innerText || "").slice(0, 40000), method: sel.length > 200 ? "selection" : "page-text" };
}
