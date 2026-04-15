/* Birkin Web UI — chat client with session management & help */

const chat = document.getElementById("chat");
const form = document.getElementById("input-form");
const input = document.getElementById("user-input");
const sendBtn = document.getElementById("send-btn");
const welcome = document.getElementById("welcome");
const suggestions = document.getElementById("suggestions");
const sidebar = document.getElementById("sidebar");
const sidebarToggle = document.getElementById("sidebar-toggle");
const sidebarOverlay = document.getElementById("sidebar-overlay");
const newChatBtn = document.getElementById("new-chat-btn");
const sessionList = document.getElementById("session-list");
const sessionEmpty = document.getElementById("session-empty");
const helpPanel = document.getElementById("help-panel");
const helpToggle = document.getElementById("help-toggle");
const helpClose = document.getElementById("help-close");
const helpOverlay = document.getElementById("help-overlay");
const welcomeHelp = document.getElementById("welcome-help");

let sessionId = null;

/* ── Minimal Markdown Parser ── */

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function parseMarkdown(text) {
  const lines = text.split("\n");
  const html = [];
  let inCodeBlock = false;
  let codeBuffer = [];
  let codeLang = "";
  let inList = false;
  let listType = "";

  function closeList() {
    if (inList) {
      html.push(listType === "ol" ? "</ol>" : "</ul>");
      inList = false;
      listType = "";
    }
  }

  function inlineFormat(line) {
    return line
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>")
      .replace(/__([^_]+)__/g, "<strong>$1</strong>")
      .replace(/_([^_]+)_/g, "<em>$1</em>")
      .replace(
        /\[([^\]]+)\]\(([^)]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
      );
  }

  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i];

    // Code blocks
    if (raw.trimStart().startsWith("```")) {
      if (inCodeBlock) {
        html.push(
          "<pre><code>" + escapeHtml(codeBuffer.join("\n")) + "</code></pre>"
        );
        codeBuffer = [];
        codeLang = "";
        inCodeBlock = false;
      } else {
        closeList();
        codeLang = raw.trimStart().slice(3).trim();
        inCodeBlock = true;
      }
      continue;
    }

    if (inCodeBlock) {
      codeBuffer.push(raw);
      continue;
    }

    const trimmed = raw.trim();

    // Empty line
    if (trimmed === "") {
      closeList();
      continue;
    }

    // Headings
    const headingMatch = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (headingMatch) {
      closeList();
      const level = headingMatch[1].length;
      html.push(
        `<h${level}>${inlineFormat(escapeHtml(headingMatch[2]))}</h${level}>`
      );
      continue;
    }

    // Unordered list
    if (/^[-*+]\s+/.test(trimmed)) {
      if (!inList || listType !== "ul") {
        closeList();
        html.push("<ul>");
        inList = true;
        listType = "ul";
      }
      const content = trimmed.replace(/^[-*+]\s+/, "");
      html.push(`<li>${inlineFormat(escapeHtml(content))}</li>`);
      continue;
    }

    // Ordered list
    if (/^\d+\.\s+/.test(trimmed)) {
      if (!inList || listType !== "ol") {
        closeList();
        html.push("<ol>");
        inList = true;
        listType = "ol";
      }
      const content = trimmed.replace(/^\d+\.\s+/, "");
      html.push(`<li>${inlineFormat(escapeHtml(content))}</li>`);
      continue;
    }

    // Paragraph
    closeList();
    html.push(`<p>${inlineFormat(escapeHtml(trimmed))}</p>`);
  }

  // Close any open blocks
  if (inCodeBlock) {
    html.push(
      "<pre><code>" + escapeHtml(codeBuffer.join("\n")) + "</code></pre>"
    );
  }
  closeList();

  return html.join("\n");
}

/* ── Chat Helpers ── */

function addBubble(role, text) {
  if (welcome && welcome.parentNode) welcome.remove();
  const el = document.createElement("div");
  el.className = `bubble ${role}`;

  if (role === "assistant") {
    el.innerHTML = parseMarkdown(text);
  } else {
    el.textContent = text;
  }

  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
  return el;
}

function showThinking() {
  const el = document.createElement("div");
  el.className = "thinking";
  el.id = "thinking";
  el.setAttribute("role", "status");
  el.setAttribute("aria-label", "Birkin is thinking");
  el.innerHTML = "<span></span><span></span><span></span>";
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
}

function hideThinking() {
  const el = document.getElementById("thinking");
  if (el) el.remove();
}

function setLoading(on) {
  sendBtn.disabled = on;
  input.disabled = on;
}

/* ── Session Management ── */

async function loadSessions() {
  try {
    const res = await fetch("/api/sessions");
    if (!res.ok) return;
    const sessions = await res.json();

    sessionList.innerHTML = "";

    if (sessions.length === 0) {
      const empty = document.createElement("li");
      empty.className = "session-empty";
      empty.textContent = "No conversations yet";
      sessionList.appendChild(empty);
      return;
    }

    sessions
      .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
      .forEach((s) => {
        const li = document.createElement("li");
        li.className = "session-item" + (s.id === sessionId ? " active" : "");
        li.setAttribute("role", "button");
        li.setAttribute("tabindex", "0");
        li.setAttribute("aria-label", `Conversation from ${formatDate(s.created_at)}, ${s.message_count} messages`);

        const text = document.createElement("span");
        text.className = "session-item-text";
        text.textContent = `Chat (${s.message_count} msgs)`;

        const meta = document.createElement("span");
        meta.className = "session-item-meta";
        meta.textContent = formatDate(s.created_at);

        const delBtn = document.createElement("button");
        delBtn.className = "session-item-delete";
        delBtn.setAttribute("aria-label", "Delete conversation");
        delBtn.textContent = "\u2715";
        delBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          deleteSession(s.id);
        });

        li.appendChild(text);
        li.appendChild(meta);
        li.appendChild(delBtn);

        li.addEventListener("click", () => switchSession(s.id));
        li.addEventListener("keydown", (e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            switchSession(s.id);
          }
        });

        sessionList.appendChild(li);
      });
  } catch {
    // Silently fail — sidebar just stays empty
  }
}

async function switchSession(id) {
  try {
    const res = await fetch(`/api/sessions/${id}`);
    if (!res.ok) return;
    const data = await res.json();

    sessionId = id;

    // Clear chat and rebuild from history
    chat.innerHTML = "";
    if (data.messages && data.messages.length > 0) {
      data.messages.forEach((m) => addBubble(m.role, m.content));
    }

    loadSessions();
    closeSidebar();
    input.focus();
  } catch {
    // Ignore
  }
}

async function deleteSession(id) {
  try {
    await fetch(`/api/sessions/${id}`, { method: "DELETE" });
    if (id === sessionId) {
      startNewChat();
    }
    loadSessions();
  } catch {
    // Ignore
  }
}

function startNewChat() {
  sessionId = null;
  chat.innerHTML = "";

  // Re-add welcome screen
  const w = document.createElement("div");
  w.className = "welcome";
  w.id = "welcome";
  w.innerHTML = `
    <div class="welcome-icon" aria-hidden="true">
      <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
        <rect x="4" y="8" width="40" height="28" rx="6" stroke="currentColor" stroke-width="2.5"/>
        <path d="M14 20h8M14 26h16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
        <path d="M16 36l-4 6M32 36l4 6" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>
      </svg>
    </div>
    <p class="welcome-title">Hello, I'm Birkin.</p>
    <p class="welcome-sub">Your AI assistant. Try one of these to get started:</p>
    <div class="suggestions">
      <button class="suggestion" type="button">Explain what you can do</button>
      <button class="suggestion" type="button">Help me draft an email</button>
      <button class="suggestion" type="button">Summarize a topic for me</button>
      <button class="suggestion" type="button">Brainstorm ideas</button>
    </div>
    <button class="welcome-help-link" type="button">Need help? Open the guide</button>
  `;
  chat.appendChild(w);

  // Re-bind suggestion clicks
  bindSuggestions(w);
  w.querySelector(".welcome-help-link").addEventListener("click", openHelp);

  loadSessions();
  input.focus();
}

function formatDate(dateStr) {
  const d = new Date(dateStr);
  const now = new Date();
  const diff = now - d;
  const mins = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);

  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  if (hours < 24) return `${hours}h ago`;
  if (days < 7) return `${days}d ago`;
  return d.toLocaleDateString();
}

/* ── Sidebar ── */

function openSidebar() {
  sidebar.classList.add("open");
  sidebarOverlay.classList.add("visible");
  sidebar.setAttribute("aria-hidden", "false");
  loadSessions();
}

function closeSidebar() {
  sidebar.classList.remove("open");
  sidebarOverlay.classList.remove("visible");
  sidebar.setAttribute("aria-hidden", "true");
}

function toggleSidebar() {
  if (sidebar.classList.contains("open")) {
    closeSidebar();
  } else {
    openSidebar();
  }
}

sidebarToggle.addEventListener("click", toggleSidebar);
sidebarOverlay.addEventListener("click", closeSidebar);
newChatBtn.addEventListener("click", () => {
  startNewChat();
  closeSidebar();
});

/* ── Help Panel ── */

function openHelp() {
  helpPanel.classList.add("open");
  helpOverlay.classList.add("visible");
  helpPanel.setAttribute("aria-hidden", "false");
  helpClose.focus();
}

function closeHelp() {
  helpPanel.classList.remove("open");
  helpOverlay.classList.remove("visible");
  helpPanel.setAttribute("aria-hidden", "true");
}

helpToggle.addEventListener("click", openHelp);
helpClose.addEventListener("click", closeHelp);
helpOverlay.addEventListener("click", closeHelp);
welcomeHelp.addEventListener("click", openHelp);

/* ── Suggestion Buttons ── */

function bindSuggestions(container) {
  container.querySelectorAll(".suggestion").forEach((btn) => {
    btn.addEventListener("click", () => {
      input.value = btn.textContent;
      form.requestSubmit();
    });
  });
}

bindSuggestions(document);

/* ── Auto-resize textarea ── */

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
});

/* ── Submit ── */

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;

  addBubble("user", text);
  input.value = "";
  input.style.height = "auto";
  setLoading(true);
  showThinking();

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        session_id: sessionId,
      }),
    });

    hideThinking();

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      addBubble("error", err.detail || "Something went wrong.");
      return;
    }

    const data = await res.json();
    sessionId = data.session_id;
    addBubble("assistant", data.reply);

    // Refresh session list in sidebar
    loadSessions();
  } catch {
    hideThinking();
    addBubble("error", "Network error \u2014 is the server running?");
  } finally {
    setLoading(false);
    input.focus();
  }
});

/* ── Keyboard shortcuts ── */

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (helpPanel.classList.contains("open")) {
      closeHelp();
    } else if (sidebar.classList.contains("open")) {
      closeSidebar();
    }
  }
});

/* ── Initial load ── */

loadSessions();
