/* Birkin — Workflow Visualizer (SVG pipeline with real-time SSE highlighting) */

(function () {
  const B = window.birkin;
  const container = B.$("view-workflow");
  let initialized = false;
  let nodeEls = {};
  let arrowEls = {};
  let tooltipEl = null;
  let tgRow = null;
  let activeNode = null;

  const NODES = [
    { id: "input",    label: "Input",    icon: "\u2709", desc: "Your message is received and prepared for the AI" },
    { id: "provider", label: "Provider", icon: "\u26A1", desc: "Connecting to the AI provider (e.g., Claude, GPT)" },
    { id: "llm",      label: "LLM",      icon: "\u2728", desc: "The AI model is thinking about your request" },
    { id: "tools",    label: "Tools",    icon: "\u2699", desc: "The AI is using tools to look up info or perform actions" },
    { id: "memory",   label: "Memory",   icon: "\u{1F4BE}", desc: "The AI is checking or updating its knowledge base" },
    { id: "response", label: "Response", icon: "\u2705", desc: "The answer is being assembled and sent to you" },
  ];

  const ARROWS = [
    ["input", "provider"], ["provider", "llm"], ["llm", "tools"],
    ["tools", "memory"], ["llm", "response"], ["memory", "llm"],
  ];

  function init() {
    if (initialized) return;
    initialized = true;

    const W = 700, H = 320;
    const nodeW = 80, nodeH = 60, gap = 30;
    const startX = 30;

    // Build SVG
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.classList.add("wf-svg");

    // Defs (glow filter + arrowhead)
    svg.innerHTML = `
      <defs>
        <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="4" result="blur"/>
          <feComposite in="SourceGraphic" in2="blur" operator="over"/>
        </filter>
        <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
          <path d="M0 0L8 3L0 6" fill="rgba(240,240,250,0.25)"/>
        </marker>
      </defs>
    `;

    // Position nodes: main row (input, provider, llm, response) + branch (tools, memory)
    const positions = {
      input:    { x: startX,                y: 80 },
      provider: { x: startX + nodeW + gap,  y: 80 },
      llm:      { x: startX + 2*(nodeW+gap), y: 80 },
      response: { x: startX + 4*(nodeW+gap), y: 80 },
      tools:    { x: startX + 3*(nodeW+gap), y: 30 },
      memory:   { x: startX + 3*(nodeW+gap), y: 130 },
    };

    // Draw arrows first (behind nodes)
    ARROWS.forEach(([from, to]) => {
      const a = positions[from], b = positions[to];
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", a.x + nodeW/2);
      line.setAttribute("y1", a.y + nodeH/2);
      line.setAttribute("x2", b.x + nodeW/2);
      line.setAttribute("y2", b.y + nodeH/2);
      line.classList.add("wf-arrow");
      svg.appendChild(line);
      arrowEls[`${from}-${to}`] = line;
    });

    // Draw nodes
    NODES.forEach((n) => {
      const pos = positions[n.id];
      const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
      g.classList.add("wf-node");
      g.setAttribute("data-id", n.id);

      const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rect.setAttribute("x", pos.x); rect.setAttribute("y", pos.y);
      rect.setAttribute("width", nodeW); rect.setAttribute("height", nodeH);
      g.appendChild(rect);

      const icon = document.createElementNS("http://www.w3.org/2000/svg", "text");
      icon.classList.add("wf-icon");
      icon.setAttribute("x", pos.x + nodeW/2); icon.setAttribute("y", pos.y + 22);
      icon.textContent = n.icon;
      g.appendChild(icon);

      const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.classList.add("wf-label");
      label.setAttribute("x", pos.x + nodeW/2); label.setAttribute("y", pos.y + nodeH - 8);
      label.textContent = n.label;
      g.appendChild(label);

      // Hover tooltip
      g.onmouseenter = () => showTooltip(n);
      g.onmouseleave = () => hideTooltip();
      g.style.cursor = "pointer";

      svg.appendChild(g);
      nodeEls[n.id] = g;
    });

    // Telegram sub-flow (below main)
    const tgG = document.createElementNS("http://www.w3.org/2000/svg", "g");
    tgG.classList.add("wf-tg-row");
    const tgLabels = ["Telegram", "Webhook", "Dispatcher"];
    const tgY = 220;
    tgLabels.forEach((lbl, i) => {
      const x = startX + i * (nodeW + gap);
      const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rect.setAttribute("x", x); rect.setAttribute("y", tgY);
      rect.setAttribute("width", nodeW); rect.setAttribute("height", 40);
      rect.setAttribute("rx", "6"); rect.setAttribute("fill", "rgba(240,240,250,0.03)");
      rect.setAttribute("stroke", "rgba(240,240,250,0.1)"); rect.setAttribute("stroke-width", "1");
      tgG.appendChild(rect);

      const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
      text.setAttribute("x", x + nodeW/2); text.setAttribute("y", tgY + 24);
      text.setAttribute("text-anchor", "middle");
      text.setAttribute("fill", "rgba(240,240,250,0.4)");
      text.setAttribute("font-size", "9"); text.setAttribute("font-weight", "700");
      text.setAttribute("letter-spacing", "0.5");
      text.textContent = lbl.toUpperCase();
      tgG.appendChild(text);

      if (i < tgLabels.length - 1) {
        const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
        line.setAttribute("x1", x + nodeW); line.setAttribute("y1", tgY + 20);
        line.setAttribute("x2", x + nodeW + gap); line.setAttribute("y2", tgY + 20);
        line.setAttribute("stroke", "rgba(240,240,250,0.1)"); line.setAttribute("stroke-width", "1");
        line.setAttribute("stroke-dasharray", "3,3");
        tgG.appendChild(line);
      }
    });
    // Dashed connector from Dispatcher to Input
    const dashLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
    dashLine.setAttribute("x1", startX + 2*(nodeW+gap) + nodeW/2); dashLine.setAttribute("y1", tgY);
    dashLine.setAttribute("x2", positions.input.x + nodeW/2); dashLine.setAttribute("y2", positions.input.y + nodeH);
    dashLine.setAttribute("stroke", "rgba(240,240,250,0.1)"); dashLine.setAttribute("stroke-width", "1");
    dashLine.setAttribute("stroke-dasharray", "4,4");
    tgG.appendChild(dashLine);

    svg.appendChild(tgG);
    tgRow = tgG;

    // Container
    const wrap = document.createElement("div");
    wrap.className = "wf-container";
    wrap.appendChild(svg);

    // Tooltip
    tooltipEl = document.createElement("div");
    tooltipEl.className = "wf-tooltip";
    wrap.appendChild(tooltipEl);
    wrap.style.position = "relative";

    // Legend
    const legend = document.createElement("div");
    legend.className = "wf-legend";
    legend.innerHTML = `
      <span class="wf-legend-item"><span class="wf-legend-dot" style="background:rgba(240,240,250,0.15)"></span> Idle</span>
      <span class="wf-legend-item"><span class="wf-legend-dot" style="background:rgba(240,240,250,0.6)"></span> Active</span>
      <span class="wf-legend-item"><span class="wf-legend-dot" style="background:#4ade80"></span> Complete</span>
      <span class="wf-legend-item"><span class="wf-legend-dot" style="background:#ef4444"></span> Error</span>
    `;
    wrap.appendChild(legend);

    container.appendChild(wrap);

    // Check Telegram status
    checkTelegram();
  }

  function showTooltip(node) {
    if (!tooltipEl) return;
    tooltipEl.innerHTML = `<strong>${node.label}</strong><br>${node.desc}`;
    tooltipEl.classList.add("visible");
  }
  function hideTooltip() {
    if (tooltipEl) tooltipEl.classList.remove("visible");
  }

  function setNodeState(id, state) {
    const el = nodeEls[id];
    if (!el) return;
    el.classList.remove("active", "complete", "error");
    if (state) el.classList.add(state);
  }

  function resetAll() {
    Object.keys(nodeEls).forEach((id) => setNodeState(id, null));
  }

  function onSSEEvent(evt) {
    if (!initialized) return;

    // User sent message
    if (evt.session_id) { setNodeState("input", "active"); activeNode = "input"; }

    if (evt.thinking === true) {
      setNodeState("input", "complete");
      setNodeState("provider", "active");
      setNodeState("llm", "active");
      activeNode = "llm";
    }
    if (evt.thinking === false && activeNode === "llm") {
      setNodeState("provider", "complete");
    }

    if (evt.tool_call) {
      setNodeState("llm", "complete");
      setNodeState("tools", "active");
      activeNode = "tools";
    }

    if (evt.tool_result) {
      setNodeState("tools", "complete");
      setNodeState("memory", "active");
      activeNode = "memory";
      setTimeout(() => { setNodeState("memory", "complete"); }, 500);
    }

    if (evt.delta && !activeNode?.startsWith("response")) {
      if (activeNode === "memory") setNodeState("memory", "complete");
      if (activeNode === "llm") { setNodeState("provider", "complete"); setNodeState("llm", "complete"); }
      setNodeState("response", "active");
      activeNode = "response";
    }

    if (evt.done) {
      setNodeState("response", "complete");
      setTimeout(resetAll, 2000);
      activeNode = null;
    }

    if (evt.error) {
      if (activeNode) setNodeState(activeNode, "error");
      setTimeout(resetAll, 3000);
      activeNode = null;
    }
  }

  async function checkTelegram() {
    try {
      const res = await fetch("/api/telegram/status");
      if (res.ok) {
        const data = await res.json();
        if (data.configured && tgRow) tgRow.classList.add("configured");
      }
    } catch { /* */ }
  }

  // Register with app.js
  B.viewHooks.workflow = { onActivate: init };

  // Expose for SSE event forwarding
  B.workflow = { onEvent: onSSEEvent };
})();
