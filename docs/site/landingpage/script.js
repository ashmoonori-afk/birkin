// =========================================================================
// Birkin Landing Page — Interactions
// Warm, chat-first design — no Three.js, no terminal
// =========================================================================

// --- Mobile nav ---
function toggleMobileNav() {
  document.getElementById("nav-mobile").classList.toggle("open");
  document.getElementById("nav-hamburger").classList.toggle("open");
}

// --- Copy to clipboard ---
function copyText(btn) {
  const text = btn.getAttribute("data-text");
  if (!text) return;
  navigator.clipboard.writeText(text).then(() => {
    const label = btn.querySelector(".copy-label");
    if (label) {
      const original = label.textContent;
      label.textContent = "Copied!";
      setTimeout(() => {
        label.textContent = original;
      }, 2000);
    }
  });
}

// --- Scroll-triggered fade-in ---
function initScrollAnimations() {
  const elements = document.querySelectorAll(
    ".feature-card, .step-card, .section-header, .demo-window, " +
      ".install-card, .oss-card",
  );

  elements.forEach((el) => el.classList.add("fade-in"));

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          const parent = entry.target.parentElement;
          if (parent) {
            const siblings = parent.querySelectorAll(".fade-in");
            let idx = Array.from(siblings).indexOf(entry.target);
            if (idx < 0) idx = 0;
            setTimeout(() => {
              entry.target.classList.add("visible");
            }, idx * 60);
          } else {
            entry.target.classList.add("visible");
          }
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.1, rootMargin: "0px 0px -40px 0px" },
  );

  elements.forEach((el) => observer.observe(el));
}

// --- Chat Conversation Demo ---
const chatConversations = [
  {
    title: "Research project",
    messages: [
      {
        role: "user",
        text: "Find the latest approaches to GRPO training and summarize them for me",
      },
      {
        role: "bot",
        text: 'I searched 4 sources and wrote a summary covering:<br><br><strong>Key findings:</strong><br>• GRPO uses group-relative advantage — no critic model needed<br>• Outperforms PPO/DPO on reasoning benchmarks<br>• Implementation available in Axolotl and TRL<br><br>Saved to <strong>~/research/grpo-summary.md</strong>',
      },
      {
        role: "user",
        text: "Can you compare it with the DPO approach we used last month?",
      },
      {
        role: "bot",
        text: "Based on your session from March 12th, you used DPO with a custom reward model. Here's how they compare:<br><br>• <strong>GRPO</strong>: No critic model, lower compute cost, better on math tasks<br>• <strong>DPO</strong>: Simpler setup, good for preference alignment<br><br>For your use case, GRPO would save ~40% training cost.",
      },
    ],
  },
  {
    title: "Code review",
    messages: [
      {
        role: "user",
        text: "Review the PR at birkin#42 and fix any issues",
      },
      {
        role: "bot",
        text: "Found 2 issues in PR #42 and fixed both:<br><br>• Empty tool schema crash in registry.py — added guard<br>• Missing error handling in delegate_tool.py — added try/except<br><br>Tests pass. Committed the fix and pushed to the PR branch.",
      },
      {
        role: "user",
        text: "Nice. Also add tests for the edge cases you found",
      },
      {
        role: "bot",
        text: "Done! Added 3 test cases:<br><br>• <strong>test_empty_schema_returns_default</strong><br>• <strong>test_malformed_schema_raises</strong><br>• <strong>test_delegate_timeout_handled</strong><br><br>Coverage went from 78% → 84%. Pushed to the same branch.",
      },
    ],
  },
  {
    title: "Daily planning",
    messages: [
      {
        role: "user",
        text: "What's on my plate today?",
      },
      {
        role: "bot",
        text: "Here's your day:<br><br><strong>Meetings:</strong><br>• 9:00 AM — Team standup (15 min)<br>• 11:30 AM — Design review with Sarah<br>• 2:00 PM — Client call (Project Atlas)<br><br><strong>Tasks due:</strong><br>• Finish API docs for v2 endpoints<br>• Review Lisa's PR on auth middleware",
      },
      {
        role: "user",
        text: "Move the client call to Thursday and block 2 hours for the API docs",
      },
      {
        role: "bot",
        text: "Done!<br><br>• Moved Project Atlas call to <strong>Thursday 2:00 PM</strong> — sent update to all participants<br>• Blocked <strong>2:00–4:00 PM today</strong> for API docs work<br><br>You now have a clear afternoon for focused work.",
      },
    ],
  },
];

class ChatDemo {
  constructor(container) {
    this.container = container;
    this.running = false;
    this.currentConversation = 0;
  }

  async start() {
    if (this.running) return;
    this.running = true;

    while (this.running) {
      const conversation =
        chatConversations[this.currentConversation % chatConversations.length];
      await this.playConversation(conversation);
      this.currentConversation++;
      await this.sleep(1500);
    }
  }

  stop() {
    this.running = false;
  }

  async playConversation(conversation) {
    this.container.innerHTML = "";

    for (const msg of conversation.messages) {
      if (!this.running) return;

      if (msg.role === "user") {
        await this.sleep(400);
        this.addMessage("user", msg.text);
        await this.sleep(600);
        // Show typing indicator before bot response
        const nextMsg = conversation.messages[
          conversation.messages.indexOf(msg) + 1
        ];
        if (nextMsg && nextMsg.role === "bot") {
          this.showTyping();
          await this.sleep(1200);
          this.removeTyping();
        }
      } else {
        this.addMessage("bot", msg.text);
        await this.sleep(2500);
      }
    }

    await this.sleep(3000);
  }

  addMessage(role, html) {
    const wrapper = document.createElement("div");
    wrapper.className = `demo-msg demo-msg-${role}`;
    wrapper.innerHTML = html;
    this.container.appendChild(wrapper);
    this.container.scrollTop = this.container.scrollHeight;
  }

  showTyping() {
    const wrapper = document.createElement("div");
    wrapper.className = "demo-msg demo-msg-bot";
    wrapper.id = "typing-indicator";
    wrapper.innerHTML =
      '<span class="msg-typing">' +
      '<span class="typing-dot"></span>' +
      '<span class="typing-dot"></span>' +
      '<span class="typing-dot"></span>' +
      "</span>";
    this.container.appendChild(wrapper);
    this.container.scrollTop = this.container.scrollHeight;
  }

  removeTyping() {
    const typing = document.getElementById("typing-indicator");
    if (typing) typing.remove();
  }

  sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}

// --- Hero chat (static, pre-filled) ---
function initHeroChat() {
  const container = document.getElementById("hero-chat");
  if (!container) return;

  const messages = [
    { role: "user", text: "What meetings do I have tomorrow?" },
    {
      role: "bot",
      text: 'You have <strong>3 meetings</strong> tomorrow:<br><br>9:00 AM — Team standup<br>11:30 AM — Design review with Sarah<br>2:00 PM — Client call (Project Atlas)',
    },
    { role: "user", text: "Move the client call to Thursday" },
    {
      role: "bot",
      text: 'Done! Moved the Project Atlas call to <strong>Thursday 2:00 PM</strong> and sent an update to all participants.',
    },
  ];

  messages.forEach((msg) => {
    const outer = document.createElement("div");
    outer.className = `chat-msg chat-msg-${msg.role}`;
    const bubble = document.createElement("div");
    bubble.className = `msg-bubble msg-${msg.role}`;
    bubble.innerHTML = msg.text;
    outer.appendChild(bubble);
    container.appendChild(outer);
  });
}

// --- Nav scroll effect ---
function initNavScroll() {
  const nav = document.querySelector(".nav");
  if (!nav) return;

  let ticking = false;
  window.addEventListener("scroll", () => {
    if (!ticking) {
      requestAnimationFrame(() => {
        nav.classList.toggle("scrolled", window.scrollY > 50);
        ticking = false;
      });
      ticking = true;
    }
  });
}

// --- Initialize ---
document.addEventListener("DOMContentLoaded", () => {
  initHeroChat();
  initScrollAnimations();
  initNavScroll();

  const demoEl = document.getElementById("demo-messages");
  if (demoEl) {
    const demo = new ChatDemo(demoEl);

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            demo.start();
          } else {
            demo.stop();
          }
        });
      },
      { threshold: 0.3 },
    );

    observer.observe(document.querySelector(".demo-window"));
  }
});
