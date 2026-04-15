/* Birkin — Visual Workflow Editor (drag-and-drop canvas) */

(function () {
  const B = window.birkin;
  const container = B.$("view-workflow");
  let initialized = false;
  let canvas, ctx;
  let nodes = [], edges = [];
  let pan = { x: 0, y: 0 }, zoom = 1;
  let drag = null, connecting = null, hoveredNode = null, selectedNode = null;
  let samplesOpen = false;
  let currentWorkflowId = null;
  let configPanel = null, samplesPanel = null;

  const NODE_W = 140, NODE_H = 56, PORT_R = 6;

  /* ── Node Palette Definition (i18n key references) ── */
  // Each item uses i18n keys: label → "nt_xxx", group → "ng_xxx"
  const PALETTE_DEF = [
    { groupKey: "ng_io", items: [
      { type: "input",           icon: "\u2709",    labelKey: "nt_input",         descKey: "nd_input",         color: "nc-io" },
      { type: "output",          icon: "\u2705",    labelKey: "nt_output",        descKey: "nd_output",        color: "nc-io" },
      { type: "webhook-trigger", icon: "\u{1F310}", labelKey: "nt_webhook",       descKey: "nd_webhook",       color: "nc-platform" },
    ]},
    { groupKey: "ng_ai", items: [
      { type: "llm",             icon: "\u2728",    labelKey: "nt_llm",           descKey: "nd_llm",           color: "nc-ai" },
      { type: "llm-stream",      icon: "\u{1F4A8}", labelKey: "nt_llm_stream",    descKey: "nd_llm_stream",    color: "nc-ai" },
      { type: "classifier",      icon: "\u{1F3AF}", labelKey: "nt_classifier",    descKey: "nd_classifier",    color: "nc-ai" },
      { type: "embedder",        icon: "\u{1F9F2}", labelKey: "nt_embedder",      descKey: "nd_embedder",      color: "nc-ai" },
      { type: "summarizer",      icon: "\u{1F4DD}", labelKey: "nt_summarizer",    descKey: "nd_summarizer",    color: "nc-ai" },
      { type: "translator",      icon: "\u{1F30D}", labelKey: "nt_translator",    descKey: "nd_translator",    color: "nc-ai" },
    ]},
    { groupKey: "ng_tools", items: [
      { type: "tool-dispatch",   icon: "\u2699",    labelKey: "nt_tool_dispatch", descKey: "nd_tool_dispatch", color: "nc-tool" },
      { type: "web-search",      icon: "\u{1F50D}", labelKey: "nt_web_search",    descKey: "nd_web_search",    color: "nc-tool" },
      { type: "code-exec",       icon: "\u{1F4BB}", labelKey: "nt_code_exec",     descKey: "nd_code_exec",     color: "nc-tool" },
      { type: "api-call",        icon: "\u{1F517}", labelKey: "nt_api_call",      descKey: "nd_api_call",      color: "nc-tool" },
      { type: "file-read",       icon: "\u{1F4C4}", labelKey: "nt_file_read",     descKey: "nd_file_read",     color: "nc-tool" },
      { type: "file-write",      icon: "\u{1F4BE}", labelKey: "nt_file_write",    descKey: "nd_file_write",    color: "nc-tool" },
    ]},
    { groupKey: "ng_memory", items: [
      { type: "memory-search",     icon: "\u{1F50E}", labelKey: "nt_mem_search",  descKey: "nd_mem_search",  color: "nc-memory" },
      { type: "memory-write",      icon: "\u{1F4DD}", labelKey: "nt_mem_write",   descKey: "nd_mem_write",   color: "nc-memory" },
      { type: "context-inject",    icon: "\u{1F4E5}", labelKey: "nt_ctx_inject",  descKey: "nd_ctx_inject",  color: "nc-memory" },
      { type: "knowledge-extract", icon: "\u{1F9E0}", labelKey: "nt_knowledge",   descKey: "nd_knowledge",   color: "nc-memory" },
    ]},
    { groupKey: "ng_control", items: [
      { type: "condition",       icon: "\u2747",    labelKey: "nt_condition",      descKey: "nd_condition",    color: "nc-control" },
      { type: "merge",           icon: "\u{1F500}", labelKey: "nt_merge",          descKey: "nd_merge",        color: "nc-control" },
      { type: "loop",            icon: "\u{1F504}", labelKey: "nt_loop",           descKey: "nd_loop",         color: "nc-control" },
      { type: "delay",           icon: "\u23F3",    labelKey: "nt_delay",          descKey: "nd_delay",        color: "nc-control" },
      { type: "parallel",        icon: "\u2261",    labelKey: "nt_parallel",       descKey: "nd_parallel",     color: "nc-control" },
      { type: "prompt-template", icon: "\u{1F4CB}", labelKey: "nt_prompt_tpl",     descKey: "nd_prompt_tpl",   color: "nc-control" },
    ]},
    { groupKey: "ng_gates", items: [
      { type: "code-review",    icon: "\u{1F50F}", labelKey: "nt_code_review",    descKey: "nd_code_review",    color: "nc-gate" },
      { type: "human-review",   icon: "\u{1F464}", labelKey: "nt_human_review",   descKey: "nd_human_review",   color: "nc-gate" },
      { type: "guardrail",      icon: "\u{1F6E1}", labelKey: "nt_guardrail",      descKey: "nd_guardrail",      color: "nc-gate" },
      { type: "validator",      icon: "\u2714",    labelKey: "nt_validator",       descKey: "nd_validator",       color: "nc-gate" },
      { type: "test-runner",    icon: "\u{1F9EA}", labelKey: "nt_test_runner",     descKey: "nd_test_runner",     color: "nc-gate" },
    ]},
    { groupKey: "ng_platform", items: [
      { type: "telegram-send",  icon: "\u2708",    labelKey: "nt_tg_send",        descKey: "nd_tg_send",        color: "nc-platform" },
      { type: "email-send",     icon: "\u2709",    labelKey: "nt_email_send",     descKey: "nd_email_send",     color: "nc-platform" },
      { type: "notify",         icon: "\u{1F514}", labelKey: "nt_notify",          descKey: "nd_notify",          color: "nc-platform" },
    ]},
  ];

  // Resolve i18n at access time
  function getPalette() {
    const t = B.t;
    return PALETTE_DEF.map((g) => ({
      group: t(g.groupKey),
      items: g.items.map((it) => ({ ...it, label: t(it.labelKey), desc: t(it.descKey) })),
    }));
  }

  function getPaletteFlat() {
    const flat = {};
    getPalette().forEach((g) => g.items.forEach((it) => { flat[it.type] = it; }));
    return flat;
  }

  function init() {
    if (initialized) return;
    initialized = true;

    container.innerHTML = "";
    const editor = document.createElement("div");
    editor.className = "wf-editor";

    // ── Build palette ──
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

    // ── Canvas area ──
    const canvasArea = document.createElement("div");
    canvasArea.className = "wf-canvas-area";

    // Toolbar
    canvasArea.innerHTML = `
      <div class="wf-toolbar">
        <span class="wf-toolbar-title" id="wf-title">Untitled Workflow</span>
        <button class="wf-tb-btn" id="wf-btn-samples">Samples</button>
        <button class="wf-tb-btn" id="wf-btn-save">Save</button>
        <button class="wf-tb-btn" id="wf-btn-load">Load</button>
        <button class="wf-tb-btn" id="wf-btn-activate">Activate</button>
        <button class="wf-tb-btn" id="wf-btn-clear" >Clear</button>
      </div>
    `;

    const canvasWrap = document.createElement("div");
    canvasWrap.className = "wf-canvas-wrap";
    canvas = document.createElement("canvas");
    canvasWrap.appendChild(canvas);

    // Samples panel
    samplesPanel = document.createElement("div");
    samplesPanel.className = "wf-samples";
    samplesPanel.id = "wf-samples-panel";
    canvasWrap.appendChild(samplesPanel);

    // Config panel
    configPanel = document.createElement("div");
    configPanel.className = "wf-config";
    configPanel.id = "wf-config-panel";
    canvasWrap.appendChild(configPanel);

    canvasArea.appendChild(canvasWrap);
    editor.appendChild(canvasArea);
    container.appendChild(editor);

    ctx = canvas.getContext("2d");

    // Wire events
    palette.querySelector("#wf-pal-search").oninput = (e) => {
      buildPaletteList(palList, e.target.value.toLowerCase());
    };

    canvasArea.querySelector("#wf-btn-samples").onclick = toggleSamples;
    canvasArea.querySelector("#wf-btn-save").onclick = saveCurrentWorkflow;
    canvasArea.querySelector("#wf-btn-load").onclick = loadWorkflowPrompt;
    canvasArea.querySelector("#wf-btn-clear").onclick = clearCanvas;
    updateActivateButton();

    canvas.onmousedown = onCanvasMouseDown;
    canvas.onmousemove = onCanvasMouseMove;
    canvas.onmouseup = onCanvasMouseUp;
    canvas.ondblclick = onCanvasDblClick;
    canvas.onwheel = onCanvasWheel;
    canvas.oncontextmenu = (e) => e.preventDefault();

    // Palette drag-to-canvas
    palList.onmousedown = onPaletteDragStart;

    resizeCanvas();
    window.addEventListener("resize", resizeCanvas);

    // Show samples gallery on first load (empty canvas)
    showSamplesGallery();
  }

  /* ── Palette rendering ── */

  function buildPaletteList(el, filter) {
    el.innerHTML = "";
    getPalette().forEach((group) => {
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

  /* ── Palette drag to canvas ── */

  function onPaletteDragStart(e) {
    const item = e.target.closest(".wf-palette-item");
    if (!item) return;
    e.preventDefault();
    const type = item.dataset.type;
    const rect = canvas.getBoundingClientRect();

    const onMove = (ev) => {
      canvas.style.cursor = "copy";
      draw();
      // Draw ghost node at cursor
      const mx = ev.clientX - rect.left;
      const my = ev.clientY - rect.top;
      drawGhostNode(mx, my, type);
    };

    const onUp = (ev) => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      canvas.style.cursor = "default";
      const mx = ev.clientX - rect.left;
      const my = ev.clientY - rect.top;
      if (mx > 0 && my > 0) {
        addNode(type, (mx - pan.x) / zoom, (my - pan.y) / zoom);
      }
      draw();
    };

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }

  /* ── Node management ── */

  let nodeIdCounter = 0;

  function addNode(type, x, y) {
    nodeIdCounter++;
    const info = getPaletteFlat()[type] || { icon: "?", label: type, color: "nc-io" };
    nodes.push({
      id: `n${nodeIdCounter}`,
      type,
      x: x - NODE_W / 2,
      y: y - NODE_H / 2,
      config: {},
      label: info.label,
    });
    draw();
  }

  function deleteNode(nodeId) {
    nodes = nodes.filter((n) => n.id !== nodeId);
    edges = edges.filter((e) => e.from !== nodeId && e.to !== nodeId);
    if (selectedNode?.id === nodeId) { selectedNode = null; closeConfig(); }
    draw();
  }

  /* ── Drawing ── */

  function resizeCanvas() {
    if (!canvas) return;
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * devicePixelRatio;
    canvas.height = rect.height * devicePixelRatio;
    canvas.style.width = rect.width + "px";
    canvas.style.height = rect.height + "px";
    draw();
  }

  function draw() {
    if (!ctx) return;
    const w = canvas.width / devicePixelRatio;
    const h = canvas.height / devicePixelRatio;
    ctx.save();
    ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.save();
    ctx.translate(pan.x, pan.y);
    ctx.scale(zoom, zoom);

    // Draw edges
    edges.forEach((e) => {
      const from = nodes.find((n) => n.id === e.from);
      const to = nodes.find((n) => n.id === e.to);
      if (!from || !to) return;
      drawEdge(from, to, e.label);
    });

    // Draw connecting line
    if (connecting) {
      ctx.beginPath();
      ctx.moveTo(connecting.startX, connecting.startY);
      const mx = (connecting.curX - pan.x) / zoom;
      const my = (connecting.curY - pan.y) / zoom;
      ctx.lineTo(mx, my);
      ctx.strokeStyle = "rgba(240, 240, 250, 0.4)";
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 4]);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Draw nodes
    nodes.forEach((n) => drawNode(n));

    ctx.restore();
    ctx.restore();
  }

  function drawNode(n) {
    const info = getPaletteFlat()[n.type] || { icon: "?", color: "nc-io" };
    const isSelected = selectedNode?.id === n.id;
    const isHovered = hoveredNode?.id === n.id;

    // Background
    const colors = {
      "nc-io": [99, 102, 241], "nc-ai": [168, 85, 247], "nc-tool": [34, 197, 94],
      "nc-control": [251, 191, 36], "nc-gate": [239, 68, 68], "nc-memory": [45, 212, 191],
      "nc-platform": [96, 165, 250],
    };
    const rgb = colors[info.color] || [240, 240, 250];
    const alpha = isSelected ? 0.2 : isHovered ? 0.12 : 0.06;

    ctx.fillStyle = `rgba(${rgb.join(",")}, ${alpha})`;
    ctx.strokeStyle = isSelected ? `rgba(${rgb.join(",")}, 0.8)` : `rgba(${rgb.join(",")}, 0.3)`;
    ctx.lineWidth = isSelected ? 2 : 1;

    roundRect(ctx, n.x, n.y, NODE_W, NODE_H, 8);
    ctx.fill();
    ctx.stroke();

    // Icon
    ctx.font = "18px sans-serif";
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.fillStyle = `rgba(${rgb.join(",")}, 0.8)`;
    ctx.fillText(info.icon, n.x + 10, n.y + NODE_H / 2);

    // Label
    ctx.font = '700 10px "D-DIN", Arial, sans-serif';
    ctx.fillStyle = "rgba(240, 240, 250, 0.7)";
    ctx.textAlign = "left";
    const label = n.config?.label || n.label || info.label;
    ctx.fillText(label.substring(0, 14), n.x + 34, n.y + NODE_H / 2 - 6);

    // Type
    ctx.font = '9px "D-DIN", Arial, sans-serif';
    ctx.fillStyle = "rgba(240, 240, 250, 0.3)";
    ctx.fillText(n.type, n.x + 34, n.y + NODE_H / 2 + 8);

    // Output port (right)
    ctx.beginPath();
    ctx.arc(n.x + NODE_W, n.y + NODE_H / 2, PORT_R, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(${rgb.join(",")}, 0.4)`;
    ctx.fill();

    // Input port (left)
    ctx.beginPath();
    ctx.arc(n.x, n.y + NODE_H / 2, PORT_R, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(${rgb.join(",")}, 0.4)`;
    ctx.fill();

    // Delete button (top-right) when hovered
    if (isHovered || isSelected) {
      ctx.font = "12px sans-serif";
      ctx.fillStyle = "rgba(239, 68, 68, 0.6)";
      ctx.textAlign = "center";
      ctx.fillText("\u2715", n.x + NODE_W - 8, n.y + 10);
    }
  }

  function drawEdge(from, to, label) {
    const x1 = from.x + NODE_W, y1 = from.y + NODE_H / 2;
    const x2 = to.x, y2 = to.y + NODE_H / 2;

    ctx.beginPath();
    // Bezier curve
    const dx = Math.abs(x2 - x1) * 0.5;
    ctx.moveTo(x1, y1);
    ctx.bezierCurveTo(x1 + dx, y1, x2 - dx, y2, x2, y2);
    ctx.strokeStyle = "rgba(240, 240, 250, 0.2)";
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Arrowhead
    const angle = Math.atan2(y2 - y1, x2 - x1);
    ctx.beginPath();
    ctx.moveTo(x2 - 8 * Math.cos(angle - 0.4), y2 - 8 * Math.sin(angle - 0.4));
    ctx.lineTo(x2, y2);
    ctx.lineTo(x2 - 8 * Math.cos(angle + 0.4), y2 - 8 * Math.sin(angle + 0.4));
    ctx.strokeStyle = "rgba(240, 240, 250, 0.3)";
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Label
    if (label) {
      const mx = (x1 + x2) / 2, my = (y1 + y2) / 2 - 8;
      ctx.font = '9px "D-DIN", Arial, sans-serif';
      ctx.fillStyle = "rgba(240, 240, 250, 0.35)";
      ctx.textAlign = "center";
      ctx.fillText(label, mx, my);
    }
  }

  function drawGhostNode(mx, my, type) {
    ctx.save();
    ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
    ctx.globalAlpha = 0.5;
    const info = getPaletteFlat()[type] || { icon: "?", label: type };
    ctx.fillStyle = "rgba(240, 240, 250, 0.1)";
    ctx.strokeStyle = "rgba(240, 240, 250, 0.3)";
    roundRect(ctx, mx - NODE_W / 2, my - NODE_H / 2, NODE_W, NODE_H, 8);
    ctx.fill();
    ctx.stroke();
    ctx.font = "18px sans-serif";
    ctx.textAlign = "center";
    ctx.fillStyle = "rgba(240, 240, 250, 0.6)";
    ctx.fillText(info.icon, mx, my + 5);
    ctx.restore();
  }

  function roundRect(c, x, y, w, h, r) {
    c.beginPath();
    c.moveTo(x + r, y);
    c.lineTo(x + w - r, y); c.quadraticCurveTo(x + w, y, x + w, y + r);
    c.lineTo(x + w, y + h - r); c.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    c.lineTo(x + r, y + h); c.quadraticCurveTo(x, y + h, x, y + h - r);
    c.lineTo(x, y + r); c.quadraticCurveTo(x, y, x + r, y);
    c.closePath();
  }

  /* ── Canvas interaction ── */

  function canvasCoords(e) {
    const rect = canvas.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  function worldCoords(cx, cy) {
    return { x: (cx - pan.x) / zoom, y: (cy - pan.y) / zoom };
  }

  function getNodeAt(wx, wy) {
    for (let i = nodes.length - 1; i >= 0; i--) {
      const n = nodes[i];
      if (wx >= n.x && wx <= n.x + NODE_W && wy >= n.y && wy <= n.y + NODE_H) return n;
    }
    return null;
  }

  function isOnOutputPort(n, wx, wy) {
    return Math.hypot(wx - (n.x + NODE_W), wy - (n.y + NODE_H / 2)) < PORT_R + 4;
  }

  function isOnDeleteBtn(n, wx, wy) {
    return Math.hypot(wx - (n.x + NODE_W - 8), wy - (n.y + 8)) < 10;
  }

  function onCanvasMouseDown(e) {
    const c = canvasCoords(e);
    const w = worldCoords(c.x, c.y);
    const node = getNodeAt(w.x, w.y);

    if (node) {
      if (isOnDeleteBtn(node, w.x, w.y)) {
        deleteNode(node.id);
        return;
      }
      if (isOnOutputPort(node, w.x, w.y)) {
        connecting = { from: node.id, startX: node.x + NODE_W, startY: node.y + NODE_H / 2, curX: c.x, curY: c.y };
        return;
      }
      selectedNode = node;
      drag = { node, offX: w.x - node.x, offY: w.y - node.y };
      showConfig(node);
    } else {
      selectedNode = null;
      closeConfig();
      drag = { pan: true, startX: c.x, startY: c.y, px: pan.x, py: pan.y };
    }
    draw();
  }

  function onCanvasMouseMove(e) {
    const c = canvasCoords(e);
    const w = worldCoords(c.x, c.y);

    if (connecting) {
      connecting.curX = c.x;
      connecting.curY = c.y;
      draw();
      return;
    }

    if (drag?.node) {
      drag.node.x = w.x - drag.offX;
      drag.node.y = w.y - drag.offY;
      draw();
    } else if (drag?.pan) {
      pan.x = drag.px + (c.x - drag.startX);
      pan.y = drag.py + (c.y - drag.startY);
      draw();
    } else {
      const prev = hoveredNode;
      hoveredNode = getNodeAt(w.x, w.y);
      if (hoveredNode) {
        canvas.style.cursor = isOnOutputPort(hoveredNode, w.x, w.y) ? "crosshair" : "move";
      } else {
        canvas.style.cursor = "default";
      }
      if (prev !== hoveredNode) draw();
    }
  }

  function onCanvasMouseUp(e) {
    if (connecting) {
      const c = canvasCoords(e);
      const w = worldCoords(c.x, c.y);
      const target = getNodeAt(w.x, w.y);
      if (target && target.id !== connecting.from) {
        // Check no duplicate edge
        const exists = edges.some((ed) => ed.from === connecting.from && ed.to === target.id);
        if (!exists) {
          edges.push({ from: connecting.from, to: target.id });
        }
      }
      connecting = null;
      draw();
    }
    drag = null;
  }

  function onCanvasDblClick(e) {
    const c = canvasCoords(e);
    const w = worldCoords(c.x, c.y);
    const node = getNodeAt(w.x, w.y);
    if (node) {
      selectedNode = node;
      showConfig(node);
      draw();
    }
  }

  function onCanvasWheel(e) {
    e.preventDefault();
    const c = canvasCoords(e);
    const delta = e.deltaY > 0 ? 0.92 : 1.08;
    const nz = Math.max(0.3, Math.min(4, zoom * delta));
    pan.x = c.x - (c.x - pan.x) * (nz / zoom);
    pan.y = c.y - (c.y - pan.y) * (nz / zoom);
    zoom = nz;
    draw();
  }

  /* ── Node config panel ── */

  function showConfig(node) {
    if (!configPanel) return;
    const info = getPaletteFlat()[node.type] || { label: node.type, desc: "" };
    configPanel.className = "wf-config open";
    configPanel.innerHTML = `
      <div class="wf-config-title">${B.esc(info.label)} — ${B.esc(node.id)}</div>
      <div class="wf-config-field">
        <label class="wf-config-label">Label</label>
        <input class="wf-config-input" id="wf-cfg-label" value="${B.esc(node.config?.label || node.label || info.label)}" />
      </div>
      ${node.type === "llm" || node.type === "llm-stream" ? `
        <div class="wf-config-field">
          <label class="wf-config-label">Provider</label>
          <select class="wf-config-select" id="wf-cfg-provider">
            <option value="anthropic">Anthropic</option>
            <option value="openai">OpenAI</option>
            <option value="claude-cli">Claude CLI</option>
            <option value="codex-cli">Codex CLI</option>
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

    configPanel.querySelector("#wf-cfg-apply").onclick = () => {
      node.config = node.config || {};
      const lbl = configPanel.querySelector("#wf-cfg-label");
      if (lbl) node.config.label = lbl.value;
      const prov = configPanel.querySelector("#wf-cfg-provider");
      if (prov) node.config.provider = prov.value;
      const tmpl = configPanel.querySelector("#wf-cfg-template");
      if (tmpl) node.config.template = tmpl.value;
      const chk = configPanel.querySelector("#wf-cfg-check");
      if (chk) node.config.check = chk.value;
      const sec = configPanel.querySelector("#wf-cfg-seconds");
      if (sec) node.config.seconds = parseInt(sec.value);
      const mx = configPanel.querySelector("#wf-cfg-max");
      if (mx) node.config.max = parseInt(mx.value);
      node.label = node.config.label;
      draw();
      closeConfig();
    };
    configPanel.querySelector("#wf-cfg-delete").onclick = () => deleteNode(node.id);
    configPanel.querySelector("#wf-cfg-close").onclick = closeConfig;
  }

  function closeConfig() {
    if (configPanel) configPanel.className = "wf-config";
  }

  /* ── Samples panel ── */

  async function toggleSamples() {
    samplesOpen = !samplesOpen;
    if (!samplesOpen) { samplesPanel.className = "wf-samples"; return; }

    samplesPanel.className = "wf-samples open";
    samplesPanel.innerHTML = '<div class="wf-samples-title">Sample Workflows</div>';

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
        samplesPanel.appendChild(item);
      });
    } catch { samplesPanel.innerHTML += '<div class="wf-sample-desc">Failed to load</div>'; }
  }

  function loadWorkflow(wf) {
    nodes = (wf.nodes || []).map((n) => ({ ...n, label: n.config?.label || getPaletteFlat()[n.type]?.label || n.type }));
    edges = [...(wf.edges || [])];
    currentWorkflowId = wf.id;
    nodeIdCounter = nodes.length;

    const title = container.querySelector("#wf-title");
    if (title) title.textContent = wf.name || wf.id;

    samplesOpen = false;
    samplesPanel.className = "wf-samples";
    closeConfig();
    selectedNode = null;

    // Auto-fit
    if (nodes.length) {
      const minX = Math.min(...nodes.map((n) => n.x));
      const minY = Math.min(...nodes.map((n) => n.y));
      pan.x = 40 - minX * zoom;
      pan.y = 40 - minY * zoom;
    }

    draw();
  }

  async function saveCurrentWorkflow() {
    const t = B.t;
    const name = prompt(t("workflow_name_prompt"), currentWorkflowId || "my-workflow");
    if (!name) return;
    const wf = {
      id: currentWorkflowId || name.toLowerCase().replace(/\s+/g, "-"),
      name,
      description: "",
      nodes: nodes.map((n) => ({ id: n.id, type: n.type, x: Math.round(n.x), y: Math.round(n.y), config: n.config || {} })),
      edges: edges.map((e) => ({ from: e.from, to: e.to, label: e.label })),
    };
    try {
      const res = await fetch("/api/workflows", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(wf) });
      if (res.ok) {
        const data = await res.json();
        currentWorkflowId = data.id;
        const title = container.querySelector("#wf-title");
        if (title) title.textContent = name;

        // Prompt to activate this workflow for chat
        showActivatePrompt(data.id, name);
      }
    } catch { /* */ }
  }

  async function showActivatePrompt(workflowId, workflowName) {
    const t = B.t;
    const bar = document.createElement("div");
    bar.className = "wf-activate-bar";
    bar.innerHTML = `
      <span class="wf-activate-text">${t("wf_activate_prompt")} <strong>${B.esc(workflowName)}</strong></span>
      <button class="wf-activate-btn yes" id="wf-act-yes">${t("wf_activate_yes")}</button>
      <button class="wf-activate-btn no" id="wf-act-no">${t("wf_activate_no")}</button>
    `;

    const canvasWrap = canvas.parentElement;
    canvasWrap.appendChild(bar);

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
      await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active_workflow: workflowId }),
      });
      if (B.currentConfig) B.currentConfig.active_workflow = workflowId;
    } catch { /* */ }
  }

  async function deactivateWorkflow() {
    await setActiveWorkflow(null);
    updateActivateButton();
  }

  function updateActivateButton() {
    const btn = container.querySelector("#wf-btn-activate");
    if (!btn) return;
    const activeId = B.currentConfig?.active_workflow;
    if (activeId && activeId === currentWorkflowId) {
      btn.textContent = B.t("wf_deactivate");
      btn.classList.add("active");
      btn.onclick = deactivateWorkflow;
    } else if (currentWorkflowId && nodes.length) {
      btn.textContent = B.t("wf_activate");
      btn.classList.remove("active");
      btn.onclick = () => { setActiveWorkflow(currentWorkflowId); updateActivateButton(); };
    } else {
      btn.textContent = B.t("wf_activate");
      btn.classList.remove("active");
      btn.onclick = () => {};
    }
  }

  async function loadWorkflowPrompt() {
    toggleSamples();
  }

  function clearCanvas() {
    if (nodes.length && !confirm("Clear all nodes?")) return;
    nodes = [];
    edges = [];
    currentWorkflowId = null;
    selectedNode = null;
    closeConfig();
    const title = container.querySelector("#wf-title");
    if (title) title.textContent = "Untitled Workflow";
    draw();
  }

  /* ── Samples Gallery (shown when canvas is empty) ── */

  let galleryEl = null;

  async function showSamplesGallery() {
    if (nodes.length) return; // Canvas has nodes, skip gallery

    try {
      const res = await fetch("/api/workflows");
      if (!res.ok) return;
      const data = await res.json();
      const all = [...(data.samples || []), ...(data.saved || [])];
      if (!all.length) return;

      // Create gallery overlay on the canvas
      galleryEl = document.createElement("div");
      galleryEl.className = "wf-gallery";
      galleryEl.innerHTML = `
        <div class="wf-gallery-header">
          <div class="wf-gallery-title">Choose a Workflow</div>
          <div class="wf-gallery-sub">Select a template to start, or drag nodes from the palette to build your own</div>
        </div>
        <div class="wf-gallery-grid" id="wf-gallery-grid"></div>
      `;

      const grid = galleryEl.querySelector("#wf-gallery-grid");

      // Category icons for samples
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
        const nodeCount = (wf.nodes || []).length;
        card.innerHTML = `
          <div class="wf-gallery-card-icon">${icon}</div>
          <div class="wf-gallery-card-name">${B.esc(wf.name || wf.id)}</div>
          <div class="wf-gallery-card-desc">${B.esc(wf.description || "")}</div>
          <div class="wf-gallery-card-meta">${nodeCount} nodes</div>
        `;
        card.onclick = () => {
          galleryEl.remove();
          galleryEl = null;
          loadWorkflow(wf);
        };
        grid.appendChild(card);
      });

      // "Blank" card
      const blank = document.createElement("div");
      blank.className = "wf-gallery-card wf-gallery-card-blank";
      blank.innerHTML = `
        <div class="wf-gallery-card-icon">+</div>
        <div class="wf-gallery-card-name">Blank Canvas</div>
        <div class="wf-gallery-card-desc">Start from scratch</div>
      `;
      blank.onclick = () => { galleryEl.remove(); galleryEl = null; draw(); };
      grid.appendChild(blank);

      const canvasWrap = canvas.parentElement;
      canvasWrap.appendChild(galleryEl);
    } catch { /* silent */ }
  }

  function hideGallery() {
    if (galleryEl) { galleryEl.remove(); galleryEl = null; }
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
        if (msg.includes(kw.toLowerCase())) {
          return { workflowId: rule.workflow, reason: rule.reason };
        }
      }
    }
    return null;
  }

  function showRecommendBanner(rec) {
    // Remove existing banner
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
    chatEl.scrollTop = chatEl.scrollHeight;

    banner.querySelector("#wf-rec-use").onclick = async () => {
      banner.remove();
      // Load the workflow and switch to workflow view
      try {
        const res = await fetch(`/api/workflows/${rec.workflowId}`);
        if (res.ok) {
          const wf = await res.json();
          B.switchView("workflow");
          // Wait for init then load
          setTimeout(() => loadWorkflow(wf), 100);
        }
      } catch { /* */ }
    };

    banner.querySelector("#wf-rec-dismiss").onclick = () => banner.remove();

    // Auto-dismiss after 15s
    setTimeout(() => { if (banner.parentNode) banner.remove(); }, 15000);
  }

  // Expose for app.js
  B.workflow = { checkRecommendation, showRecommendBanner };

  /* ── Register ── */
  B.viewHooks.workflow = { onActivate: init };
})();
