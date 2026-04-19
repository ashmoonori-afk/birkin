/* Birkin Workflow — Config panel, save/load, samples, gallery */

(function () {
  const B = window.birkin;
  const S = B._wf;

  /* ── Node config panel ── */

  function showConfig(node) {
    if (!S.configPanel) return;
    const info = S.getPaletteFlat()[node.type] || { label: node.type, desc: "" };
    S.configPanel.className = "wf-config open";
    S.configPanel.innerHTML = `
      <div class="wf-config-title">${B.esc(info.label)} — ${B.esc(node.id)}</div>
      <div class="wf-config-field">
        <label class="wf-config-label">Label</label>
        <input class="wf-config-input" id="wf-cfg-label" value="${B.esc(node.config?.label || node.label || info.label)}" />
      </div>
      ${["llm","llm-stream","classifier","embedder","summarizer","translator","knowledge-extract"].includes(node.type) ? `
        <div class="wf-config-field">
          <label class="wf-config-label">Provider</label>
          <select class="wf-config-select" id="wf-cfg-provider">
            <option value="">Default</option>
            <option value="anthropic">Anthropic (Claude)</option>
            <option value="openai">OpenAI (GPT)</option>
            <option value="gemini">Gemini</option>
            <option value="perplexity">Perplexity</option>
            <option value="groq">Groq</option>
            <option value="ollama">Ollama (Local)</option>
            <option value="openrouter">OpenRouter</option>
            <option value="claude-cli">Claude CLI (Local)</option>
            <option value="codex-cli">Codex CLI (Local)</option>
          </select>
        </div>
      ` : ""}
      ${node.type === "prompt-template" ? `
        <div class="wf-config-field">
          <label class="wf-config-label">Template</label>
          <input class="wf-config-input" id="wf-cfg-template" value="${B.esc(node.config?.template || "")}" placeholder="{input}" />
        </div>
      ` : ""}
      ${node.type === "condition" ? `
        <div class="wf-config-field">
          <label class="wf-config-label">Check</label>
          <input class="wf-config-input" id="wf-cfg-check" value="${B.esc(node.config?.check || "")}" placeholder="e.g., has_tool_calls" />
        </div>
      ` : ""}
      ${node.type === "delay" ? `
        <div class="wf-config-field">
          <label class="wf-config-label">Seconds</label>
          <input class="wf-config-input" type="number" id="wf-cfg-seconds" value="${node.config?.seconds || 1}" min="0" />
        </div>
      ` : ""}
      ${node.type === "loop" ? `
        <div class="wf-config-field">
          <label class="wf-config-label">Max Iterations</label>
          <input class="wf-config-input" type="number" id="wf-cfg-max" value="${node.config?.max || 5}" min="1" />
        </div>
      ` : ""}
      <div style="display:flex;gap:6px;margin-top:8px">
        <button class="wf-tb-btn" id="wf-cfg-apply">Apply</button>
        <button class="wf-tb-btn danger" id="wf-cfg-delete">Delete Node</button>
        <button class="wf-tb-btn" id="wf-cfg-close">Close</button>
      </div>
    `;

    // Restore saved provider selection
    const provSelect = S.configPanel.querySelector("#wf-cfg-provider");
    if (provSelect && node.config?.provider) provSelect.value = node.config.provider;

    S.configPanel.querySelector("#wf-cfg-apply").onclick = () => {
      node.config = node.config || {};
      const lbl = S.configPanel.querySelector("#wf-cfg-label");
      if (lbl) node.config.label = lbl.value;
      const prov = S.configPanel.querySelector("#wf-cfg-provider");
      if (prov) node.config.provider = prov.value;
      const tmpl = S.configPanel.querySelector("#wf-cfg-template");
      if (tmpl) node.config.template = tmpl.value;
      const chk = S.configPanel.querySelector("#wf-cfg-check");
      if (chk) node.config.check = chk.value;
      const sec = S.configPanel.querySelector("#wf-cfg-seconds");
      if (sec) node.config.seconds = parseInt(sec.value);
      const mx = S.configPanel.querySelector("#wf-cfg-max");
      if (mx) node.config.max = parseInt(mx.value);
      node.label = node.config.label;
      S.draw();
      closeConfig();
    };
    S.configPanel.querySelector("#wf-cfg-delete").onclick = () => S.deleteNode(node.id);
    S.configPanel.querySelector("#wf-cfg-close").onclick = closeConfig;
  }

  function closeConfig() {
    if (S.configPanel) S.configPanel.className = "wf-config";
  }

  /* ── Load / Save ── */

  function loadWorkflow(wf) {
    S.nodes = (wf.nodes || []).map((n) => ({ ...n, label: n.config?.label || S.getPaletteFlat()[n.type]?.label || n.type }));
    S.edges = [...(wf.edges || [])];
    S.currentWorkflowId = wf.id;
    S.nodeIdCounter = S.nodes.reduce((max, n) => {
      const m = n.id.match(/\d+$/);
      return m ? Math.max(max, parseInt(m[0], 10)) : max;
    }, 0);

    const title = S.container.querySelector("#wf-title");
    if (title) title.textContent = wf.name || wf.id;

    S.samplesOpen = false;
    S.samplesPanel.className = "wf-samples";
    closeConfig();
    S.selectedNode = null;

    if (S.nodes.length) {
      const minX = Math.min(...S.nodes.map((n) => n.x));
      const minY = Math.min(...S.nodes.map((n) => n.y));
      S.pan.x = 40 - minX * S.zoom;
      S.pan.y = 40 - minY * S.zoom;
    }

    S.draw();
  }

  async function saveCurrentWorkflow() {
    const t = B.t;
    const name = prompt(t("workflow_name_prompt"), S.currentWorkflowId || "my-workflow");
    if (!name) return;
    const wf = {
      id: S.currentWorkflowId || name.toLowerCase().replace(/\s+/g, "-"),
      name,
      description: "",
      nodes: S.nodes.map((n) => ({ id: n.id, type: n.type, x: Math.round(n.x), y: Math.round(n.y), config: n.config || {} })),
      edges: S.edges.map((e) => ({ ...e })),
    };
    try {
      const res = await fetch("/api/workflows", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(wf) });
      if (res.ok) {
        const data = await res.json();
        S.currentWorkflowId = data.id;
        const title = S.container.querySelector("#wf-title");
        if (title) title.textContent = name;
        showActivatePrompt(data.id, name);
      } else {
        alert(B.t("wf_save_failed") || "Failed to save workflow");
      }
    } catch {
      alert(B.t("wf_save_failed") || "Failed to save workflow");
    }
  }

  /* ── Activate / Deactivate ── */

  async function showActivatePrompt(workflowId, workflowName) {
    const t = B.t;
    const bar = document.createElement("div");
    bar.className = "wf-activate-bar";
    bar.innerHTML = `
      <span class="wf-activate-text">${t("wf_activate_prompt")} <strong>${B.esc(workflowName)}</strong></span>
      <button class="wf-activate-btn yes" id="wf-act-yes">${t("wf_activate_yes")}</button>
      <button class="wf-activate-btn no" id="wf-act-no">${t("wf_activate_no")}</button>
    `;
    S.canvas.parentElement.appendChild(bar);
    bar.querySelector("#wf-act-yes").onclick = async () => {
      await setActiveWorkflow(workflowId);
      bar.remove();
      updateActivateButton();
    };
    bar.querySelector("#wf-act-no").onclick = () => bar.remove();
    setTimeout(() => { if (bar.parentNode) bar.remove(); }, 15000);
  }

  async function setActiveWorkflow(workflowId) {
    try {
      await fetch("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ active_workflow: workflowId }) });
      if (B.currentConfig) B.currentConfig.active_workflow = workflowId;
    } catch { /* */ }
  }

  function updateActivateButton() {
    const btn = S.container.querySelector("#wf-btn-activate");
    if (!btn) return;
    const activeId = B.currentConfig?.active_workflow;
    if (activeId && activeId === S.currentWorkflowId) {
      btn.textContent = B.t("wf_deactivate");
      btn.classList.add("active");
      btn.onclick = async () => { await setActiveWorkflow(null); updateActivateButton(); };
    } else if (S.currentWorkflowId && S.nodes.length) {
      btn.textContent = B.t("wf_activate");
      btn.classList.remove("active");
      btn.onclick = () => { setActiveWorkflow(S.currentWorkflowId); updateActivateButton(); };
    } else {
      btn.textContent = B.t("wf_activate");
      btn.classList.remove("active");
      btn.onclick = () => {};
    }
  }

  /* ── Samples ── */

  async function toggleSamples() {
    S.samplesOpen = !S.samplesOpen;
    if (!S.samplesOpen) { S.samplesPanel.className = "wf-samples"; return; }
    S.samplesPanel.className = "wf-samples open";
    S.samplesPanel.innerHTML = '<div class="wf-samples-title">Sample Workflows</div>';
    try {
      const res = await fetch("/api/workflows");
      if (!res.ok) return;
      const data = await res.json();
      const all = [...(data.samples || []), ...(data.saved || [])];
      all.forEach((wf) => {
        const item = document.createElement("div");
        item.className = "wf-sample-item";
        item.innerHTML = `<div class="wf-sample-name">${B.esc(wf.name || wf.id)}</div><div class="wf-sample-desc">${B.esc(wf.description || "")}</div>`;
        item.onclick = () => loadWorkflow(wf);
        S.samplesPanel.appendChild(item);
      });
    } catch { S.samplesPanel.innerHTML += '<div class="wf-sample-desc">Failed to load</div>'; }
  }

  /* ── Gallery (empty canvas) ── */

  async function showSamplesGallery() {
    if (S.nodes.length) return;
    try {
      const res = await fetch("/api/workflows");
      if (!res.ok) return;
      const data = await res.json();
      const all = [...(data.samples || []), ...(data.saved || [])];
      if (!all.length) return;

      S.galleryEl = document.createElement("div");
      S.galleryEl.className = "wf-gallery";
      S.galleryEl.innerHTML = `
        <div class="wf-gallery-header">
          <div class="wf-gallery-title">Choose a Workflow</div>
          <div class="wf-gallery-sub">Select a template to start, or drag nodes from the palette to build your own</div>
        </div>
        <div class="wf-gallery-grid" id="wf-gallery-grid"></div>
      `;
      const grid = S.galleryEl.querySelector("#wf-gallery-grid");
      const icons = {
        "simple-chat": "\u2709", "code-review-gate": "\u{1F50F}", "rag-pipeline": "\u{1F50E}",
        "multi-model-consensus": "\u{1F500}", "safety-filter": "\u{1F6E1}", "tool-loop": "\u2699",
        "chain-of-thought": "\u{1F9E0}", "translate-review": "\u{1F30D}", "memory-write-loop": "\u{1F4BE}",
        "telegram-auto-reply": "\u2708",
      };
      all.forEach((wf) => {
        const card = document.createElement("div");
        card.className = "wf-gallery-card";
        const icon = icons[wf.id] || "\u{1F4CB}";
        card.innerHTML = `
          <div class="wf-gallery-card-icon">${icon}</div>
          <div class="wf-gallery-card-name">${B.esc(wf.name || wf.id)}</div>
          <div class="wf-gallery-card-desc">${B.esc(wf.description || "")}</div>
          <div class="wf-gallery-card-meta">${(wf.nodes || []).length} nodes</div>
        `;
        card.onclick = () => { S.galleryEl.remove(); S.galleryEl = null; loadWorkflow(wf); };
        grid.appendChild(card);
      });

      const blank = document.createElement("div");
      blank.className = "wf-gallery-card wf-gallery-card-blank";
      blank.innerHTML = `<div class="wf-gallery-card-icon">+</div><div class="wf-gallery-card-name">Blank Canvas</div><div class="wf-gallery-card-desc">Start from scratch</div>`;
      blank.onclick = () => { S.galleryEl.remove(); S.galleryEl = null; S.draw(); };
      grid.appendChild(blank);

      S.canvas.parentElement.appendChild(S.galleryEl);
    } catch { /* silent */ }
  }

  function clearCanvas() {
    if (S.nodes.length && !confirm("Clear all nodes?")) return;
    S.nodes = []; S.edges = []; S.currentWorkflowId = null; S.selectedNode = null;
    closeConfig();
    const title = S.container.querySelector("#wf-title");
    if (title) title.textContent = "Untitled Workflow";
    S.draw();
  }

  // Expose
  S.showConfig = showConfig;
  S.closeConfig = closeConfig;
  S.loadWorkflow = loadWorkflow;
  S.saveCurrentWorkflow = saveCurrentWorkflow;
  S.toggleSamples = toggleSamples;
  S.showSamplesGallery = showSamplesGallery;
  S.updateActivateButton = updateActivateButton;
  S.clearCanvas = clearCanvas;
})();
