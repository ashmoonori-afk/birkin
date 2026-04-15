/* Birkin — Telegram Integration Panel (step-by-step interactive wizard) */

(function () {
  const B = window.birkin;
  const container = B.$("view-telegram");
  let initialized = false;
  let currentStep = 1;
  let savedToken = "";

  async function init() {
    if (initialized) { await render(); return; }
    initialized = true;
    await render();
  }

  async function render() {
    container.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "tg-container";

    // Fetch status
    let status = { configured: false };
    try {
      const res = await fetch("/api/telegram/status");
      if (res.ok) status = await res.json();
    } catch { /* */ }

    if (status.configured) {
      renderDashboard(wrap, status);
    } else {
      renderFullWizard(wrap);
    }

    container.appendChild(wrap);
  }

  /* ── Full Step-by-Step Wizard ── */

  function renderFullWizard(wrap) {
    currentStep = 1;

    wrap.innerHTML = `
      <div class="tg-header">
        <div class="tg-header-icon">
          <svg width="56" height="56" viewBox="0 0 56 56" fill="none">
            <circle cx="28" cy="28" r="26" stroke="rgba(240,240,250,0.2)" stroke-width="1.5"/>
            <path d="M16 27l20-9-7 22-5-8-8-5z" stroke="rgba(240,240,250,0.5)" stroke-width="1.5" stroke-linejoin="round" fill="rgba(240,240,250,0.05)"/>
            <path d="M24 32l5-7" stroke="rgba(240,240,250,0.4)" stroke-width="1.5" stroke-linecap="round"/>
          </svg>
        </div>
        <div class="tg-header-title">Connect Telegram</div>
        <div class="tg-header-sub">Follow these steps to link a Telegram bot to Birkin</div>
      </div>

      <!-- Progress bar -->
      <div class="tg-progress">
        <div class="tg-progress-step active" data-step="1"><span class="tg-pnum">1</span><span class="tg-plabel">Create Bot</span></div>
        <div class="tg-progress-line"></div>
        <div class="tg-progress-step" data-step="2"><span class="tg-pnum">2</span><span class="tg-plabel">Enter Token</span></div>
        <div class="tg-progress-line"></div>
        <div class="tg-progress-step" data-step="3"><span class="tg-pnum">3</span><span class="tg-plabel">Webhook</span></div>
        <div class="tg-progress-line"></div>
        <div class="tg-progress-step" data-step="4"><span class="tg-pnum">4</span><span class="tg-plabel">Test</span></div>
      </div>

      <!-- Step panels -->
      <div class="tg-wizard" id="tg-wizard"></div>
    `;

    const wizardEl = wrap.querySelector("#tg-wizard");
    showStep(wrap, wizardEl, 1);
  }

  function showStep(wrap, wizardEl, step) {
    currentStep = step;
    wizardEl.innerHTML = "";

    // Update progress bar
    wrap.querySelectorAll(".tg-progress-step").forEach((el) => {
      const s = parseInt(el.dataset.step);
      el.classList.remove("active", "complete");
      if (s < step) el.classList.add("complete");
      if (s === step) el.classList.add("active");
    });
    wrap.querySelectorAll(".tg-progress-line").forEach((el, i) => {
      el.classList.toggle("complete", i < step - 1);
    });

    if (step === 1) renderStep1(wrap, wizardEl);
    else if (step === 2) renderStep2(wrap, wizardEl);
    else if (step === 3) renderStep3(wrap, wizardEl);
    else if (step === 4) renderStep4(wrap, wizardEl);
  }

  /* ── Step 1: Create a Bot ── */

  function renderStep1(wrap, wizardEl) {
    wizardEl.innerHTML = `
      <div class="tg-step-card">
        <h3 class="tg-card-title">Step 1: Create a Telegram Bot</h3>

        <div class="tg-instructions">
          <div class="tg-instruction">
            <span class="tg-inst-num">1</span>
            <div class="tg-inst-text">
              <p>Open the <strong>Telegram</strong> app on your phone or desktop.</p>
            </div>
          </div>

          <div class="tg-instruction">
            <span class="tg-inst-num">2</span>
            <div class="tg-inst-text">
              <p>Search for <code>@BotFather</code> and start a conversation.</p>
              <p class="tg-hint">BotFather is Telegram's official bot for creating other bots.</p>
            </div>
          </div>

          <div class="tg-instruction">
            <span class="tg-inst-num">3</span>
            <div class="tg-inst-text">
              <p>Send the command: <code>/newbot</code></p>
            </div>
          </div>

          <div class="tg-instruction">
            <span class="tg-inst-num">4</span>
            <div class="tg-inst-text">
              <p>BotFather will ask for a <strong>name</strong> and <strong>username</strong> for your bot.</p>
              <p class="tg-hint">Username must end in "bot" (e.g., <code>mybirkin_bot</code>)</p>
            </div>
          </div>

          <div class="tg-instruction">
            <span class="tg-inst-num">5</span>
            <div class="tg-inst-text">
              <p>BotFather will give you a <strong>bot token</strong> like:</p>
              <div class="tg-token-example">123456789:ABCdefGHIjklMNOpqrsTUVwxyz</div>
              <p class="tg-hint">Copy this token. You'll paste it in the next step.</p>
            </div>
          </div>
        </div>

        <div class="tg-step-actions">
          <button class="ghost-btn" id="tg-next-1">I have my token &rarr;</button>
        </div>
      </div>
    `;

    wizardEl.querySelector("#tg-next-1").onclick = () => showStep(wrap, wizardEl, 2);
  }

  /* ── Step 2: Enter Token ── */

  function renderStep2(wrap, wizardEl) {
    wizardEl.innerHTML = `
      <div class="tg-step-card">
        <h3 class="tg-card-title">Step 2: Enter Your Bot Token</h3>
        <p class="tg-card-desc">Paste the token you received from BotFather below. It will be saved securely to your local <code>.env</code> file.</p>

        <div class="tg-token-input-wrap">
          <label class="tg-field-label">Bot Token</label>
          <div class="tg-input-row">
            <input class="tg-input tg-input-lg" type="password" id="tg-token-input" placeholder="123456789:ABCdefGHI..." autocomplete="off" />
            <button class="tg-eye-btn" id="tg-toggle-vis" aria-label="Show/hide token">&#128065;</button>
          </div>
          <div class="tg-token-feedback" id="tg-token-feedback"></div>
        </div>

        <div class="tg-step-actions">
          <button class="ghost-btn secondary" id="tg-back-2">&larr; Back</button>
          <button class="ghost-btn" id="tg-save-token">Save &amp; Verify</button>
        </div>
      </div>
    `;

    const tokenInput = wizardEl.querySelector("#tg-token-input");
    const feedback = wizardEl.querySelector("#tg-token-feedback");

    wizardEl.querySelector("#tg-toggle-vis").onclick = () => {
      tokenInput.type = tokenInput.type === "password" ? "text" : "password";
    };

    wizardEl.querySelector("#tg-back-2").onclick = () => showStep(wrap, wizardEl, 1);

    wizardEl.querySelector("#tg-save-token").onclick = async () => {
      const token = tokenInput.value.trim();
      if (!token) { feedback.textContent = "Please enter a token."; feedback.className = "tg-token-feedback error"; return; }
      if (!token.includes(":")) { feedback.textContent = "Invalid format. Token should contain a colon (:)."; feedback.className = "tg-token-feedback error"; return; }

      feedback.textContent = "Saving and verifying...";
      feedback.className = "tg-token-feedback loading";

      try {
        // Save token to .env
        const saveRes = await fetch("/api/settings/keys", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ TELEGRAM_BOT_TOKEN: token }),
        });

        if (!saveRes.ok) {
          feedback.textContent = "Failed to save token.";
          feedback.className = "tg-token-feedback error";
          return;
        }

        // Verify by fetching bot info
        const statusRes = await fetch("/api/telegram/status");
        if (statusRes.ok) {
          const statusData = await statusRes.json();
          if (statusData.configured && statusData.bot_info) {
            savedToken = token;
            feedback.innerHTML = `<span class="dot ok"></span> Verified: <strong>@${B.esc(statusData.bot_info.username)}</strong> (${B.esc(statusData.bot_info.first_name)})`;
            feedback.className = "tg-token-feedback success";

            // Auto-advance after 1s
            setTimeout(() => showStep(wrap, wizardEl, 3), 1200);
            return;
          }
        }

        feedback.textContent = "Token saved but could not verify. Check if the token is correct.";
        feedback.className = "tg-token-feedback warn";
        savedToken = token;

        // Still allow proceeding
        setTimeout(() => showStep(wrap, wizardEl, 3), 2000);
      } catch {
        feedback.textContent = "Network error. Token may have been saved — try proceeding.";
        feedback.className = "tg-token-feedback error";
        savedToken = token;
      }
    };
  }

  /* ── Step 3: Webhook ── */

  function renderStep3(wrap, wizardEl) {
    const suggestedUrl = `${window.location.origin}/api/webhooks/telegram/${savedToken}`;

    wizardEl.innerHTML = `
      <div class="tg-step-card">
        <h3 class="tg-card-title">Step 3: Register Webhook</h3>
        <p class="tg-card-desc">Telegram needs a public URL to send messages to your Birkin server. If you're running locally, you can skip this step and use polling instead.</p>

        <div class="tg-token-input-wrap">
          <label class="tg-field-label">Webhook URL</label>
          <input class="tg-input tg-input-lg" type="text" id="tg-webhook-url" value="${B.esc(suggestedUrl)}" />
          <p class="tg-hint" style="margin-top:6px">This URL must be publicly accessible (HTTPS). For local development, use a tunnel like <code>ngrok</code>.</p>
        </div>

        <div class="tg-webhook-feedback" id="tg-webhook-feedback"></div>

        <div class="tg-step-actions">
          <button class="ghost-btn secondary" id="tg-back-3">&larr; Back</button>
          <button class="ghost-btn" id="tg-register-wh">Register Webhook</button>
          <button class="ghost-btn secondary" id="tg-skip-wh">Skip for now</button>
        </div>
      </div>
    `;

    wizardEl.querySelector("#tg-back-3").onclick = () => showStep(wrap, wizardEl, 2);
    wizardEl.querySelector("#tg-skip-wh").onclick = () => showStep(wrap, wizardEl, 4);

    wizardEl.querySelector("#tg-register-wh").onclick = async () => {
      const url = wizardEl.querySelector("#tg-webhook-url").value.trim();
      const feedback = wizardEl.querySelector("#tg-webhook-feedback");
      if (!url) { feedback.textContent = "Please enter a URL."; feedback.className = "tg-webhook-feedback error"; return; }

      feedback.textContent = "Registering...";
      feedback.className = "tg-webhook-feedback loading";

      try {
        const res = await fetch("/api/telegram/webhook", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ webhook_url: url }),
        });

        if (res.ok) {
          const data = await res.json();
          if (data.ok || data.result) {
            feedback.innerHTML = '<span class="dot ok"></span> Webhook registered successfully!';
            feedback.className = "tg-webhook-feedback success";
            setTimeout(() => showStep(wrap, wizardEl, 4), 1000);
          } else {
            feedback.textContent = data.description || "Registration failed.";
            feedback.className = "tg-webhook-feedback error";
          }
        } else {
          feedback.textContent = "Failed to register webhook.";
          feedback.className = "tg-webhook-feedback error";
        }
      } catch {
        feedback.textContent = "Network error.";
        feedback.className = "tg-webhook-feedback error";
      }
    };
  }

  /* ── Step 4: Complete / Test ── */

  function renderStep4(wrap, wizardEl) {
    wizardEl.innerHTML = `
      <div class="tg-step-card tg-complete-card">
        <div class="tg-complete-icon">
          <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
            <circle cx="24" cy="24" r="22" stroke="#4ade80" stroke-width="2"/>
            <path d="M14 24l7 7 13-14" stroke="#4ade80" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
        <h3 class="tg-card-title" style="color:#4ade80">Setup Complete</h3>
        <p class="tg-card-desc">Your Telegram bot is connected to Birkin. Send a message to your bot in Telegram to test it!</p>

        <div class="tg-test-section" id="tg-test-section">
          <p class="tg-hint">Loading bot info...</p>
        </div>

        <div class="tg-step-actions">
          <button class="ghost-btn" id="tg-go-dashboard">View Dashboard</button>
        </div>
      </div>
    `;

    wizardEl.querySelector("#tg-go-dashboard").onclick = render;

    // Load and show bot info
    loadBotInfo(wizardEl.querySelector("#tg-test-section"));
  }

  async function loadBotInfo(section) {
    try {
      const res = await fetch("/api/telegram/status");
      if (!res.ok) { section.innerHTML = '<p class="tg-hint">Could not load bot info.</p>'; return; }
      const data = await res.json();
      const bot = data.bot_info || {};
      const wh = data.webhook_info || {};

      section.innerHTML = `
        <div class="tg-mini-card">
          <div class="tg-status-row"><span class="tg-status-label">Bot</span><span class="tg-status-value">@${B.esc(bot.username || '?')}</span></div>
          <div class="tg-status-row"><span class="tg-status-label">Name</span><span class="tg-status-value">${B.esc(bot.first_name || '?')}</span></div>
          <div class="tg-status-row"><span class="tg-status-label">Webhook</span><span class="tg-status-value">${wh.url ? '<span class="dot ok"></span> Active' : '<span class="dot" style="background:#fbbf24"></span> Not set'}</span></div>
        </div>
      `;
    } catch {
      section.innerHTML = '<p class="tg-hint">Could not load bot info.</p>';
    }
  }

  /* ── Dashboard (already configured) ── */

  function renderDashboard(wrap, status) {
    const bot = status.bot_info || {};
    const wh = status.webhook_info || {};
    const whUrl = wh.url || "";
    const hasWebhook = !!whUrl;

    wrap.innerHTML = `
      <div class="tg-header">
        <div class="tg-header-icon">
          <svg width="56" height="56" viewBox="0 0 56 56" fill="none">
            <circle cx="28" cy="28" r="26" stroke="${hasWebhook ? '#4ade80' : '#fbbf24'}" stroke-width="1.5"/>
            <path d="M16 27l20-9-7 22-5-8-8-5z" stroke="${hasWebhook ? '#4ade80' : '#fbbf24'}" stroke-width="1.5" stroke-linejoin="round" fill="${hasWebhook ? 'rgba(74,222,128,0.08)' : 'rgba(251,191,36,0.08)'}"/>
            <path d="M24 32l5-7" stroke="${hasWebhook ? '#4ade80' : '#fbbf24'}" stroke-width="1.5" stroke-linecap="round"/>
          </svg>
        </div>
        <div class="tg-header-title">${hasWebhook ? 'Connected' : 'Partially Configured'}</div>
        <div class="tg-header-sub">@${B.esc(bot.username || 'unknown')}</div>
      </div>

      <div class="tg-status-card">
        <div class="tg-status-row">
          <span class="tg-status-label">Status</span>
          <span class="tg-status-value"><span class="dot" style="background:${hasWebhook ? '#4ade80' : '#fbbf24'}"></span>${hasWebhook ? 'Active' : 'Webhook not set'}</span>
        </div>
        <div class="tg-status-row">
          <span class="tg-status-label">Bot</span>
          <span class="tg-status-value">@${B.esc(bot.username || '?')}</span>
        </div>
        <div class="tg-status-row">
          <span class="tg-status-label">Name</span>
          <span class="tg-status-value">${B.esc(bot.first_name || '')}</span>
        </div>
        ${whUrl ? `
          <div class="tg-status-row">
            <span class="tg-status-label">Webhook</span>
            <span class="tg-status-value" style="word-break:break-all;font-size:0.75rem">${B.esc(whUrl)}</span>
          </div>
        ` : ''}
        ${wh.pending_update_count ? `
          <div class="tg-status-row">
            <span class="tg-status-label">Pending</span>
            <span class="tg-status-value">${wh.pending_update_count} updates</span>
          </div>
        ` : ''}
        ${wh.last_error_message ? `
          <div class="tg-status-row">
            <span class="tg-status-label">Error</span>
            <span class="tg-status-value" style="color:#ef4444">${B.esc(wh.last_error_message)}</span>
          </div>
        ` : ''}
      </div>

      ${!hasWebhook ? `
        <div class="tg-step-card" style="margin-bottom:16px">
          <h3 class="tg-card-title">Register Webhook</h3>
          <p class="tg-card-desc">Your token is saved but no webhook is registered.</p>
          <div class="tg-input-row" style="margin-top:8px">
            <input class="tg-input tg-input-lg" id="tg-dash-wh-url" placeholder="https://your-domain.com/api/webhooks/telegram/TOKEN" />
            <button class="ghost-btn" id="tg-dash-register">Register</button>
          </div>
          <div id="tg-dash-wh-feedback" class="tg-webhook-feedback"></div>
        </div>
      ` : ''}

      <div class="tg-actions">
        ${hasWebhook ? '<button class="ghost-btn secondary" id="tg-dash-remove">Remove Webhook</button>' : ''}
        <button class="ghost-btn secondary" id="tg-dash-reconfig">Reconfigure</button>
        <button class="ghost-btn secondary" id="tg-dash-refresh">Refresh</button>
      </div>
    `;

    // Wire dashboard events
    const registerBtn = wrap.querySelector("#tg-dash-register");
    if (registerBtn) {
      registerBtn.onclick = async () => {
        const url = wrap.querySelector("#tg-dash-wh-url").value.trim();
        const fb = wrap.querySelector("#tg-dash-wh-feedback");
        if (!url) return;
        fb.textContent = "Registering..."; fb.className = "tg-webhook-feedback loading";
        try {
          await fetch("/api/telegram/webhook", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ webhook_url: url }) });
          fb.innerHTML = '<span class="dot ok"></span> Done!'; fb.className = "tg-webhook-feedback success";
          setTimeout(render, 800);
        } catch { fb.textContent = "Failed."; fb.className = "tg-webhook-feedback error"; }
      };
    }

    const removeBtn = wrap.querySelector("#tg-dash-remove");
    if (removeBtn) {
      removeBtn.onclick = async () => {
        if (!confirm("Remove the webhook?")) return;
        try { await fetch("/api/telegram/webhook", { method: "DELETE" }); } catch { /* */ }
        render();
      };
    }

    const reconfigBtn = wrap.querySelector("#tg-dash-reconfig");
    if (reconfigBtn) {
      reconfigBtn.onclick = () => {
        // Reset and show wizard
        container.innerHTML = "";
        const w = document.createElement("div");
        w.className = "tg-container";
        renderFullWizard(w);
        container.appendChild(w);
      };
    }

    const refreshBtn = wrap.querySelector("#tg-dash-refresh");
    if (refreshBtn) refreshBtn.onclick = render;
  }

  B.viewHooks.telegram = { onActivate: init };
})();
