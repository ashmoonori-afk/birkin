/* Birkin — Telegram Integration Panel */

(function () {
  const B = window.birkin;
  const container = B.$("view-telegram");
  let initialized = false;

  async function init() {
    if (initialized) { await render(); return; }
    initialized = true;
    await render();
  }

  async function render() {
    container.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "tg-container";

    // Header
    wrap.innerHTML = `
      <div class="tg-header">
        <div class="tg-header-icon">\u2708</div>
        <div class="tg-header-title">Telegram Integration</div>
        <div class="tg-header-sub">Connect a Telegram bot to chat with Birkin</div>
      </div>
    `;

    // Fetch status
    let status = { configured: false };
    try {
      const res = await fetch("/api/telegram/status");
      if (res.ok) status = await res.json();
    } catch { /* */ }

    if (status.configured) {
      renderConnected(wrap, status);
    } else {
      renderWizard(wrap);
    }

    container.appendChild(wrap);
  }

  function renderConnected(wrap, status) {
    const bot = status.bot_info || {};
    const wh = status.webhook_info || {};
    const whUrl = wh.url || "";
    const hasWebhook = !!whUrl;

    const card = document.createElement("div");
    card.innerHTML = `
      <div class="tg-status-card">
        <div class="tg-status-row">
          <span class="tg-status-label">Status</span>
          <span class="tg-status-value"><span class="dot" style="background:${hasWebhook ? '#4ade80' : '#fbbf24'}"></span>${hasWebhook ? 'Connected' : 'Token set, webhook not registered'}</span>
        </div>
        <div class="tg-status-row">
          <span class="tg-status-label">Bot</span>
          <span class="tg-status-value">@${B.esc(bot.username || 'unknown')}</span>
        </div>
        <div class="tg-status-row">
          <span class="tg-status-label">Name</span>
          <span class="tg-status-value">${B.esc(bot.first_name || '')}</span>
        </div>
        ${whUrl ? `<div class="tg-status-row"><span class="tg-status-label">Webhook</span><span class="tg-status-value" style="word-break:break-all;font-size:0.75rem">${B.esc(whUrl)}</span></div>` : ''}
        ${wh.pending_update_count ? `<div class="tg-status-row"><span class="tg-status-label">Pending</span><span class="tg-status-value">${wh.pending_update_count} updates</span></div>` : ''}
        ${wh.last_error_message ? `<div class="tg-status-row"><span class="tg-status-label">Last Error</span><span class="tg-status-value" style="color:#ef4444">${B.esc(wh.last_error_message)}</span></div>` : ''}
      </div>

      ${!hasWebhook ? `
        <div class="tg-step active">
          <div class="tg-step-header"><span class="tg-step-num">!</span><span class="tg-step-title">Register Webhook</span></div>
          <div class="tg-step-body">
            <p>Your bot token is set but webhook is not registered.</p>
            <div class="tg-input-row">
              <input class="tg-input" id="tg-webhook-url" placeholder="https://your-domain.com/api/webhooks/telegram/TOKEN" />
              <button class="ghost-btn" id="tg-register-btn">Register</button>
            </div>
          </div>
        </div>
      ` : ''}

      <div class="tg-actions">
        ${hasWebhook ? '<button class="ghost-btn secondary" id="tg-remove-webhook">Remove Webhook</button>' : ''}
        <button class="ghost-btn secondary" id="tg-refresh-btn">Refresh</button>
      </div>
    `;

    wrap.appendChild(card);

    // Wire events
    const registerBtn = card.querySelector("#tg-register-btn");
    if (registerBtn) {
      registerBtn.onclick = async () => {
        const url = card.querySelector("#tg-webhook-url").value.trim();
        if (!url) return;
        try {
          await fetch("/api/telegram/webhook", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ webhook_url: url }) });
        } catch { /* */ }
        render();
      };
    }

    const removeBtn = card.querySelector("#tg-remove-webhook");
    if (removeBtn) {
      removeBtn.onclick = async () => {
        try { await fetch("/api/telegram/webhook", { method: "DELETE" }); } catch { /* */ }
        render();
      };
    }

    const refreshBtn = card.querySelector("#tg-refresh-btn");
    if (refreshBtn) refreshBtn.onclick = render;
  }

  function renderWizard(wrap) {
    const wizard = document.createElement("div");
    wizard.className = "tg-wizard";
    wizard.innerHTML = `
      <div class="tg-step active" id="tg-step-1">
        <div class="tg-step-header">
          <span class="tg-step-num">1</span>
          <span class="tg-step-title">Create a Bot</span>
        </div>
        <div class="tg-step-body">
          <p>Open Telegram and message <code>@BotFather</code>.</p>
          <p>Send <code>/newbot</code> and follow the prompts to create a new bot.</p>
          <p>BotFather will give you a bot token like: <code>123456:ABC-DEF...</code></p>
        </div>
      </div>

      <div class="tg-step" id="tg-step-2">
        <div class="tg-step-header">
          <span class="tg-step-num">2</span>
          <span class="tg-step-title">Set Bot Token</span>
        </div>
        <div class="tg-step-body">
          <p>Paste your bot token below:</p>
          <div class="tg-input-row">
            <input class="tg-input" type="password" id="tg-token-input" placeholder="123456:ABC-DEF..." />
            <button class="ghost-btn" id="tg-save-token">Save</button>
          </div>
        </div>
      </div>

      <div class="tg-step" id="tg-step-3">
        <div class="tg-step-header">
          <span class="tg-step-num">3</span>
          <span class="tg-step-title">Set Webhook URL</span>
        </div>
        <div class="tg-step-body">
          <p>Register a public URL where Telegram will send messages:</p>
          <div class="tg-input-row">
            <input class="tg-input" id="tg-webhook-input" placeholder="https://your-domain.com/api/webhooks/telegram/TOKEN" />
            <button class="ghost-btn" id="tg-register-webhook">Register</button>
          </div>
          <p style="margin-top:8px;font-size:0.78rem;color:rgba(240,240,250,0.35)">Your server must be publicly accessible for Telegram to reach it.</p>
        </div>
      </div>
    `;

    wrap.appendChild(wizard);

    // Step 2: Save token
    wizard.querySelector("#tg-save-token").onclick = async () => {
      const token = wizard.querySelector("#tg-token-input").value.trim();
      if (!token) return;
      try {
        await fetch("/api/settings/keys", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ TELEGRAM_BOT_TOKEN: token }),
        });
        wizard.querySelector("#tg-step-1").classList.remove("active");
        wizard.querySelector("#tg-step-1").classList.add("complete");
        wizard.querySelector("#tg-step-2").classList.remove("active");
        wizard.querySelector("#tg-step-2").classList.add("complete");
        wizard.querySelector("#tg-step-3").classList.add("active");

        // Pre-fill webhook URL
        const whInput = wizard.querySelector("#tg-webhook-input");
        whInput.value = `${window.location.origin}/api/webhooks/telegram/${token}`;
      } catch { /* */ }
    };

    // Step 3: Register webhook
    wizard.querySelector("#tg-register-webhook").onclick = async () => {
      const url = wizard.querySelector("#tg-webhook-input").value.trim();
      if (!url) return;
      try {
        await fetch("/api/telegram/webhook", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ webhook_url: url }),
        });
        wizard.querySelector("#tg-step-3").classList.remove("active");
        wizard.querySelector("#tg-step-3").classList.add("complete");
        // Re-render with connected status
        setTimeout(render, 500);
      } catch { /* */ }
    };
  }

  B.viewHooks.telegram = { onActivate: init };
})();
