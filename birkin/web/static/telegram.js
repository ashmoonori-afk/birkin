/* Birkin — Telegram Integration Panel (i18n-enabled) */

(function () {
  const B = window.birkin;
  const container = B.$("view-telegram");
  let initialized = false;
  let currentStep = 1;
  let savedToken = "";

  function t(k) { return B.t(k); }

  async function init() {
    if (initialized) { await render(); return; }
    initialized = true;
    await render();
  }

  async function render() {
    container.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "tg-container";

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

  /* ── Wizard ── */

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
        <div class="tg-header-title">${t("tg_connect")}</div>
        <div class="tg-header-sub">${t("tg_follow_steps")}</div>
      </div>
      <div class="tg-progress">
        <div class="tg-progress-step active" data-step="1"><span class="tg-pnum">1</span><span class="tg-plabel">${t("tg_create_bot")}</span></div>
        <div class="tg-progress-line"></div>
        <div class="tg-progress-step" data-step="2"><span class="tg-pnum">2</span><span class="tg-plabel">${t("tg_enter_token")}</span></div>
        <div class="tg-progress-line"></div>
        <div class="tg-progress-step" data-step="3"><span class="tg-pnum">3</span><span class="tg-plabel">${t("tg_webhook")}</span></div>
        <div class="tg-progress-line"></div>
        <div class="tg-progress-step" data-step="4"><span class="tg-pnum">4</span><span class="tg-plabel">${t("tg_test")}</span></div>
      </div>
      <div class="tg-wizard" id="tg-wizard"></div>
    `;
    const wizardEl = wrap.querySelector("#tg-wizard");
    showStep(wrap, wizardEl, 1);
  }

  function showStep(wrap, wizardEl, step) {
    currentStep = step;
    wizardEl.innerHTML = "";
    wrap.querySelectorAll(".tg-progress-step").forEach((el) => {
      const s = parseInt(el.dataset.step);
      el.classList.remove("active", "complete");
      if (s < step) el.classList.add("complete");
      if (s === step) el.classList.add("active");
    });
    wrap.querySelectorAll(".tg-progress-line").forEach((el, i) => { el.classList.toggle("complete", i < step - 1); });

    if (step === 1) renderStep1(wrap, wizardEl);
    else if (step === 2) renderStep2(wrap, wizardEl);
    else if (step === 3) renderStep3(wrap, wizardEl);
    else if (step === 4) renderStep4(wrap, wizardEl);
  }

  function renderStep1(wrap, wizardEl) {
    wizardEl.innerHTML = `
      <div class="tg-step-card">
        <h3 class="tg-card-title">${t("tg_step1_title")}</h3>
        <div class="tg-instructions">
          <div class="tg-instruction"><span class="tg-inst-num">1</span><div class="tg-inst-text"><p>${t("tg_step1_1")}</p></div></div>
          <div class="tg-instruction"><span class="tg-inst-num">2</span><div class="tg-inst-text"><p>${t("tg_step1_2")}</p><p class="tg-hint">${t("tg_step1_2_hint")}</p></div></div>
          <div class="tg-instruction"><span class="tg-inst-num">3</span><div class="tg-inst-text"><p>${t("tg_step1_3")} <code>/newbot</code></p></div></div>
          <div class="tg-instruction"><span class="tg-inst-num">4</span><div class="tg-inst-text"><p>${t("tg_step1_4")}</p><p class="tg-hint">${t("tg_step1_4_hint")}</p></div></div>
          <div class="tg-instruction"><span class="tg-inst-num">5</span><div class="tg-inst-text"><p>${t("tg_step1_5")}</p><div class="tg-token-example">123456789:ABCdefGHIjklMNOpqrsTUVwxyz</div><p class="tg-hint">${t("tg_step1_5_hint")}</p></div></div>
        </div>
        <div class="tg-step-actions"><button class="ghost-btn" id="tg-next-1">${t("tg_have_token")}</button></div>
      </div>
    `;
    wizardEl.querySelector("#tg-next-1").onclick = () => showStep(wrap, wizardEl, 2);
  }

  function renderStep2(wrap, wizardEl) {
    wizardEl.innerHTML = `
      <div class="tg-step-card">
        <h3 class="tg-card-title">${t("tg_step2_title")}</h3>
        <p class="tg-card-desc">${t("tg_step2_desc")}</p>
        <div class="tg-token-input-wrap">
          <label class="tg-field-label">${t("tg_bot_token")}</label>
          <div class="tg-input-row">
            <input class="tg-input tg-input-lg" type="password" id="tg-token-input" placeholder="123456789:ABCdefGHI..." autocomplete="off" />
            <button class="tg-eye-btn" id="tg-toggle-vis" aria-label="${t("toggle_vis")}">&#128065;</button>
          </div>
          <div class="tg-token-feedback" id="tg-token-feedback"></div>
        </div>
        <div class="tg-step-actions">
          <button class="ghost-btn secondary" id="tg-back-2">&larr; ${t("back")}</button>
          <button class="ghost-btn" id="tg-save-token">${t("tg_save_verify")}</button>
        </div>
      </div>
    `;
    const tokenInput = wizardEl.querySelector("#tg-token-input");
    const feedback = wizardEl.querySelector("#tg-token-feedback");

    wizardEl.querySelector("#tg-toggle-vis").onclick = () => { tokenInput.type = tokenInput.type === "password" ? "text" : "password"; };
    wizardEl.querySelector("#tg-back-2").onclick = () => showStep(wrap, wizardEl, 1);

    wizardEl.querySelector("#tg-save-token").onclick = async () => {
      const token = tokenInput.value.trim();
      if (!token) { feedback.textContent = t("tg_enter_token_ph"); feedback.className = "tg-token-feedback error"; return; }
      if (!token.includes(":")) { feedback.textContent = t("tg_invalid_format"); feedback.className = "tg-token-feedback error"; return; }

      feedback.textContent = t("tg_saving"); feedback.className = "tg-token-feedback loading";

      try {
        const saveRes = await fetch("/api/settings/keys", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ TELEGRAM_BOT_TOKEN: token }) });
        if (!saveRes.ok) { feedback.textContent = t("tg_save_failed"); feedback.className = "tg-token-feedback error"; return; }

        const statusRes = await fetch("/api/telegram/status");
        if (statusRes.ok) {
          const sd = await statusRes.json();
          if (sd.configured && sd.bot_info) {
            savedToken = token;
            feedback.innerHTML = `<span class="dot ok"></span> ${t("tg_verified")} <strong>@${B.esc(sd.bot_info.username)}</strong>`;
            feedback.className = "tg-token-feedback success";
            setTimeout(() => showStep(wrap, wizardEl, 3), 1200);
            return;
          }
        }
        feedback.textContent = t("tg_saved_not_verified"); feedback.className = "tg-token-feedback warn";
        savedToken = token;
        setTimeout(() => showStep(wrap, wizardEl, 3), 2000);
      } catch {
        feedback.textContent = t("tg_net_error_saved"); feedback.className = "tg-token-feedback error";
        savedToken = token;
      }
    };
  }

  function renderStep3(wrap, wizardEl) {
    const suggestedUrl = `${window.location.origin}/api/webhooks/telegram/${savedToken}`;
    wizardEl.innerHTML = `
      <div class="tg-step-card">
        <h3 class="tg-card-title">${t("tg_step3_title")}</h3>
        <p class="tg-card-desc">${t("tg_step3_desc")}</p>
        <div class="tg-token-input-wrap">
          <label class="tg-field-label">${t("tg_webhook_url")}</label>
          <input class="tg-input tg-input-lg" type="text" id="tg-webhook-url" value="${B.esc(suggestedUrl)}" />
          <p class="tg-hint" style="margin-top:6px">${t("tg_webhook_hint")}</p>
        </div>
        <div class="tg-webhook-feedback" id="tg-webhook-feedback"></div>
        <div class="tg-step-actions">
          <button class="ghost-btn secondary" id="tg-back-3">&larr; ${t("back")}</button>
          <button class="ghost-btn" id="tg-register-wh">${t("tg_register")}</button>
          <button class="ghost-btn secondary" id="tg-skip-wh">${t("tg_skip_now")}</button>
        </div>
      </div>
    `;
    wizardEl.querySelector("#tg-back-3").onclick = () => showStep(wrap, wizardEl, 2);
    wizardEl.querySelector("#tg-skip-wh").onclick = () => showStep(wrap, wizardEl, 4);

    wizardEl.querySelector("#tg-register-wh").onclick = async () => {
      const url = wizardEl.querySelector("#tg-webhook-url").value.trim();
      const fb = wizardEl.querySelector("#tg-webhook-feedback");
      if (!url) { fb.textContent = t("tg_enter_url"); fb.className = "tg-webhook-feedback error"; return; }
      fb.textContent = t("tg_registering"); fb.className = "tg-webhook-feedback loading";
      try {
        const res = await fetch("/api/telegram/webhook", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ webhook_url: url }) });
        if (res.ok) {
          const data = await res.json();
          if (data.ok || data.result) {
            fb.innerHTML = `<span class="dot ok"></span> ${t("tg_webhook_success")}`;
            fb.className = "tg-webhook-feedback success";
            setTimeout(() => showStep(wrap, wizardEl, 4), 1000);
          } else { fb.textContent = data.description || t("tg_reg_failed"); fb.className = "tg-webhook-feedback error"; }
        } else { fb.textContent = t("tg_webhook_failed"); fb.className = "tg-webhook-feedback error"; }
      } catch { fb.textContent = t("tg_net_error"); fb.className = "tg-webhook-feedback error"; }
    };
  }

  function renderStep4(wrap, wizardEl) {
    wizardEl.innerHTML = `
      <div class="tg-step-card tg-complete-card">
        <div class="tg-complete-icon"><svg width="48" height="48" viewBox="0 0 48 48" fill="none"><circle cx="24" cy="24" r="22" stroke="#4ade80" stroke-width="2"/><path d="M14 24l7 7 13-14" stroke="#4ade80" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
        <h3 class="tg-card-title" style="color:#4ade80">${t("tg_complete")}</h3>
        <p class="tg-card-desc">${t("tg_complete_desc")}</p>
        <div class="tg-test-section" id="tg-test-section"><p class="tg-hint">${t("tg_loading_bot")}</p></div>
        <div class="tg-step-actions"><button class="ghost-btn" id="tg-go-dashboard">${t("tg_view_dashboard")}</button></div>
      </div>
    `;
    wizardEl.querySelector("#tg-go-dashboard").onclick = render;
    loadBotInfo(wizardEl.querySelector("#tg-test-section"));
  }

  async function loadBotInfo(section) {
    try {
      const res = await fetch("/api/telegram/status");
      if (!res.ok) { section.innerHTML = `<p class="tg-hint">${t("tg_no_bot_info")}</p>`; return; }
      const data = await res.json();
      const bot = data.bot_info || {};
      const wh = data.webhook_info || {};
      section.innerHTML = `
        <div class="tg-mini-card">
          <div class="tg-status-row"><span class="tg-status-label">${t("tg_bot")}</span><span class="tg-status-value">@${B.esc(bot.username || '?')}</span></div>
          <div class="tg-status-row"><span class="tg-status-label">${t("tg_name")}</span><span class="tg-status-value">${B.esc(bot.first_name || '?')}</span></div>
          <div class="tg-status-row"><span class="tg-status-label">${t("tg_webhook")}</span><span class="tg-status-value">${wh.url ? `<span class="dot ok"></span> ${t("tg_active")}` : `<span class="dot" style="background:#fbbf24"></span> ${t("tg_wh_not_set")}`}</span></div>
        </div>
      `;
    } catch { section.innerHTML = `<p class="tg-hint">${t("tg_no_bot_info")}</p>`; }
  }

  /* ── Dashboard ── */

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
        <div class="tg-header-title">${hasWebhook ? t("tg_connected") : t("tg_partial")}</div>
        <div class="tg-header-sub">@${B.esc(bot.username || 'unknown')}</div>
      </div>
      <div class="tg-status-card">
        <div class="tg-status-row"><span class="tg-status-label">${t("tg_status")}</span><span class="tg-status-value"><span class="dot" style="background:${hasWebhook ? '#4ade80' : '#fbbf24'}"></span>${hasWebhook ? t("tg_active") : t("tg_wh_not_set")}</span></div>
        <div class="tg-status-row"><span class="tg-status-label">${t("tg_bot")}</span><span class="tg-status-value">@${B.esc(bot.username || '?')}</span></div>
        <div class="tg-status-row"><span class="tg-status-label">${t("tg_name")}</span><span class="tg-status-value">${B.esc(bot.first_name || '')}</span></div>
        ${whUrl ? `<div class="tg-status-row"><span class="tg-status-label">${t("tg_webhook")}</span><span class="tg-status-value" style="word-break:break-all;font-size:0.75rem">${B.esc(whUrl)}</span></div>` : ''}
        ${wh.pending_update_count ? `<div class="tg-status-row"><span class="tg-status-label">${t("tg_pending")}</span><span class="tg-status-value">${wh.pending_update_count} ${t("tg_updates")}</span></div>` : ''}
        ${wh.last_error_message ? `<div class="tg-status-row"><span class="tg-status-label">${t("tg_error")}</span><span class="tg-status-value" style="color:#ef4444">${B.esc(wh.last_error_message)}</span></div>` : ''}
      </div>
      ${!hasWebhook ? `
        <div class="tg-step-card" style="margin-bottom:16px">
          <h3 class="tg-card-title">${t("tg_register")}</h3>
          <p class="tg-card-desc">${t("tg_no_wh")}</p>
          <div class="tg-input-row" style="margin-top:8px">
            <input class="tg-input tg-input-lg" id="tg-dash-wh-url" placeholder="https://..." />
            <button class="ghost-btn" id="tg-dash-register">${t("tg_register")}</button>
          </div>
          <div id="tg-dash-wh-feedback" class="tg-webhook-feedback"></div>
        </div>
      ` : ''}
      <div class="tg-actions">
        ${hasWebhook ? `<button class="ghost-btn secondary" id="tg-dash-remove">${t("tg_remove_wh")}</button>` : ''}
        <button class="ghost-btn secondary" id="tg-dash-reconfig">${t("tg_reconfig")}</button>
        <button class="ghost-btn secondary" id="tg-dash-refresh">${t("refresh")}</button>
      </div>
    `;

    const registerBtn = wrap.querySelector("#tg-dash-register");
    if (registerBtn) {
      registerBtn.onclick = async () => {
        const url = wrap.querySelector("#tg-dash-wh-url").value.trim();
        const fb = wrap.querySelector("#tg-dash-wh-feedback");
        if (!url) return;
        fb.textContent = t("tg_registering"); fb.className = "tg-webhook-feedback loading";
        try {
          await fetch("/api/telegram/webhook", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ webhook_url: url }) });
          fb.innerHTML = `<span class="dot ok"></span> ${t("tg_done")}`; fb.className = "tg-webhook-feedback success";
          setTimeout(render, 800);
        } catch { fb.textContent = t("tg_failed"); fb.className = "tg-webhook-feedback error"; }
      };
    }

    const removeBtn = wrap.querySelector("#tg-dash-remove");
    if (removeBtn) {
      removeBtn.onclick = async () => {
        if (!confirm(t("tg_remove_confirm"))) return;
        try { await fetch("/api/telegram/webhook", { method: "DELETE" }); } catch { /* */ }
        render();
      };
    }

    const reconfigBtn = wrap.querySelector("#tg-dash-reconfig");
    if (reconfigBtn) {
      reconfigBtn.onclick = () => {
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
