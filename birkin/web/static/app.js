/* Birkin Web UI — chat client */

const chat = document.getElementById("chat");
const form = document.getElementById("input-form");
const input = document.getElementById("user-input");
const sendBtn = document.getElementById("send-btn");
const welcome = document.getElementById("welcome");

let sessionId = null;

/* ── Helpers ── */

function addBubble(role, text) {
  if (welcome) welcome.remove();
  const el = document.createElement("div");
  el.className = `bubble ${role}`;
  el.textContent = text;
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
  return el;
}

function showThinking() {
  const el = document.createElement("div");
  el.className = "thinking";
  el.id = "thinking";
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
  } catch (err) {
    hideThinking();
    addBubble("error", "Network error — is the server running?");
  } finally {
    setLoading(false);
    input.focus();
  }
});

/* ── Enter to send, Shift+Enter for newline ── */

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});
