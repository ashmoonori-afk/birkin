/* Birkin Web UI — SpaceX dark theme, SSE streaming, agentic flow, settings */

const $ = (id) => document.getElementById(id);
const chat = $("chat");
const form = $("input-form");
const input = $("user-input");
const sendBtn = $("send-btn");
const welcome = $("welcome");
const sidebar = $("sidebar");
const sidebarToggle = $("sidebar-toggle");
const sidebarOverlay = $("sidebar-overlay");
const newChatBtn = $("new-chat-btn");
const sessionList = $("session-list");
const helpPanel = $("help-panel");
const helpToggle = $("help-toggle");
const helpClose = $("help-close");
const helpOverlay = $("help-overlay");
const welcomeHelp = $("welcome-help");
const settingsPanel = $("settings-panel");
const settingsToggle = $("settings-toggle");
const settingsClose = $("settings-close");
const settingsOverlay = $("settings-overlay");
const settingsContent = $("settings-content");
const providerBadge = $("provider-badge");

let sessionId = null;
let currentConfig = {};
let providersCache = null;

/* ── Markdown Parser ── */

function esc(s) {
  return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

function md(text) {
  const lines = text.split("\n"), html = [];
  let inCode = false, codeBuf = [], inList = false, lt = "";
  const closeList = () => { if (inList) { html.push(lt === "ol" ? "</ol>" : "</ul>"); inList = false; lt = ""; } };
  const inl = (l) => l
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/__([^_]+)__/g, "<strong>$1</strong>")
    .replace(/_([^_]+)_/g, "<em>$1</em>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

  for (const raw of lines) {
    if (raw.trimStart().startsWith("```")) {
      if (inCode) { html.push("<pre><code>" + esc(codeBuf.join("\n")) + "</code></pre>"); codeBuf = []; inCode = false; }
      else { closeList(); inCode = true; }
      continue;
    }
    if (inCode) { codeBuf.push(raw); continue; }
    const t = raw.trim();
    if (!t) { closeList(); continue; }
    const hm = t.match(/^(#{1,4})\s+(.+)$/);
    if (hm) { closeList(); html.push(`<h${hm[1].length}>${inl(esc(hm[2]))}</h${hm[1].length}>`); continue; }
    if (/^[-*+]\s+/.test(t)) { if (!inList || lt !== "ul") { closeList(); html.push("<ul>"); inList = true; lt = "ul"; } html.push(`<li>${inl(esc(t.replace(/^[-*+]\s+/,"")))}</li>`); continue; }
    if (/^\d+\.\s+/.test(t)) { if (!inList || lt !== "ol") { closeList(); html.push("<ol>"); inList = true; lt = "ol"; } html.push(`<li>${inl(esc(t.replace(/^\d+\.\s+/,"")))}</li>`); continue; }
    closeList();
    html.push(`<p>${inl(esc(t))}</p>`);
  }
  if (inCode) html.push("<pre><code>" + esc(codeBuf.join("\n")) + "</code></pre>");
  closeList();
  return html.join("\n");
}

/* ── Chat Helpers ── */

function addBubble(role, text) {
  if (welcome && welcome.parentNode) welcome.remove();
  const el = document.createElement("div");
  el.className = `bubble ${role}`;
  if (role === "assistant") {
    el.innerHTML = md(text || "");
  } else {
    el.textContent = text;
  }
  chat.appendChild(el);
  requestAnimationFrame(() => { chat.scrollTop = chat.scrollHeight; });
  return el;
}

function createStreamBubble() {
  if (welcome && welcome.parentNode) welcome.remove();
  const el = document.createElement("div");
  el.className = "bubble assistant streaming";
  el.dataset.streaming = "1";
  el.innerHTML = '<span class="cursor">|</span>';
  chat.appendChild(el);
  requestAnimationFrame(() => { chat.scrollTop = chat.scrollHeight; });
  return el;
}

function finalizeStreamBubble(bubble, text) {
  if (!bubble) return;
  bubble.classList.remove("streaming");
  delete bubble.dataset.streaming;
  bubble.innerHTML = md(text || "");
  requestAnimationFrame(() => { chat.scrollTop = chat.scrollHeight; });
}

function showThinking() {
  const el = document.createElement("div");
  el.className = "thinking"; el.id = "thinking";
  el.setAttribute("role", "status");
  el.innerHTML = "<span></span><span></span><span></span>";
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
}
function hideThinking() { const el = $("thinking"); if (el) el.remove(); }
function setLoading(on) { sendBtn.disabled = on; input.disabled = on; }

/* ── Agentic Flow Rendering ── */

function createThinkingIndicator() {
  const el = document.createElement("div");
  el.className = "thinking-indicator";
  el.id = "agent-thinking";
  el.textContent = t("reasoning");
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
  return el;
}
function removeThinkingIndicator() { const el = $("agent-thinking"); if (el) el.remove(); }

function createToolCallBlock(name, inputData) {
  if (welcome && welcome.parentNode) welcome.remove();
  const el = document.createElement("div");
  el.className = "tool-call";
  el.innerHTML = `
    <div class="tool-call-label">${t("using_tool")}</div>
    <div class="tool-call-name">${esc(name)}</div>
    <details><summary>${t("tool_input")}</summary><pre>${esc(JSON.stringify(inputData, null, 2))}</pre></details>
  `;
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
  return el;
}

function appendToolResult(parentEl, name, output, isError) {
  const el = document.createElement("div");
  el.className = "tool-result" + (isError ? " error" : "");
  el.innerHTML = `
    <div class="tool-result-label">${isError ? t("tool_error") : t("tool_result")}</div>
    <details><summary>${esc(name)}</summary><pre>${esc(output)}</pre></details>
  `;
  parentEl.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
}

/* ── @memory search command ── */

async function handleMemorySearch(query) {
  addBubble("user", `@memory ${query}`);
  input.value = ""; input.style.height = "auto";
  setLoading(true); showThinking();

  try {
    const res = await fetch(`/api/wiki/search?q=${encodeURIComponent(query)}`);
    hideThinking();
    if (!res.ok) { addBubble("error", t("something_wrong")); return; }
    const results = await res.json();

    if (!results.length) {
      addBubble("assistant", t("mem_no_results").replace("{q}", query));
    } else {
      const lines = results.map((r) => `**${r.slug}** (${r.category})\n${r.snippet}`);
      addBubble("assistant", `${t("mem_found")} ${results.length} ${t("mem_pages")}:\n\n${lines.join("\n\n---\n\n")}`);
    }
  } catch {
    hideThinking();
    addBubble("error", t("network_error"));
  } finally { setLoading(false); input.focus(); }
}

/* ── SSE Streaming Chat ── */

async function sendMessageStream(text) {
  // Handle @memory command
  if (text.startsWith("@memory ")) {
    return handleMemorySearch(text.slice(8).trim());
  }

  addBubble("user", text);
  input.value = ""; input.style.height = "auto";
  setLoading(true); showThinking();

  // Check active workflow — show apply banner
  const activeWf = currentConfig.active_workflow;
  if (activeWf && !document.querySelector(".wf-active-banner")) {
    showActiveWorkflowBanner(activeWf);
  }

  // Check for workflow recommendation (only if no active workflow)
  if (!activeWf && window.birkin.workflow?.checkRecommendation) {
    const rec = window.birkin.workflow.checkRecommendation(text);
    if (rec) setTimeout(() => window.birkin.workflow.showRecommendBanner(rec), 2000);
  }

  let currentToolBlock = null;

  try {
    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        session_id: sessionId,
        provider: currentConfig.provider || "anthropic",
        model: currentConfig.model || undefined,
      }),
    });

    if (!res.ok) {
      hideThinking();
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      addBubble("error", err.detail || t("something_wrong"));
      setLoading(false); input.focus();
      return;
    }

    hideThinking();
    let bubble = null;
    let accumulated = "";

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const raw = line.slice(6).trim();
        if (!raw) continue;
        try {
          const evt = JSON.parse(raw);

          if (evt.session_id) { sessionId = evt.session_id; }

          // Forward all events to workflow visualizer
          if (window.birkin.workflow) window.birkin.workflow.onEvent(evt);

          // Workflow step events
          if (evt.wf_step) {
            const step = evt.wf_step;
            const status = step.status === "done" ? "\u2705" : step.status === "error" ? "\u274C" : "\u23F3";
            if (step.status !== "done") {
              removeThinkingIndicator();
              const el = document.createElement("div");
              el.className = "tool-call";
              el.innerHTML = `<div class="tool-call-label">${status} ${esc(step.type)}</div>`;
              chat.appendChild(el);
              requestAnimationFrame(() => { chat.scrollTop = chat.scrollHeight; });
            }
          }

          if (evt.event === "fallback") {
            removeThinkingIndicator();
            addBubble("error", evt.message);
            showThinking();
          }

          if (evt.thinking === true) { removeThinkingIndicator(); createThinkingIndicator(); }
          if (evt.thinking === false) { removeThinkingIndicator(); }

          if (evt.tool_call) {
            removeThinkingIndicator();
            currentToolBlock = createToolCallBlock(evt.tool_call.name, evt.tool_call.input);
          }

          if (evt.tool_result && currentToolBlock) {
            appendToolResult(currentToolBlock, evt.tool_result.name, evt.tool_result.output, evt.tool_result.is_error);
          }

          if (evt.delta) {
            if (!bubble) bubble = createStreamBubble();
            accumulated += evt.delta;
            bubble.innerHTML = md(accumulated) + '<span class="cursor">|</span>';
            requestAnimationFrame(() => { chat.scrollTop = chat.scrollHeight; });
          }

          if (evt.done) {
            accumulated = evt.reply || accumulated;
            finalizeStreamBubble(bubble, accumulated);
            bubble = null;
          }

          if (evt.error) {
            if (bubble) { bubble.remove(); bubble = null; }
            addBubble("error", evt.error);
          }
        } catch { /* skip malformed */ }
      }
    }

    // Safety: finalize any stuck streaming bubble
    if (bubble) finalizeStreamBubble(bubble, accumulated);
    removeThinkingIndicator();
    loadSessions();
  } catch {
    hideThinking(); removeThinkingIndicator();
    addBubble("error", t("network_error"));
  } finally { setLoading(false); input.focus(); }
}

/* ── Active Workflow Banner ── */

async function showActiveWorkflowBanner(workflowId) {
  let wfName = workflowId;
  try {
    const res = await fetch(`/api/workflows/${workflowId}`);
    if (res.ok) { const wf = await res.json(); wfName = wf.name || workflowId; }
  } catch { /* */ }

  const banner = document.createElement("div");
  banner.className = "wf-active-banner";
  banner.innerHTML = `
    <span class="wf-active-icon">\u26A1</span>
    <span class="wf-active-text">${t("wf_active_using")} <strong>${esc(wfName)}</strong></span>
    <button class="wf-active-btn view" id="wf-ab-view">${t("wf_active_view")}</button>
    <button class="wf-active-btn off" id="wf-ab-off">${t("wf_active_disable")}</button>
    <button class="wf-active-dismiss" id="wf-ab-dismiss">\u2715</button>
  `;
  chat.appendChild(banner);
  chat.scrollTop = chat.scrollHeight;

  banner.querySelector("#wf-ab-view").onclick = () => { banner.remove(); switchView("workflow"); };
  banner.querySelector("#wf-ab-off").onclick = async () => {
    try {
      await fetch("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ active_workflow: null }) });
      currentConfig.active_workflow = null;
    } catch { /* */ }
    banner.remove();
  };
  banner.querySelector("#wf-ab-dismiss").onclick = () => banner.remove();
}

/* ── Session Management ── */

async function loadSessions() {
  try {
    const res = await fetch("/api/sessions");
    if (!res.ok) return;
    const sessions = await res.json();
    sessionList.innerHTML = "";
    if (!sessions.length) {
      sessionList.innerHTML = `<li class="session-empty">${t("no_conversations")}</li>`;
      return;
    }
    sessions.sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).forEach((s) => {
      const li = document.createElement("li");
      li.className = "session-item" + (s.id === sessionId ? " active" : "");
      li.setAttribute("role", "button"); li.setAttribute("tabindex", "0");
      li.innerHTML = `<span class="session-item-text">${t("chat")} (${s.message_count} ${t("chat_msgs")})</span><span class="session-item-meta">${fmtDate(s.created_at)}</span>`;
      const del = document.createElement("button");
      del.className = "session-item-delete"; del.textContent = "\u2715"; del.setAttribute("aria-label", "Delete");
      del.onclick = (e) => { e.stopPropagation(); deleteSession(s.id); };
      li.appendChild(del);
      li.onclick = () => switchSession(s.id);
      sessionList.appendChild(li);
    });
  } catch { /* silent */ }
}

async function switchSession(id) {
  try {
    const res = await fetch(`/api/sessions/${id}`);
    if (!res.ok) return;
    const data = await res.json();
    sessionId = id;
    chat.innerHTML = "";
    (data.messages || []).forEach((m) => {
      // Skip tool/system messages — only render user + assistant
      if (m.role === "user" || m.role === "assistant") addBubble(m.role, m.content);
    });
    loadSessions(); closeSidebar(); input.focus();
  } catch { /* */ }
}

async function deleteSession(id) {
  try {
    await fetch(`/api/sessions/${id}`, { method: "DELETE" });
    if (id === sessionId) startNewChat();
    loadSessions();
  } catch { /* */ }
}

function startNewChat() {
  sessionId = null; chat.innerHTML = "";
  const w = document.createElement("div");
  w.className = "welcome"; w.id = "welcome";
  w.innerHTML = `
    <div class="welcome-icon" aria-hidden="true"><svg width="48" height="48" viewBox="0 0 48 48" fill="none"><rect x="4" y="8" width="40" height="28" rx="6" stroke="currentColor" stroke-width="2.5"/><path d="M14 20h8M14 26h16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M16 36l-4 6M32 36l4 6" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/></svg></div>
    <p class="welcome-title">${t("welcome_title")}</p>
    <p class="welcome-sub">${t("welcome_sub")}</p>
    <div class="suggestions">
      <button class="suggestion" type="button">${t("suggest_explain")}</button>
      <button class="suggestion" type="button">${t("suggest_email")}</button>
      <button class="suggestion" type="button">${t("suggest_brainstorm")}</button>
    </div>
    <button class="welcome-help-link" type="button">${t("welcome_help_link")}</button>`;
  chat.appendChild(w);
  bindSuggestions(w);
  w.querySelector(".welcome-help-link").onclick = openHelp;
  loadSessions(); input.focus();
}

function fmtDate(d) {
  const ms = Date.now() - new Date(d);
  const m = Math.floor(ms / 60000);
  if (m < 1) return t("just_now");
  if (m < 60) return `${m}m`;
  const h = Math.floor(ms / 3600000);
  if (h < 24) return `${h}h`;
  const dy = Math.floor(ms / 86400000);
  if (dy < 7) return `${dy}d`;
  return new Date(d).toLocaleDateString();
}

/* ── Panels ── */

function openSidebar() { sidebar.classList.add("open"); sidebarOverlay.classList.add("visible"); loadSessions(); }
function closeSidebar() { sidebar.classList.remove("open"); sidebarOverlay.classList.remove("visible"); }
sidebarToggle.onclick = () => sidebar.classList.contains("open") ? closeSidebar() : openSidebar();
sidebarOverlay.onclick = closeSidebar;
newChatBtn.onclick = () => { startNewChat(); closeSidebar(); };

function openHelp() { helpPanel.classList.add("open"); helpOverlay.classList.add("visible"); helpPanel.setAttribute("aria-hidden","false"); }
function closeHelp() { helpPanel.classList.remove("open"); helpOverlay.classList.remove("visible"); helpPanel.setAttribute("aria-hidden","true"); }
helpToggle.onclick = openHelp;
helpClose.onclick = closeHelp;
helpOverlay.onclick = closeHelp;
welcomeHelp.onclick = openHelp;

function openSettings() { loadSettingsPanel(); settingsPanel.classList.add("open"); settingsOverlay.classList.add("visible"); settingsPanel.setAttribute("aria-hidden","false"); }
function closeSettings() { settingsPanel.classList.remove("open"); settingsOverlay.classList.remove("visible"); settingsPanel.setAttribute("aria-hidden","true"); }
settingsToggle.onclick = openSettings;
settingsClose.onclick = closeSettings;
settingsOverlay.onclick = closeSettings;

/* ── Settings Panel ── */

async function loadSettingsPanel() {
  try {
    const [cfgRes, provRes] = await Promise.all([
      fetch("/api/settings"),
      fetch("/api/settings/providers"),
    ]);
    if (cfgRes.ok) currentConfig = await cfgRes.json();
    if (provRes.ok) providersCache = await provRes.json();
  } catch { /* */ }

  const providers = providersCache || {};
  const cfg = currentConfig;
  const labels = { anthropic: t("anthropic_claude"), openai: t("openai_gpt"), "claude-cli": t("claude_code"), "codex-cli": t("codex_cli") };

  settingsContent.innerHTML = `
    <div class="settings-section">
      <div class="settings-section-title">${t("provider")}</div>
      <div class="settings-provider-list" id="s-providers">
        ${Object.entries(providers).map(([k, v]) => `
          <label class="settings-provider-opt ${v.available ? '' : 'unavailable'}">
            <input type="radio" name="s-provider" value="${k}" ${k === cfg.provider ? 'checked' : ''} ${v.available ? '' : 'disabled'} />
            <span class="dot ${v.available ? 'ok' : ''}"></span>
            <span class="settings-provider-name">${labels[k] || k}</span>
            <span class="settings-provider-meta">${v.type === 'local' ? t("local_no_key") : v.key_env || ''}</span>
          </label>`).join("")}
      </div>
    </div>

    <div class="settings-section">
      <div class="settings-section-title">${t("api_keys")}</div>
      <div class="settings-field">
        <label class="settings-label">${t("anthropic_key")}</label>
        <div class="settings-key-wrap">
          <input class="settings-input" type="password" id="s-key-anthropic" placeholder="sk-ant-..." value="" autocomplete="off" />
          <button class="settings-key-toggle" type="button" data-target="s-key-anthropic" aria-label="${t("toggle_vis")}">&#128065;</button>
        </div>
      </div>
      <div class="settings-field">
        <label class="settings-label">${t("openai_key")}</label>
        <div class="settings-key-wrap">
          <input class="settings-input" type="password" id="s-key-openai" placeholder="sk-..." value="" autocomplete="off" />
          <button class="settings-key-toggle" type="button" data-target="s-key-openai" aria-label="${t("toggle_vis")}">&#128065;</button>
        </div>
      </div>
    </div>

    <div class="settings-section">
      <div class="settings-section-title">${t("model")}</div>
      <div class="settings-field">
        <label class="settings-label">${t("primary_model")}</label>
        <select class="settings-select" id="s-model">
          <option value="">${t("default")}</option>
        </select>
      </div>
    </div>

    <div class="settings-section">
      <div class="settings-section-title">${t("fallback")}</div>
      <div class="settings-field">
        <label class="settings-label">${t("fallback_provider")}</label>
        <select class="settings-select" id="s-fallback">
          <option value="">${t("none")}</option>
          ${Object.entries(providers).filter(([,v]) => v.available).map(([k]) => `<option value="${k}" ${k === cfg.fallback_provider ? 'selected' : ''}>${labels[k] || k}</option>`).join("")}
        </select>
      </div>
    </div>

    <div class="settings-section">
      <div class="settings-section-title">${t("system_prompt")}</div>
      <div class="settings-field">
        <textarea class="settings-textarea" id="s-system-prompt" placeholder="${t("system_prompt_ph")}">${esc(cfg.system_prompt || "")}</textarea>
      </div>
    </div>

    <div class="settings-actions">
      <button class="ghost-btn" id="s-save" type="button">${t("save")}</button>
      <button class="ghost-btn secondary" id="s-reset" type="button">${t("reset")}</button>
    </div>
  `;

  // Populate model dropdown
  populateModels();

  // Wire events
  settingsContent.querySelector("#s-save").onclick = saveSettings;
  settingsContent.querySelector("#s-reset").onclick = resetSettings;
  settingsContent.querySelectorAll('input[name="s-provider"]').forEach((r) => { r.onchange = populateModels; });
  settingsContent.querySelectorAll(".settings-key-toggle").forEach((btn) => {
    btn.onclick = () => {
      const inp = $(btn.dataset.target);
      inp.type = inp.type === "password" ? "text" : "password";
    };
  });
}

function populateModels() {
  const sel = $("s-model");
  if (!sel) return;
  const prov = settingsContent.querySelector('input[name="s-provider"]:checked')?.value;
  const info = providersCache?.[prov];
  sel.innerHTML = '<option value="">Default</option>';
  if (info?.models) {
    info.models.forEach((m) => {
      const opt = document.createElement("option");
      opt.value = m; opt.textContent = m;
      if (m === currentConfig.model) opt.selected = true;
      sel.appendChild(opt);
    });
  }
}

async function saveSettings() {
  const prov = settingsContent.querySelector('input[name="s-provider"]:checked')?.value;
  const model = $("s-model")?.value || null;
  const fallback = $("s-fallback")?.value || null;
  const sysPrompt = $("s-system-prompt")?.value?.trim() || null;

  const config = { provider: prov, model: model, fallback_provider: fallback, system_prompt: sysPrompt, onboarding_complete: true };

  try {
    await fetch("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(config) });
    currentConfig = { ...currentConfig, ...config };
  } catch { /* */ }

  // Save API keys if entered
  const keys = {};
  const antKey = $("s-key-anthropic")?.value?.trim();
  const oaiKey = $("s-key-openai")?.value?.trim();
  if (antKey) keys.ANTHROPIC_API_KEY = antKey;
  if (oaiKey) keys.OPENAI_API_KEY = oaiKey;
  if (Object.keys(keys).length) {
    try { await fetch("/api/settings/keys", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(keys) }); } catch { /* */ }
  }

  updateProviderBadge();
  closeSettings();
}

async function resetSettings() {
  try {
    await fetch("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider: "anthropic", model: null, fallback_provider: null, fallback_model: null, system_prompt: null, onboarding_complete: true }) });
    currentConfig = { provider: "anthropic", model: null, onboarding_complete: true };
  } catch { /* */ }
  updateProviderBadge();
  closeSettings();
}

/* ── Provider Badge ── */

async function updateProviderBadge() {
  try {
    const [cfgRes, provRes] = await Promise.all([fetch("/api/settings"), fetch("/api/settings/providers")]);
    if (cfgRes.ok) currentConfig = await cfgRes.json();
    if (provRes.ok) providersCache = await provRes.json();
  } catch { /* */ }

  const prov = currentConfig.provider || "anthropic";
  const info = providersCache?.[prov];
  const ok = info?.available ?? false;
  const short = { anthropic: "Claude", openai: "GPT", "claude-cli": "CLI", "codex-cli": "Codex" };
  providerBadge.innerHTML = `<span class="dot ${ok ? 'ok' : ''}"></span><span>${short[prov] || prov}</span>`;
}

/* ── Suggestions ── */

function bindSuggestions(c) { c.querySelectorAll(".suggestion").forEach((b) => { b.onclick = () => { input.value = b.textContent; form.requestSubmit(); }; }); }
bindSuggestions(document);

/* ── Auto-resize ── */

input.oninput = () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 160) + "px"; };

/* ── Submit ── */

form.onsubmit = (e) => { e.preventDefault(); const t = input.value.trim(); if (t) sendMessageStream(t); };
input.onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } };

document.onkeydown = (e) => {
  if (e.key === "Escape") {
    if (settingsPanel.classList.contains("open")) closeSettings();
    else if (helpPanel.classList.contains("open")) closeHelp();
    else if (sidebar.classList.contains("open")) closeSidebar();
  }
};

/* ── Onboarding ── */

async function checkOnboarding() {
  try {
    const res = await fetch("/api/settings");
    if (res.ok) currentConfig = await res.json();
    if (currentConfig.onboarding_complete) return;
    const pRes = await fetch("/api/settings/providers");
    if (pRes.ok) { const p = await pRes.json(); providersCache = p; showOnboarding(p); }
  } catch { /* */ }
}

function showOnboarding(providers) {
  const overlay = document.createElement("div");
  overlay.className = "onboarding-overlay";
  const modal = document.createElement("div");
  modal.className = "onboarding-modal";
  const labels = { anthropic: t("anthropic_claude"), openai: t("openai_gpt"), "claude-cli": t("claude_code_local"), "codex-cli": t("codex_cli_local") };
  const first = Object.entries(providers).find(([, v]) => v.available);
  const def = first ? first[0] : "anthropic";

  modal.innerHTML = `
    <h2 class="ob-title">${t("ob_welcome")}</h2>
    <p class="ob-sub">${t("ob_select_provider")}</p>
    <div class="ob-providers">${Object.entries(providers).map(([k, v]) => `
      <label class="ob-provider ${v.available ? '' : 'unavailable'}">
        <input type="radio" name="ob-prov" value="${k}" ${v.available ? '' : 'disabled'} ${k === def ? 'checked' : ''} />
        <div class="ob-provider-info">
          <strong>${labels[k] || k}</strong>
          ${v.available ? `<span class="ob-status ok">${t("ob_ready")}</span>` : v.needs_key ? `<span class="ob-status warn">${t("ob_key_needed")}</span>` : `<span class="ob-status off">${t("ob_not_found")}</span>`}
          <small>${v.type === 'local' ? t("local_no_key") : `Env: ${v.key_env}`}</small>
        </div>
      </label>`).join("")}</div>
    <details class="ob-advanced"><summary>${t("ob_fallback_title")}</summary>
      <p class="ob-hint">${t("ob_fallback_desc")}</p>
      <select id="ob-fallback" class="ob-select"><option value="">${t("none")}</option>${Object.entries(providers).filter(([,v]) => v.available).map(([k]) => `<option value="${k}">${labels[k] || k}</option>`).join("")}</select>
    </details>
    <div class="ob-actions">
      <button class="ob-btn primary" id="ob-save">${t("ob_start")}</button>
      <button class="ob-btn secondary" id="ob-skip">${t("ob_skip")}</button>
    </div>`;

  overlay.appendChild(modal);
  document.body.appendChild(overlay);

  modal.querySelector("#ob-save").onclick = async () => {
    const prov = modal.querySelector('input[name="ob-prov"]:checked')?.value || def;
    const fb = modal.querySelector("#ob-fallback")?.value || null;
    try { await fetch("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider: prov, fallback_provider: fb, onboarding_complete: true }) }); currentConfig = { ...currentConfig, provider: prov, onboarding_complete: true }; } catch {}
    overlay.remove(); updateProviderBadge(); input.focus();
  };
  modal.querySelector("#ob-skip").onclick = async () => {
    try { await fetch("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ onboarding_complete: true }) }); } catch {}
    overlay.remove(); input.focus();
  };
}

/* ── View Router ── */

let currentView = "chat";
const viewContainers = { chat: $("view-chat"), workflow: $("view-workflow"), memory: $("view-memory"), telegram: $("view-telegram"), triggers: $("view-triggers"), skills: $("view-skills"), dashboard: $("view-dashboard"), approvals: $("view-approvals"), insights: $("view-insights") };
const viewHooks = {};  // { viewName: { onActivate: fn } }

function switchView(name) {
  if (!viewContainers[name]) return;
  currentView = name;
  Object.entries(viewContainers).forEach(([k, el]) => { el.classList.toggle("active", k === name); });
  document.querySelectorAll(".view-nav-btn").forEach((btn) => { btn.classList.toggle("active", btn.dataset.view === name); });
  if (viewHooks[name]?.onActivate) viewHooks[name].onActivate();
}

document.querySelectorAll(".view-nav-btn").forEach((btn) => {
  btn.onclick = () => switchView(btn.dataset.view);
});

/* ── Language Toggle ── */

const langToggle = $("lang-toggle");
const t = window.birkin.t;

function updateLangButton() {
  const lang = window.birkin.getLang();
  langToggle.textContent = lang === "ko" ? "\uD55C" : "EN";
}

langToggle.onclick = () => {
  const next = window.birkin.getLang() === "en" ? "ko" : "en";
  window.birkin.setLang(next);
  updateLangButton();
  refreshTranslatedUI();
};

function refreshTranslatedUI() {
  // Static HTML elements
  const map = {
    ".sidebar-title": "conversations",
    ".welcome-title": "welcome_title",
    ".welcome-sub": "welcome_sub",
    "#user-input": { attr: "placeholder", key: "input_placeholder" },
    ".input-hint": { html: true, key: "input_hint_html" },
  };

  // Sidebar title
  const sidebarTitle = document.querySelector(".sidebar-title");
  if (sidebarTitle) sidebarTitle.textContent = t("conversations");

  // Input placeholder
  const inp = $("user-input");
  if (inp) inp.placeholder = t("input_placeholder");

  // Nav buttons
  document.querySelectorAll(".view-nav-btn").forEach((btn) => {
    const view = btn.dataset.view;
    const span = btn.querySelector("span");
    if (span && view) span.textContent = t(view);
  });

  // Help panel title
  const helpTitle = document.querySelector(".help-title");
  if (helpTitle) helpTitle.textContent = t("help");

  // Settings panel title
  const settingsTitle = document.querySelector(".settings-title");
  if (settingsTitle) settingsTitle.textContent = t("settings");
}

/* ── Global Namespace ── */

Object.assign(window.birkin, {
  $, md, esc, switchView, currentConfig,
  viewHooks,
  updateProviderBadge,
  refreshTranslatedUI,
});
Object.defineProperty(window.birkin, "sessionId", {
  get() { return sessionId; },
  set(v) { sessionId = v; },
});

/* ── Auth Gate ── */

async function checkAuth() {
  try {
    const res = await fetch("/api/auth/status");
    if (!res.ok) return;
    const data = await res.json();
    if (!data.auth_required || data.authenticated) return;

    // Check for ?token= query param
    const params = new URLSearchParams(window.location.search);
    const urlToken = params.get("token");
    if (urlToken) {
      const bRes = await fetch("/api/auth/bootstrap", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: urlToken }),
      });
      if (bRes.ok) {
        // Strip token from URL
        params.delete("token");
        const newUrl = params.toString()
          ? `${window.location.pathname}?${params}`
          : window.location.pathname;
        history.replaceState(null, "", newUrl);
        return;
      }
    }

    // Show login prompt
    showLoginOverlay();
  } catch { /* silent */ }
}

function showLoginOverlay() {
  const overlay = document.createElement("div");
  overlay.className = "onboarding-overlay";
  overlay.id = "auth-overlay";
  const modal = document.createElement("div");
  modal.className = "onboarding-modal";
  modal.innerHTML = `
    <h2 class="ob-title">Authentication Required</h2>
    <p class="ob-sub">Enter your access token to continue.</p>
    <div class="settings-field" style="margin:1rem 0">
      <input class="settings-input" type="password" id="auth-token-input" placeholder="Paste token..." autocomplete="off" />
    </div>
    <p id="auth-error" style="color:var(--accent-red,#e74c3c);display:none;margin-bottom:0.5rem"></p>
    <div class="ob-actions">
      <button class="ob-btn primary" id="auth-submit">Sign In</button>
    </div>`;
  overlay.appendChild(modal);
  document.body.appendChild(overlay);

  const inp = modal.querySelector("#auth-token-input");
  const errEl = modal.querySelector("#auth-error");
  const btn = modal.querySelector("#auth-submit");

  async function doLogin() {
    const token = inp.value.trim();
    if (!token) return;
    btn.disabled = true;
    try {
      const res = await fetch("/api/auth/bootstrap", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
      if (res.ok) {
        overlay.remove();
        return;
      }
      errEl.textContent = "Invalid token. Please try again.";
      errEl.style.display = "block";
    } catch {
      errEl.textContent = "Network error.";
      errEl.style.display = "block";
    } finally {
      btn.disabled = false;
    }
  }

  btn.onclick = doLogin;
  inp.onkeydown = (e) => { if (e.key === "Enter") doLogin(); };
  inp.focus();
}

/* ── Init ── */

updateLangButton();
refreshTranslatedUI();
loadSessions();
updateProviderBadge();
checkAuth();
checkOnboarding();
