/* Birkin — Memory Graph (Canvas force-directed wiki visualizer, i18n-enabled) */

(function () {
  const B = window.birkin;
  const container = B.$("view-memory");
  const detailPanel = B.$("memory-detail");
  const detailTitle = B.$("memory-detail-title");
  const detailContent = B.$("memory-detail-content");
  const detailClose = B.$("memory-detail-close");
  const detailOverlay = B.$("memory-detail-overlay");
  let initialized = false;
  let canvas, ctx;
  let nodes = [], edges = [], orphans = new Set();
  let simRunning = false;
  let pan = { x: 0, y: 0 }, zoom = 1;
  let drag = null, hoveredNode = null;
  let searchTerm = "";

  function t(k) { return B.t(k); }

  const COLORS = {
    entities: "#2dd4bf",
    concepts: "#a78bfa",
    sessions: "#fbbf24",
    broken: "#ef4444",
    orphan: "#ef4444",
  };
  const NODE_R = 16;
  const FONT = '10px "D-DIN", Arial, sans-serif';

  function init() {
    if (initialized) { refresh(); return; }
    initialized = true;

    container.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "mem-container";

    const toolbar = document.createElement("div");
    toolbar.className = "mem-toolbar";
    toolbar.innerHTML = `
      <input class="mem-search" type="text" placeholder="${t("search_memory")}" id="mem-search-input" />
      <label class="mem-upload-btn" title="${t("mem_upload_title")}">
        <input type="file" id="mem-file-input" accept=".md,.txt,.csv,.xlsx,.xls,.pdf" style="display:none" />
        \u{1F4CE} ${t("mem_upload")}
      </label>
      <button class="mem-refresh" id="mem-auto-link" title="${t("mem_auto_link_title")}">\u{1F517}</button>
      <button class="mem-refresh" id="mem-summarize" title="${t("mem_summarize_title")}">\u{1F4E6}</button>
      <button class="mem-refresh" id="mem-refresh-btn">${t("refresh")}</button>
    `;
    wrap.appendChild(toolbar);

    const canvasWrap = document.createElement("div");
    canvasWrap.className = "mem-canvas-wrap";
    canvas = document.createElement("canvas");
    canvasWrap.appendChild(canvas);
    wrap.appendChild(canvasWrap);

    const legend = document.createElement("div");
    legend.className = "mem-legend";
    legend.innerHTML = `
      <span class="mem-legend-item"><span class="mem-legend-dot" style="background:${COLORS.entities}"></span> ${t("entities")}</span>
      <span class="mem-legend-item"><span class="mem-legend-dot" style="background:${COLORS.concepts}"></span> ${t("concepts")}</span>
      <span class="mem-legend-item"><span class="mem-legend-dot" style="background:${COLORS.sessions}"></span> ${t("sessions")}</span>
      <span class="mem-legend-item"><span class="mem-legend-dot" style="background:${COLORS.orphan};border:1px dashed rgba(239,68,68,0.5)"></span> ${t("orphan")}</span>
    `;
    wrap.appendChild(legend);

    container.appendChild(wrap);
    ctx = canvas.getContext("2d");

    toolbar.querySelector("#mem-search-input").oninput = (e) => { searchTerm = e.target.value.toLowerCase(); };
    toolbar.querySelector("#mem-refresh-btn").onclick = refresh;

    // File upload
    toolbar.querySelector("#mem-file-input").onchange = async (e) => {
      const file = e.target.files?.[0];
      if (!file) return;
      const formData = new FormData();
      formData.append("file", file);
      try {
        const res = await fetch("/api/wiki/upload", { method: "POST", body: formData });
        if (res.ok) { const data = await res.json(); alert(`${t("mem_uploaded")}: ${data.category}/${data.slug}`); refresh(); }
        else { const err = await res.json().catch(() => ({})); alert(err.detail || t("something_wrong")); }
      } catch { alert(t("network_error")); }
      e.target.value = "";
    };

    // Auto-link
    toolbar.querySelector("#mem-auto-link").onclick = async () => {
      try {
        const res = await fetch("/api/wiki/auto-link", { method: "POST" });
        if (res.ok) { const data = await res.json(); alert(`${t("mem_links_added")}: ${data.links_added}`); refresh(); }
      } catch { /* */ }
    };

    // Summarize old sessions
    toolbar.querySelector("#mem-summarize").onclick = async () => {
      try {
        const res = await fetch("/api/wiki/summarize", { method: "POST" });
        if (res.ok) { const data = await res.json(); alert(`${t("mem_summarized")}: ${data.summarized} ${t("mem_pages")}`); refresh(); }
      } catch { /* */ }
    };
    canvas.onmousedown = onMouseDown;
    canvas.onmousemove = onMouseMove;
    canvas.onmouseup = onMouseUp;
    canvas.onwheel = onWheel;
    canvas.ondblclick = onDblClick;

    detailClose.onclick = closeDetail;
    detailOverlay.onclick = closeDetail;

    resizeCanvas();
    window.addEventListener("resize", resizeCanvas);
    refresh();
  }

  function resizeCanvas() {
    if (!canvas) return;
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * devicePixelRatio;
    canvas.height = rect.height * devicePixelRatio;
    canvas.style.width = rect.width + "px";
    canvas.style.height = rect.height + "px";
    ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
    draw();
  }

  async function refresh() {
    try {
      const res = await fetch("/api/wiki/graph");
      if (!res.ok) { showEmpty(); return; }
      const data = await res.json();
      if (!data.nodes || data.nodes.length === 0) { showEmpty(); return; }

      orphans = new Set(data.orphans || []);
      const cx = (canvas?.width || 600) / devicePixelRatio / 2;
      const cy = (canvas?.height || 400) / devicePixelRatio / 2;

      nodes = data.nodes.map((n) => ({
        ...n,
        x: cx + (Math.random() - 0.5) * 200,
        y: cy + (Math.random() - 0.5) * 200,
        vx: 0, vy: 0,
      }));

      edges = data.edges.map((e) => ({
        source: nodes.find((n) => n.slug === e.source),
        target: nodes.find((n) => n.slug === e.target),
      })).filter((e) => e.source && e.target);

      const empty = container.querySelector(".mem-empty");
      if (empty) empty.remove();
      if (canvas) canvas.parentElement.style.display = "";

      startSimulation();
    } catch { showEmpty(); }
  }

  function showEmpty() {
    if (!container.querySelector(".mem-empty")) {
      const el = document.createElement("div");
      el.className = "mem-empty";
      el.innerHTML = `<div class="mem-empty-icon">\u{1F4DA}</div><div class="mem-empty-title">${t("no_memory_pages")}</div><div class="mem-empty-sub">${t("no_memory_desc")}</div>`;
      const c = container.querySelector(".mem-container");
      if (c) c.appendChild(el);
      if (canvas) canvas.parentElement.style.display = "none";
    }
  }

  function startSimulation() {
    if (simRunning) return;
    simRunning = true;
    let iter = 0;
    const maxIter = 300;

    function step() {
      if (iter++ > maxIter || !simRunning) { simRunning = false; draw(); return; }
      const cx = (canvas.width / devicePixelRatio) / 2;
      const cy = (canvas.height / devicePixelRatio) / 2;

      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          let dx = nodes[j].x - nodes[i].x, dy = nodes[j].y - nodes[i].y;
          let d = Math.sqrt(dx * dx + dy * dy) || 1;
          let f = 2000 / (d * d);
          nodes[i].vx -= dx / d * f; nodes[i].vy -= dy / d * f;
          nodes[j].vx += dx / d * f; nodes[j].vy += dy / d * f;
        }
      }

      edges.forEach((e) => {
        let dx = e.target.x - e.source.x, dy = e.target.y - e.source.y;
        let d = Math.sqrt(dx * dx + dy * dy) || 1;
        let f = (d - 80) * 0.02;
        e.source.vx += dx / d * f; e.source.vy += dy / d * f;
        e.target.vx -= dx / d * f; e.target.vy -= dy / d * f;
      });

      nodes.forEach((n) => {
        n.vx += (cx - n.x) * 0.005; n.vy += (cy - n.y) * 0.005;
        n.vx *= 0.9; n.vy *= 0.9;
        if (n !== drag?.node) { n.x += n.vx; n.y += n.vy; }
      });
      draw();
      requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function draw() {
    if (!ctx || !canvas) return;
    const w = canvas.width / devicePixelRatio, h = canvas.height / devicePixelRatio;
    ctx.save(); ctx.clearRect(0, 0, w, h);
    ctx.translate(pan.x, pan.y); ctx.scale(zoom, zoom);

    edges.forEach((e) => {
      ctx.beginPath(); ctx.moveTo(e.source.x, e.source.y); ctx.lineTo(e.target.x, e.target.y);
      const hl = searchTerm && (e.source.slug.toLowerCase().includes(searchTerm) || e.target.slug.toLowerCase().includes(searchTerm));
      ctx.strokeStyle = hl ? "rgba(240,240,250,0.4)" : "rgba(240,240,250,0.08)";
      ctx.lineWidth = hl ? 1.5 : 0.8; ctx.stroke();
    });

    nodes.forEach((n) => {
      const color = COLORS[n.category] || "rgba(240,240,250,0.3)";
      const isOrphan = orphans.has(n.slug);
      const isHovered = hoveredNode === n;
      const isMatch = searchTerm && n.slug.toLowerCase().includes(searchTerm);

      ctx.beginPath(); ctx.arc(n.x, n.y, isHovered ? NODE_R + 3 : NODE_R, 0, Math.PI * 2);
      if (isOrphan) { ctx.setLineDash([3, 3]); ctx.strokeStyle = COLORS.orphan; ctx.lineWidth = 2; }
      else { ctx.setLineDash([]); ctx.strokeStyle = isMatch ? "#fff" : color; ctx.lineWidth = isHovered || isMatch ? 2.5 : 1.5; }
      ctx.fillStyle = isHovered ? color + "40" : color + "18";
      ctx.fill(); ctx.stroke(); ctx.setLineDash([]);

      ctx.font = FONT; ctx.fillStyle = isHovered || isMatch ? "#f0f0fa" : "rgba(240,240,250,0.5)";
      ctx.textAlign = "center"; ctx.fillText(n.slug, n.x, n.y + NODE_R + 14);
    });
    ctx.restore();
  }

  function getNodeAt(mx, my) {
    const x = (mx - pan.x) / zoom, y = (my - pan.y) / zoom;
    for (const n of nodes) { if (Math.hypot(n.x - x, n.y - y) < NODE_R + 4) return n; }
    return null;
  }

  function onMouseDown(e) {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const node = getNodeAt(mx, my);
    if (node) { drag = { node, startX: mx, startY: my }; }
    else { drag = { pan: true, startX: mx, startY: my, px: pan.x, py: pan.y }; }
  }

  function onMouseMove(e) {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    if (drag?.node) { drag.node.x = (mx - pan.x) / zoom; drag.node.y = (my - pan.y) / zoom; drag.node.vx = 0; drag.node.vy = 0; draw(); }
    else if (drag?.pan) { pan.x = drag.px + (mx - drag.startX); pan.y = drag.py + (my - drag.startY); draw(); }
    else { const prev = hoveredNode; hoveredNode = getNodeAt(mx, my); canvas.style.cursor = hoveredNode ? "pointer" : "grab"; if (prev !== hoveredNode) draw(); }
  }

  function onMouseUp() { drag = null; }

  function onWheel(e) {
    e.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    const nz = Math.max(0.2, Math.min(5, zoom * delta));
    pan.x = mx - (mx - pan.x) * (nz / zoom); pan.y = my - (my - pan.y) * (nz / zoom);
    zoom = nz; draw();
  }

  function onDblClick(e) {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const node = getNodeAt(mx, my);
    if (node && node.category !== "broken") openDetail(node);
  }

  async function openDetail(node) {
    detailTitle.textContent = `${node.category}/${node.slug}`;
    detailContent.innerHTML = '<div class="thinking"><span></span><span></span><span></span></div>';
    detailPanel.classList.add("open");
    detailPanel.setAttribute("aria-hidden", "false");
    detailOverlay.classList.add("visible");

    try {
      const res = await fetch(`/api/wiki/pages/${node.category}/${node.slug}`);
      if (!res.ok) { detailContent.innerHTML = `<p style="color:rgba(239,68,68,0.8)">${t("page_not_found")}</p>`; return; }
      const data = await res.json();

      detailContent.innerHTML = `
        <div id="mem-page-view">${B.md(data.content)}</div>
        <div class="mem-detail-actions">
          <button class="ghost-btn" id="mem-edit-btn">${t("edit")}</button>
          <button class="ghost-btn secondary" id="mem-delete-btn">${t("delete")}</button>
        </div>
      `;

      B.$("mem-edit-btn").onclick = () => {
        detailContent.innerHTML = `
          <textarea class="mem-edit-area" id="mem-edit-textarea">${B.esc(data.content)}</textarea>
          <div class="mem-detail-actions">
            <button class="ghost-btn" id="mem-save-btn">${t("save")}</button>
            <button class="ghost-btn secondary" id="mem-cancel-btn">${t("cancel")}</button>
          </div>
        `;
        B.$("mem-save-btn").onclick = async () => {
          const newContent = B.$("mem-edit-textarea").value;
          await fetch(`/api/wiki/pages/${node.category}/${node.slug}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content: newContent }) });
          closeDetail(); refresh();
        };
        B.$("mem-cancel-btn").onclick = () => openDetail(node);
      };

      B.$("mem-delete-btn").onclick = async () => {
        if (!confirm(t("delete_confirm").replace("{slug}", node.slug))) return;
        await fetch(`/api/wiki/pages/${node.category}/${node.slug}`, { method: "DELETE" });
        closeDetail(); refresh();
      };
    } catch { detailContent.innerHTML = `<p style="color:rgba(239,68,68,0.8)">${t("failed_load_page")}</p>`; }
  }

  function closeDetail() {
    detailPanel.classList.remove("open");
    detailPanel.setAttribute("aria-hidden", "true");
    detailOverlay.classList.remove("visible");
  }

  B.viewHooks.memory = { onActivate: init };
})();
