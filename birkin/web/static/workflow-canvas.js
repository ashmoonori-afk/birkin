/* Birkin Workflow — Canvas drawing functions */

(function () {
  const B = window.birkin;
  const S = B._wf;

  function roundRect(c, x, y, w, h, r) {
    c.beginPath();
    c.moveTo(x + r, y);
    c.lineTo(x + w - r, y); c.quadraticCurveTo(x + w, y, x + w, y + r);
    c.lineTo(x + w, y + h - r); c.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    c.lineTo(x + r, y + h); c.quadraticCurveTo(x, y + h, x, y + h - r);
    c.lineTo(x, y + r); c.quadraticCurveTo(x, y, x + r, y);
    c.closePath();
  }

  function drawNode(n) {
    const ctx = S.ctx;
    const info = S.getPaletteFlat()[n.type] || { icon: "?", label: n.type, color: "nc-io" };
    const isSelected = S.selectedNode === n;
    const isHovered = S.hoveredNode === n;

    // Background
    ctx.fillStyle = isSelected ? "rgba(240, 240, 250, 0.12)" : isHovered ? "rgba(240, 240, 250, 0.08)" : "rgba(240, 240, 250, 0.04)";
    ctx.strokeStyle = isSelected ? "rgba(240, 240, 250, 0.5)" : "rgba(240, 240, 250, 0.15)";
    roundRect(ctx, n.x, n.y, S.NODE_W, S.NODE_H, 8);
    ctx.fill(); ctx.stroke();

    // Color accent bar
    const colors = { "nc-io": "#4f9cf7", "nc-ai": "#a855f7", "nc-tool": "#22c55e", "nc-memory": "#f59e0b", "nc-control": "#ec4899", "nc-gate": "#ef4444", "nc-platform": "#06b6d4" };
    ctx.fillStyle = colors[info.color] || "#666";
    ctx.fillRect(n.x, n.y, 3, S.NODE_H);

    // Icon & label
    ctx.font = '16px serif';
    ctx.fillStyle = "rgba(240, 240, 250, 0.9)";
    ctx.textBaseline = "middle";
    ctx.textAlign = "left";
    ctx.fillText(info.icon, n.x + 10, n.y + S.NODE_H / 2);
    ctx.font = '11px "D-DIN", Arial, sans-serif';
    ctx.fillStyle = "rgba(240, 240, 250, 0.75)";
    const label = n.config?.label || n.label || info.label;
    ctx.fillText(label.slice(0, 16), n.x + 32, n.y + S.NODE_H / 2);

    // Output port
    ctx.beginPath();
    ctx.arc(n.x + S.NODE_W, n.y + S.NODE_H / 2, S.PORT_R, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(240, 240, 250, 0.2)";
    ctx.fill();
    ctx.strokeStyle = "rgba(240, 240, 250, 0.3)";
    ctx.stroke();

    // Input port
    ctx.beginPath();
    ctx.arc(n.x, n.y + S.NODE_H / 2, S.PORT_R, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(240, 240, 250, 0.2)";
    ctx.fill();
    ctx.strokeStyle = "rgba(240, 240, 250, 0.3)";
    ctx.stroke();

    // Delete button (hover only)
    if (isHovered || isSelected) {
      ctx.fillStyle = "rgba(239, 68, 68, 0.7)";
      ctx.beginPath();
      ctx.arc(n.x + S.NODE_W - 8, n.y + 8, 6, 0, Math.PI * 2);
      ctx.fill();
      ctx.font = '10px Arial'; ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText("\u00D7", n.x + S.NODE_W - 8, n.y + 8);
    }
  }

  function drawEdge(from, to, label) {
    const ctx = S.ctx;
    const x1 = from.x + S.NODE_W, y1 = from.y + S.NODE_H / 2;
    const x2 = to.x, y2 = to.y + S.NODE_H / 2;
    const cpx = (x1 + x2) / 2;

    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.bezierCurveTo(cpx, y1, cpx, y2, x2, y2);
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
    const ctx = S.ctx;
    ctx.save();
    ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
    ctx.globalAlpha = 0.5;
    const info = S.getPaletteFlat()[type] || { icon: "?", label: type };
    ctx.fillStyle = "rgba(240, 240, 250, 0.1)";
    ctx.strokeStyle = "rgba(240, 240, 250, 0.3)";
    roundRect(ctx, mx - S.NODE_W / 2, my - S.NODE_H / 2, S.NODE_W, S.NODE_H, 8);
    ctx.fill(); ctx.stroke();
    ctx.font = '16px serif'; ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(info.icon, mx, my);
    ctx.restore();
  }

  function resizeCanvas() {
    if (!S.canvas) return;
    const rect = S.canvas.parentElement.getBoundingClientRect();
    S.canvas.width = rect.width * devicePixelRatio;
    S.canvas.height = rect.height * devicePixelRatio;
    S.canvas.style.width = rect.width + "px";
    S.canvas.style.height = rect.height + "px";
    draw();
  }

  function draw() {
    if (!S.ctx) return;
    const canvas = S.canvas;
    const ctx = S.ctx;
    const w = canvas.width / devicePixelRatio;
    const h = canvas.height / devicePixelRatio;
    ctx.save();
    ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.save();
    ctx.translate(S.pan.x, S.pan.y);
    ctx.scale(S.zoom, S.zoom);

    // Draw edges
    S.edges.forEach((e) => {
      const from = S.nodes.find((n) => n.id === e.from);
      const to = S.nodes.find((n) => n.id === e.to);
      if (!from || !to) return;
      drawEdge(from, to, e.label);
    });

    // Draw connecting line (convert viewport coords to world coords)
    if (S.connecting) {
      ctx.beginPath();
      ctx.moveTo(S.connecting.startX, S.connecting.startY);
      const mx = (S.connecting.curX - S.pan.x) / S.zoom;
      const my = (S.connecting.curY - S.pan.y) / S.zoom;
      ctx.lineTo(mx, my);

      ctx.strokeStyle = "rgba(240, 240, 250, 0.4)";
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 4]);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Draw nodes
    S.nodes.forEach((n) => drawNode(n));

    ctx.restore();
    ctx.restore();
  }

  // Expose
  S.draw = draw;
  S.resizeCanvas = resizeCanvas;
  S.drawGhostNode = drawGhostNode;
})();
