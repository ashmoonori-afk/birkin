/* Birkin Workflow — Main entry point + chat recommendation
 *
 * Module structure (load order matters):
 *   1. workflow-state.js    — shared state, palette, constants
 *   2. workflow-canvas.js   — drawing functions
 *   3. workflow-events.js   — mouse/keyboard handlers
 *   4. workflow-config.js   — config panel, save/load, samples
 *   5. workflow.js          — init + chat recommendation (this file)
 */

(function () {
  const B = window.birkin;
  const S = B._wf;

  /* ── Palette rendering ── */

  function buildPaletteList(el, filter) {
    el.innerHTML = "";
    S.getPalette().forEach((group) => {
      const items = group.items.filter((it) => !filter || it.label.toLowerCase().includes(filter) || it.type.includes(filter));
      if (!items.length) return;
      const gDiv = document.createElement("div");
      gDiv.className = "wf-palette-group";
      gDiv.innerHTML = `<div class="wf-palette-group-title">${group.group}</div>`;
      items.forEach((it) => {
        const item = document.createElement("div");
        item.className = "wf-palette-item";
        item.dataset.type = it.type;
        item.innerHTML = `<span class="wf-palette-icon ${it.color}">${it.icon}</span><span class="wf-palette-label">${it.label}</span>`;
        item.title = it.desc;
        gDiv.appendChild(item);
      });
      el.appendChild(gDiv);
    });
  }

  /* ── Init ── */

  function init() {
    if (S.initialized) return;
    S.initialized = true;

    S.container.innerHTML = "";
    const editor = document.createElement("div");
    editor.className = "wf-editor";

    // Palette
    const palette = document.createElement("div");
    palette.className = "wf-palette";
    const t = B.t;
    palette.innerHTML = `<div class="wf-palette-header">${t("node_palette")}</div><input class="wf-palette-search" placeholder="${t("search_nodes")}" id="wf-pal-search" />`;
    const palList = document.createElement("div");
    palList.className = "wf-palette-list";
    palList.id = "wf-pal-list";
    buildPaletteList(palList, "");
    palette.appendChild(palList);
    editor.appendChild(palette);

    // Canvas area
    const canvasArea = document.createElement("div");
    canvasArea.className = "wf-canvas-area";
    canvasArea.innerHTML = `
      <div class="wf-toolbar">
        <span class="wf-toolbar-title" id="wf-title">Untitled Workflow</span>
        <button class="wf-tb-btn" id="wf-btn-suggest" style="color:#c084fc">\u{1F4A1} Suggest</button>
        <button class="wf-tb-btn" id="wf-btn-samples">Samples</button>
        <button class="wf-tb-btn" id="wf-btn-save">Save</button>
        <button class="wf-tb-btn" id="wf-btn-load">Load</button>
        <button class="wf-tb-btn" id="wf-btn-activate">Activate</button>
        <button class="wf-tb-btn" id="wf-btn-clear">Clear</button>
      </div>
    `;

    const canvasWrap = document.createElement("div");
    canvasWrap.className = "wf-canvas-wrap";
    S.canvas = document.createElement("canvas");
    canvasWrap.appendChild(S.canvas);

    S.samplesPanel = document.createElement("div");
    S.samplesPanel.className = "wf-samples";
    S.samplesPanel.id = "wf-samples-panel";
    canvasWrap.appendChild(S.samplesPanel);

    S.configPanel = document.createElement("div");
    S.configPanel.className = "wf-config";
    S.configPanel.id = "wf-config-panel";
    canvasWrap.appendChild(S.configPanel);

    // Suggestions panel
    S.suggestionsPanel = document.createElement("div");
    S.suggestionsPanel.className = "wf-suggestions";
    S.suggestionsPanel.id = "wf-suggestions-panel";
    S.suggestionsPanel.style.display = "none";
    canvasWrap.appendChild(S.suggestionsPanel);

    canvasArea.appendChild(canvasWrap);
    editor.appendChild(canvasArea);
    S.container.appendChild(editor);

    S.ctx = S.canvas.getContext("2d");

    // Wire events
    palette.querySelector("#wf-pal-search").oninput = (e) => buildPaletteList(palList, e.target.value.toLowerCase());
    canvasArea.querySelector("#wf-btn-suggest").onclick = toggleSuggestions;
    canvasArea.querySelector("#wf-btn-samples").onclick = S.toggleSamples;
    canvasArea.querySelector("#wf-btn-save").onclick = S.saveCurrentWorkflow;
    canvasArea.querySelector("#wf-btn-load").onclick = S.toggleSamples;
    canvasArea.querySelector("#wf-btn-clear").onclick = S.clearCanvas;
    S.updateActivateButton();

    S.canvas.onmousedown = S.onCanvasMouseDown;
    S.canvas.onmousemove = S.onCanvasMouseMove;
    S.canvas.onmouseup = S.onCanvasMouseUp;
    S.canvas.ondblclick = S.onCanvasDblClick;
    S.canvas.onwheel = S.onCanvasWheel;
    S.canvas.oncontextmenu = (e) => e.preventDefault();
    palList.onmousedown = S.onPaletteDragStart;

    S.resizeCanvas();
    window.addEventListener("resize", S.resizeCanvas);

    S.showSamplesGallery();
  }

  /* ── Workflow Suggestions Panel ── */

  let suggestionsVisible = false;

  async function toggleSuggestions() {
    suggestionsVisible = !suggestionsVisible;
    const panel = S.suggestionsPanel;
    if (!suggestionsVisible) { panel.style.display = "none"; return; }
    panel.style.display = "block";
    panel.innerHTML = `<div class="wf-suggestions-header"><span>${B.t("wf_suggestions")}</span><button class="wf-suggestions-close">\u2715</button></div><div style="text-align:center;padding:12px;color:var(--text-faint);font-size:0.75rem">Loading...</div>`;
    panel.querySelector(".wf-suggestions-close").onclick = () => { suggestionsVisible = false; panel.style.display = "none"; };
    try {
      const res = await fetch("/api/workflows/suggestions?top_k=5");
      const data = await res.json();
      renderSuggestions(data);
    } catch { renderSuggestions([]); }
  }

  function renderSuggestions(suggestions) {
    const panel = S.suggestionsPanel;
    const header = panel.querySelector(".wf-suggestions-header");
    panel.innerHTML = "";
    panel.appendChild(header);
    header.querySelector(".wf-suggestions-close").onclick = () => { suggestionsVisible = false; panel.style.display = "none"; };

    if (!suggestions.length) {
      const empty = document.createElement("div");
      empty.className = "wf-suggestions-empty";
      empty.textContent = B.t("wf_no_suggestions");
      panel.appendChild(empty);
      return;
    }

    suggestions.forEach((s) => {
      const card = document.createElement("div");
      card.className = "wf-suggestion-card";
      const pct = Math.round((s.confidence || 0) * 100);
      card.innerHTML = `
        <div class="wf-suggestion-title">${B.esc(s.title)}</div>
        <div class="wf-suggestion-desc">${B.esc(s.description)}</div>
        <div class="wf-suggestion-meta"><span class="wf-suggestion-score">${pct}% ${B.t("wf_suggestion_confidence")}</span></div>
        <div class="wf-suggestion-actions">
          <button class="wf-suggestion-btn accept">${B.t("wf_suggestion_accept")}</button>
          <button class="wf-suggestion-btn dismiss">${B.t("wf_suggestion_dismiss")}</button>
        </div>
      `;
      card.querySelector(".accept").onclick = () => handleFeedback(s, "accepted", card);
      card.querySelector(".dismiss").onclick = () => handleFeedback(s, "dismissed", card);
      panel.appendChild(card);
    });
  }

  async function handleFeedback(suggestion, action, cardEl) {
    try {
      await fetch(`/api/workflows/suggestions/${suggestion.id}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
    } catch { /* non-blocking */ }
    if (action === "accepted" && suggestion.draft_workflow) {
      S.loadWorkflow(suggestion.draft_workflow);
      suggestionsVisible = false;
      S.suggestionsPanel.style.display = "none";
    }
    cardEl.style.opacity = "0.3";
    cardEl.style.pointerEvents = "none";
    setTimeout(() => cardEl.remove(), 500);
  }

  /* ── Chat-based Workflow Recommendation ── */

  const RECOMMEND_RULES = [
    { keywords: ["code review", "코드 리뷰", "review my code", "PR review"], workflow: "code-review-gate", reason: "Code review workflow" },
    { keywords: ["translate", "번역", "translation"], workflow: "translate-review", reason: "Translation workflow" },
    { keywords: ["search", "검색", "find information", "look up", "RAG"], workflow: "rag-pipeline", reason: "RAG search pipeline" },
    { keywords: ["safety", "moderation", "filter", "guardrail", "안전"], workflow: "safety-filter", reason: "Safety filter" },
    { keywords: ["step by step", "단계별", "chain of thought", "think through"], workflow: "chain-of-thought", reason: "Chain of thought" },
    { keywords: ["compare models", "모델 비교", "consensus", "multiple models"], workflow: "multi-model-consensus", reason: "Multi-model consensus" },
    { keywords: ["remember", "기억", "save this", "learn", "memorize"], workflow: "memory-write-loop", reason: "Learn & remember" },
    { keywords: ["telegram", "텔레그램", "bot message"], workflow: "telegram-auto-reply", reason: "Telegram auto-reply" },
    { keywords: ["tool", "도구", "use tool", "execute", "run code", "API call"], workflow: "tool-loop", reason: "Agentic tool loop" },
    { keywords: ["automate", "자동화", "workflow", "워크플로우", "pipeline"], workflow: "simple-chat", reason: "Build your own workflow" },
  ];

  function checkRecommendation(userMessage) {
    const msg = userMessage.toLowerCase();
    for (const rule of RECOMMEND_RULES) {
      for (const kw of rule.keywords) {
        if (msg.includes(kw.toLowerCase())) return { workflowId: rule.workflow, reason: rule.reason };
      }
    }
    return null;
  }

  function showRecommendBanner(rec) {
    const existing = document.querySelector(".wf-recommend");
    if (existing) existing.remove();

    const banner = document.createElement("div");
    banner.className = "wf-recommend";
    banner.innerHTML = `
      <span class="wf-recommend-icon">\u{1F4A1}</span>
      <span class="wf-recommend-text">This looks like a <strong>${B.esc(rec.reason)}</strong> task.</span>
      <button class="wf-recommend-btn" id="wf-rec-use">Use Workflow</button>
      <button class="wf-recommend-dismiss" id="wf-rec-dismiss">\u2715</button>
    `;

    const chatEl = B.$("chat");
    chatEl.appendChild(banner);

    banner.querySelector("#wf-rec-use").onclick = async () => {
      banner.remove();
      try {
        const res = await fetch(`/api/workflows/${rec.workflowId}`);
        if (res.ok) {
          const wf = await res.json();
          B.switchView("workflow");
          setTimeout(() => S.loadWorkflow(wf), 100);
        }
      } catch { /* */ }
    };

    banner.querySelector("#wf-rec-dismiss").onclick = () => banner.remove();
    setTimeout(() => { if (banner.parentNode) banner.remove(); }, 15000);
  }

  // Expose for app.js
  B.workflow = { checkRecommendation, showRecommendBanner };
  B.viewHooks.workflow = { onActivate: init };
})();
