/* Birkin — Remote Control (Telegram + Slack + Discord) */

(function () {
  const B = window.birkin;
  const container = B.$("view-telegram");
  let initialized = false;
  let savedToken = "";
  let _activePlatform = "telegram";

  function t(k) { return B.t(k); }

  async function init() {
    if (initialized) { renderPlatformTabs(); return; }
    initialized = true;
    renderPlatformTabs();
  }

  function renderPlatformTabs() {
    container.innerHTML = "";
    const header = document.createElement("div");
    header.className = "rc-header";
    header.innerHTML = `
      <h2 class="rc-title">Remote Control</h2>
      <div class="rc-tabs">
        <button class="rc-tab ${_activePlatform === "telegram" ? "active" : ""}" data-platform="telegram">Telegram</button>
        <button class="rc-tab ${_activePlatform === "slack" ? "active" : ""}" data-platform="slack">Slack</button>
        <button class="rc-tab ${_activePlatform === "discord" ? "active" : ""}" data-platform="discord">Discord</button>
      </div>
    `;
    container.appendChild(header);

    header.querySelectorAll(".rc-tab").forEach((btn) => {
      btn.onclick = () => { _activePlatform = btn.dataset.platform; renderPlatformTabs(); };
    });

    const content = document.createElement("div");
    content.className = "rc-content";
    container.appendChild(content);

    if (_activePlatform === "telegram") renderTelegram(content);
    else if (_activePlatform === "slack") renderSlack(content);
    else if (_activePlatform === "discord") renderDiscord(content);
  }

  /* ── Slack ── */
  async function renderSlack(el) {
    let status = { configured: false };
    try { const r = await fetch("/api/remote/slack/status"); if (r.ok) status = await r.json(); } catch {}

    if (status.configured) {
      el.innerHTML = `<div class="tg-container"><div class="tg-dashboard">
        <div class="tg-dash-status"><span class="tg-status-dot connected"></span> Slack Connected</div>
        <p style="color:var(--text-dim);font-size:0.85rem;margin:12px 0">${status.channel ? "Channel: " + B.esc(status.channel) : "Default channel"}</p>
        <div style="display:flex;gap:8px;margin-top:12px">
          <button class="tg-btn" id="rc-slack-test">Send Test</button>
          <button class="tg-btn secondary" id="rc-slack-reconfig">Reconfigure</button>
        </div>
      </div></div>`;
      el.querySelector("#rc-slack-test").onclick = async () => {
        const r = await fetch("/api/remote/slack/test", { method: "POST" });
        const d = await r.json();
        alert(d.message);
      };
      el.querySelector("#rc-slack-reconfig").onclick = () => { renderSlackSetup(el); };
    } else {
      renderSlackSetup(el);
    }
  }

  function renderSlackSetup(el) {
    el.innerHTML = `<div class="tg-container">
      <div class="tg-header">
        <div class="tg-header-title">Connect Slack</div>
        <div class="tg-header-sub">Paste your Slack Incoming Webhook URL</div>
      </div>
      <div class="tg-steps">
        <div class="tg-step"><div class="tg-step-num">1</div><div class="tg-step-content">
          <div class="tg-step-title">Create Incoming Webhook</div>
          <div class="tg-step-desc">Go to <a href="https://api.slack.com/messaging/webhooks" target="_blank" style="color:var(--text)">Slack API → Incoming Webhooks</a> and create a new webhook for your workspace.</div>
        </div></div>
        <div class="tg-step"><div class="tg-step-num">2</div><div class="tg-step-content">
          <div class="tg-step-title">Paste Webhook URL</div>
          <div class="tg-step-desc"><input class="tg-input" id="rc-slack-url" placeholder="https://hooks.slack.com/services/T.../B.../xxx" /></div>
        </div></div>
        <div class="tg-step"><div class="tg-step-num">3</div><div class="tg-step-content">
          <div class="tg-step-title">Channel (optional)</div>
          <div class="tg-step-desc"><input class="tg-input" id="rc-slack-channel" placeholder="#general" /></div>
        </div></div>
      </div>
      <button class="tg-btn primary" id="rc-slack-save" style="margin-top:16px;width:100%">Connect Slack</button>
    </div>`;
    el.querySelector("#rc-slack-save").onclick = async () => {
      const url = el.querySelector("#rc-slack-url").value.trim();
      const channel = el.querySelector("#rc-slack-channel").value.trim();
      const r = await fetch("/api/remote/slack/configure", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ webhook_url: url, channel }),
      });
      const d = await r.json();
      if (d.status === "ok") renderSlack(el);
      else alert(d.message);
    };
  }

  /* ── Discord ── */
  async function renderDiscord(el) {
    let status = { configured: false };
    try { const r = await fetch("/api/remote/discord/status"); if (r.ok) status = await r.json(); } catch {}

    if (status.configured) {
      el.innerHTML = `<div class="tg-container"><div class="tg-dashboard">
        <div class="tg-dash-status"><span class="tg-status-dot connected"></span> Discord Connected</div>
        <p style="color:var(--text-dim);font-size:0.85rem;margin:12px 0">Bot name: ${B.esc(status.username || "Birkin")}</p>
        <div style="display:flex;gap:8px;margin-top:12px">
          <button class="tg-btn" id="rc-discord-test">Send Test</button>
          <button class="tg-btn secondary" id="rc-discord-reconfig">Reconfigure</button>
        </div>
      </div></div>`;
      el.querySelector("#rc-discord-test").onclick = async () => {
        const r = await fetch("/api/remote/discord/test", { method: "POST" });
        const d = await r.json();
        alert(d.message);
      };
      el.querySelector("#rc-discord-reconfig").onclick = () => { renderDiscordSetup(el); };
    } else {
      renderDiscordSetup(el);
    }
  }

  function renderDiscordSetup(el) {
    el.innerHTML = `<div class="tg-container">
      <div class="tg-header">
        <div class="tg-header-title">Connect Discord</div>
        <div class="tg-header-sub">Paste your Discord Webhook URL</div>
      </div>
      <div class="tg-steps">
        <div class="tg-step"><div class="tg-step-num">1</div><div class="tg-step-content">
          <div class="tg-step-title">Create Webhook</div>
          <div class="tg-step-desc">In your Discord server: Server Settings → Integrations → Webhooks → New Webhook</div>
        </div></div>
        <div class="tg-step"><div class="tg-step-num">2</div><div class="tg-step-content">
          <div class="tg-step-title">Copy Webhook URL</div>
          <div class="tg-step-desc"><input class="tg-input" id="rc-discord-url" placeholder="https://discord.com/api/webhooks/..." /></div>
        </div></div>
        <div class="tg-step"><div class="tg-step-num">3</div><div class="tg-step-content">
          <div class="tg-step-title">Bot Name (optional)</div>
          <div class="tg-step-desc"><input class="tg-input" id="rc-discord-name" placeholder="Birkin" value="Birkin" /></div>
        </div></div>
      </div>
      <button class="tg-btn primary" id="rc-discord-save" style="margin-top:16px;width:100%">Connect Discord</button>
    </div>`;
    el.querySelector("#rc-discord-save").onclick = async () => {
      const url = el.querySelector("#rc-discord-url").value.trim();
      const username = el.querySelector("#rc-discord-name").value.trim();
      const r = await fetch("/api/remote/discord/configure", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ webhook_url: url, username }),
      });
      const d = await r.json();
      if (d.status === "ok") renderDiscord(el);
      else alert(d.message);
    };
  }

  /* ── Telegram (existing) ── */
  function renderTelegram(el) {
    const wrap = document.createElement("div");
    wrap.className = "tg-container";
    renderTelegramContent(wrap);
    el.appendChild(wrap);
  }

  async function renderTelegramContent(wrap) {
    let status = { configured: false, polling: false };
    try {
      const res = await fetch("/api/telegram/status");
      if (res.ok) status = await res.json();
    } catch {}

    if (status.configured) {
      renderDashboard(wrap, status);
    } else {
      renderSetup(wrap);
    }
  }

  /* ── Simple Setup: Token → Auto Connect → Test ── */

  function renderSetup(wrap) {
    wrap.innerHTML = `
      <div class="tg-header">
        <div class="tg-header-icon">
          <svg width="56" height="56" viewBox="0 0 56 56" fill="none">
            <circle cx="28" cy="28" r="26" stroke="rgba(240,240,250,0.2)" stroke-width="1.5"/>
            <path d="M16 27l20-9-7 22-5-8-8-5z" stroke="rgba(240,240,250,0.5)" stroke-width="1.5" stroke-linejoin="round" fill="rgba(240,240,250,0.05)"/>
            <path d="M24 32l5-7" stroke="rgba(240,240,250,0.4)" stroke-width="1.5" stroke-linecap="round"/>
          </svg>
        </div>
        <div class="tg-header-title">${t("tg_connect")}</div>
        <div class="tg-header-sub">${t("tg_follow_steps")}</div>
      </div>

      <!-- Step 1: Get token from BotFather -->
      <div class="tg-step-card">
        <h3 class="tg-card-title">${t("tg_step1_title")}</h3>
        <div class="tg-instructions">
          <div class="tg-instruction"><span class="tg-inst-num">1</span><div class="tg-inst-text"><p>${t("tg_step1_1")}</p></div></div>
          <div class="tg-instruction"><span class="tg-inst-num">2</span><div class="tg-inst-text"><p>${t("tg_step1_2")}</p><p class="tg-hint">${t("tg_step1_2_hint")}</p></div></div>
          <div class="tg-instruction"><span class="tg-inst-num">3</span><div class="tg-inst-text"><p>${t("tg_step1_3")} <code>/newbot</code></p></div></div>
          <div class="tg-instruction"><span class="tg-inst-num">4</span><div class="tg-inst-text"><p>${t("tg_step1_5")}</p><div class="tg-token-example">123456789:ABCdefGHIjklMNOpqrsTUVwxyz</div></div></div>
        </div>
      </div>

      <!-- Step 2: Paste token + connect -->
      <div class="tg-step-card">
        <h3 class="tg-card-title">${t("tg_step2_title")}</h3>
        <div class="tg-token-input-wrap">
          <label class="tg-field-label">${t("tg_bot_token")}</label>
          <div class="tg-input-row">
            <input class="tg-input tg-input-lg" type="password" id="tg-token-input" placeholder="123456789:ABCdefGHI..." autocomplete="off" />
            <button class="tg-eye-btn" id="tg-toggle-vis" aria-label="${t("toggle_vis")}">&#128065;</button>
          </div>
        </div>
        <div class="tg-token-input-wrap">
          <label class="tg-field-label">Chat ID <span style="color:rgba(240,240,250,0.3)">(${t("tg_chatid_hint")})</span></label>
          <input class="tg-input tg-input-lg" type="text" id="tg-chatid-input" placeholder="${t("tg_chatid_placeholder")}" autocomplete="off" />
          <p class="tg-hint" style="margin-top:4px">${t("tg_chatid_how")}</p>
        </div>
        <div class="tg-token-feedback" id="tg-setup-feedback"></div>
        <div class="tg-step-actions">
          <button class="ghost-btn" id="tg-connect-btn">${t("tg_connect_btn")}</button>
        </div>
      </div>
    `;

    wrap.querySelector("#tg-toggle-vis").onclick = () => {
      const inp = wrap.querySelector("#tg-token-input");
      inp.type = inp.type === "password" ? "text" : "password";
    };

    wrap.querySelector("#tg-connect-btn").onclick = () => doConnect(wrap);
  }

  async function doConnect(wrap) {
    const token = wrap.querySelector("#tg-token-input").value.trim();
    const chatId = wrap.querySelector("#tg-chatid-input").value.trim();
    const fb = wrap.querySelector("#tg-setup-feedback");

    if (!token) { fb.textContent = t("tg_enter_token_ph"); fb.className = "tg-token-feedback error"; return; }
    if (!token.includes(":")) { fb.textContent = t("tg_invalid_format"); fb.className = "tg-token-feedback error"; return; }

    fb.textContent = t("tg_connecting"); fb.className = "tg-token-feedback loading";

    try {
      // 1. Save token
      const saveRes = await fetch("/api/settings/keys", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ TELEGRAM_BOT_TOKEN: token }),
      });
      if (!saveRes.ok) { fb.textContent = t("tg_save_failed"); fb.className = "tg-token-feedback error"; return; }

      // 2. Verify bot
      fb.textContent = t("tg_verifying"); fb.className = "tg-token-feedback loading";
      const statusRes = await fetch("/api/telegram/status");
      if (!statusRes.ok) { fb.textContent = t("tg_save_failed"); fb.className = "tg-token-feedback error"; return; }
      const statusData = await statusRes.json();

      if (!statusData.configured || !statusData.bot_info) {
        fb.textContent = t("tg_saved_not_verified"); fb.className = "tg-token-feedback warn";
        return;
      }

      const botName = statusData.bot_info.username || "bot";
      fb.innerHTML = `<span class="dot ok"></span> ${t("tg_verified")} @${B.esc(botName)}`;
      fb.className = "tg-token-feedback success";

      // 3. Start polling automatically
      fb.textContent = t("tg_starting_polling"); fb.className = "tg-token-feedback loading";
      await fetch("/api/telegram/polling/start", { method: "POST" });

      // 4. Send test message if chat_id provided
      if (chatId) {
        fb.textContent = t("tg_sending_test"); fb.className = "tg-token-feedback loading";
        const testRes = await fetch("/api/telegram/send-test", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chat_id: chatId }),
        });
        if (testRes.ok) {
          fb.innerHTML = `<span class="dot ok"></span> ${t("tg_all_done")}`;
          fb.className = "tg-token-feedback success";
        } else {
          const err = await testRes.json().catch(() => ({}));
          fb.innerHTML = `<span class="dot ok"></span> ${t("tg_polling_started")} <span style="color:#fbbf24">(${t("tg_test_failed")}: ${B.esc(err.detail || "?")})</span>`;
          fb.className = "tg-token-feedback success";
        }
      } else {
        fb.innerHTML = `<span class="dot ok"></span> ${t("tg_polling_started")}`;
        fb.className = "tg-token-feedback success";
      }

      // Re-render to dashboard after 2s
      setTimeout(render, 2000);

    } catch (e) {
      fb.textContent = t("tg_net_error"); fb.className = "tg-token-feedback error";
    }
  }

  /* ── Dashboard ── */

  function renderDashboard(wrap, status) {
    const bot = status.bot_info || {};
    const wh = status.webhook_info || {};
    const whUrl = wh.url || "";
    const hasWebhook = !!whUrl;
    const isActive = status.polling || hasWebhook;

    wrap.innerHTML = `
      <div class="tg-header">
        <div class="tg-header-icon">
          <svg width="56" height="56" viewBox="0 0 56 56" fill="none">
            <circle cx="28" cy="28" r="26" stroke="${isActive ? '#4ade80' : '#fbbf24'}" stroke-width="1.5"/>
            <path d="M16 27l20-9-7 22-5-8-8-5z" stroke="${isActive ? '#4ade80' : '#fbbf24'}" stroke-width="1.5" stroke-linejoin="round" fill="${isActive ? 'rgba(74,222,128,0.08)' : 'rgba(251,191,36,0.08)'}"/>
            <path d="M24 32l5-7" stroke="${isActive ? '#4ade80' : '#fbbf24'}" stroke-width="1.5" stroke-linecap="round"/>
          </svg>
        </div>
        <div class="tg-header-title">${isActive ? t("tg_connected") : t("tg_partial")}</div>
        <div class="tg-header-sub">@${B.esc(bot.username || 'unknown')}</div>
      </div>

      <div class="tg-status-card">
        <div class="tg-status-row"><span class="tg-status-label">${t("tg_status")}</span><span class="tg-status-value"><span class="dot" style="background:${isActive ? '#4ade80' : '#fbbf24'}"></span>${status.polling ? t("tg_polling_running") : hasWebhook ? t("tg_active") : t("tg_wh_not_set")}</span></div>
        <div class="tg-status-row"><span class="tg-status-label">${t("tg_bot")}</span><span class="tg-status-value">@${B.esc(bot.username || '?')}</span></div>
        <div class="tg-status-row"><span class="tg-status-label">${t("tg_name")}</span><span class="tg-status-value">${B.esc(bot.first_name || '')}</span></div>
        ${whUrl ? `<div class="tg-status-row"><span class="tg-status-label">${t("tg_webhook")}</span><span class="tg-status-value" style="word-break:break-all;font-size:0.75rem">${B.esc(whUrl)}</span></div>` : ''}
        ${wh.pending_update_count ? `<div class="tg-status-row"><span class="tg-status-label">${t("tg_pending")}</span><span class="tg-status-value">${wh.pending_update_count} ${t("tg_updates")}</span></div>` : ''}
        ${wh.last_error_message ? `<div class="tg-status-row"><span class="tg-status-label">${t("tg_error")}</span><span class="tg-status-value" style="color:#ef4444">${B.esc(wh.last_error_message)}</span></div>` : ''}
      </div>

      <!-- Quick test -->
      <div class="tg-step-card" style="margin-bottom:12px">
        <h3 class="tg-card-title">${t("tg_send_test_title")}</h3>
        <div class="tg-input-row">
          <input class="tg-input tg-input-lg" id="tg-dash-chatid" placeholder="Chat ID" />
          <button class="ghost-btn" id="tg-dash-test">${t("tg_send_test_btn")}</button>
        </div>
        <div class="tg-token-feedback" id="tg-dash-test-fb"></div>
      </div>

      <div class="tg-actions">
        ${status.polling
          ? `<button class="ghost-btn secondary" id="tg-dash-stop-poll">${t("tg_polling_stop")}</button>`
          : `<button class="ghost-btn" id="tg-dash-start-poll">${t("tg_polling_start")}</button>`
        }
        <button class="ghost-btn secondary" id="tg-dash-reconfig">${t("tg_reconfig")}</button>
        <button class="ghost-btn secondary" id="tg-dash-refresh">${t("refresh")}</button>
      </div>
    `;

    // Test message
    const testBtn = wrap.querySelector("#tg-dash-test");
    if (testBtn) {
      testBtn.onclick = async () => {
        const chatId = wrap.querySelector("#tg-dash-chatid").value.trim();
        const fb = wrap.querySelector("#tg-dash-test-fb");
        if (!chatId) { fb.textContent = t("tg_chatid_required"); fb.className = "tg-token-feedback error"; return; }
        fb.textContent = t("tg_sending_test"); fb.className = "tg-token-feedback loading";
        try {
          const res = await fetch("/api/telegram/send-test", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ chat_id: chatId }) });
          if (res.ok) { fb.innerHTML = `<span class="dot ok"></span> ${t("tg_test_sent")}`; fb.className = "tg-token-feedback success"; }
          else { const err = await res.json().catch(() => ({})); fb.textContent = err.detail || t("tg_failed"); fb.className = "tg-token-feedback error"; }
        } catch { fb.textContent = t("tg_net_error"); fb.className = "tg-token-feedback error"; }
      };
    }

    // Polling start/stop
    const startBtn = wrap.querySelector("#tg-dash-start-poll");
    if (startBtn) { startBtn.onclick = async () => { await fetch("/api/telegram/polling/start", { method: "POST" }); setTimeout(render, 500); }; }
    const stopBtn = wrap.querySelector("#tg-dash-stop-poll");
    if (stopBtn) { stopBtn.onclick = async () => { await fetch("/api/telegram/polling/stop", { method: "POST" }); setTimeout(render, 500); }; }

    // Reconfig
    const reconfigBtn = wrap.querySelector("#tg-dash-reconfig");
    if (reconfigBtn) { reconfigBtn.onclick = () => { initialized = false; init(); }; }

    // Refresh
    const refreshBtn = wrap.querySelector("#tg-dash-refresh");
    if (refreshBtn) { refreshBtn.onclick = renderPlatformTabs; }
  }

  B.viewHooks.telegram = { onActivate: init };
})();
