const $ = (id) => document.getElementById(id);
chrome.storage.local.get({ server: "http://localhost:8000", token: "" }).then((s) => { $("server").value = s.server; $("token").value = s.token; });
$("save").onclick = async () => {
  const server = $("server").value.trim().replace(/\/$/, "") || "http://localhost:8000";
  const token = $("token").value.trim();
  if (!/^https?:\/\//.test(server)) { $("msg").textContent = "Server URL must start with http:// or https://"; return; }
  if (!/^cvx_/.test(token)) { $("msg").textContent = "Tokens start with cvx_"; return; }
  if (!/^http:\/\/(localhost|127\.0\.0\.1):8000$/.test(server)) {
    const ok = await chrome.permissions.request({ origins: [server + "/*"] });
    if (!ok) { $("msg").textContent = "Permission to reach that server was declined."; return; }
  }
  await chrome.storage.local.set({ server, token });
  $("msg").textContent = "Saved.";
};
