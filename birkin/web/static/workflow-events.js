/* Birkin Workflow — Canvas event handlers (mouse, keyboard, drag) */

(function () {
  const B = window.birkin;
  const S = B._wf;

  function canvasCoords(e) {
    const rect = S.canvas.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  function worldCoords(cx, cy) {
    return { x: (cx - S.pan.x) / S.zoom, y: (cy - S.pan.y) / S.zoom };
  }

  function getNodeAt(wx, wy) {
    for (let i = S.nodes.length - 1; i >= 0; i--) {
      const n = S.nodes[i];
      if (wx >= n.x && wx <= n.x + S.NODE_W && wy >= n.y && wy <= n.y + S.NODE_H) return n;
    }
    return null;
  }

  function isOnOutputPort(n, wx, wy) {
    return Math.hypot(wx - (n.x + S.NODE_W), wy - (n.y + S.NODE_H / 2)) < S.PORT_R + 4;
  }

  function isOnDeleteBtn(n, wx, wy) {
    return Math.hypot(wx - (n.x + S.NODE_W - 8), wy - (n.y + 8)) < 10;
  }

  function addNode(type, x, y) {
    S.nodeIdCounter++;
    const info = S.getPaletteFlat()[type] || { icon: "?", label: type, color: "nc-io" };
    S.nodes.push({
      id: `n${S.nodeIdCounter}`,
      type,
      x: x - S.NODE_W / 2,
      y: y - S.NODE_H / 2,
      config: {},
      label: info.label,
    });
    S.draw();
  }

  function deleteNode(nodeId) {
    S.nodes = S.nodes.filter((n) => n.id !== nodeId);
    S.edges = S.edges.filter((e) => e.from !== nodeId && e.to !== nodeId);
    if (S.selectedNode?.id === nodeId) { S.selectedNode = null; S.closeConfig(); }
    S.draw();
  }

  // Mouse handlers
  function onCanvasMouseDown(e) {
    const c = canvasCoords(e);
    const w = worldCoords(c.x, c.y);
    const node = getNodeAt(w.x, w.y);

    if (node) {
      if (isOnDeleteBtn(node, w.x, w.y)) { deleteNode(node.id); return; }
      if (isOnOutputPort(node, w.x, w.y)) {
        S.connecting = { from: node.id, startX: node.x + S.NODE_W, startY: node.y + S.NODE_H / 2, curX: c.x, curY: c.y };
        return;
      }
      S.selectedNode = node;
      S.drag = { node, offX: w.x - node.x, offY: w.y - node.y };
      S.showConfig(node);
    } else {
      S.selectedNode = null;
      S.closeConfig();
      S.drag = { pan: true, startX: c.x, startY: c.y, px: S.pan.x, py: S.pan.y };
    }
    S.draw();
  }

  function onCanvasMouseMove(e) {
    const c = canvasCoords(e);
    const w = worldCoords(c.x, c.y);

    if (S.connecting) {
      S.connecting.curX = c.x;
      S.connecting.curY = c.y;
      S.draw();
      return;
    }

    if (S.drag?.node) {
      S.drag.node.x = w.x - S.drag.offX;
      S.drag.node.y = w.y - S.drag.offY;
      S.draw();
    } else if (S.drag?.pan) {
      S.pan.x = S.drag.px + (c.x - S.drag.startX);
      S.pan.y = S.drag.py + (c.y - S.drag.startY);
      S.draw();
    } else {
      const prev = S.hoveredNode;
      S.hoveredNode = getNodeAt(w.x, w.y);
      if (S.hoveredNode) {
        S.canvas.style.cursor = isOnOutputPort(S.hoveredNode, w.x, w.y) ? "crosshair" : "move";
      } else {
        S.canvas.style.cursor = "default";
      }
      if (prev !== S.hoveredNode) S.draw();
    }
  }

  function onCanvasMouseUp(e) {
    if (S.connecting) {
      const c = canvasCoords(e);
      const w = worldCoords(c.x, c.y);
      const target = getNodeAt(w.x, w.y);
      if (target && target.id !== S.connecting.from) {
        const exists = S.edges.some((ed) => ed.from === S.connecting.from && ed.to === target.id);
        if (!exists) {
          S.edges.push({ from: S.connecting.from, to: target.id });
        }
      }
      S.connecting = null;
      S.draw();
    }
    S.drag = null;
  }

  function onCanvasDblClick(e) {
    const c = canvasCoords(e);
    const w = worldCoords(c.x, c.y);
    const node = getNodeAt(w.x, w.y);
    if (node) { S.selectedNode = node; S.showConfig(node); S.draw(); }
  }

  function onCanvasWheel(e) {
    e.preventDefault();
    const c = canvasCoords(e);
    const delta = e.deltaY > 0 ? 0.92 : 1.08;
    const nz = Math.max(0.3, Math.min(4, S.zoom * delta));
    S.pan.x = c.x - (c.x - S.pan.x) * (nz / S.zoom);
    S.pan.y = c.y - (c.y - S.pan.y) * (nz / S.zoom);
    S.zoom = nz;
    S.draw();
  }

  // Palette drag
  function onPaletteDragStart(e) {
    const item = e.target.closest(".wf-palette-item");
    if (!item) return;
    e.preventDefault();
    const type = item.dataset.type;
    const rect = S.canvas.getBoundingClientRect();

    const onMove = (ev) => {
      S.canvas.style.cursor = "copy";
      S.draw();
      const mx = ev.clientX - rect.left;
      const my = ev.clientY - rect.top;
      S.drawGhostNode(mx, my, type);
    };

    const onUp = (ev) => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      S.canvas.style.cursor = "default";
      const mx = ev.clientX - rect.left;
      const my = ev.clientY - rect.top;
      if (mx > 0 && my > 0) {
        addNode(type, (mx - S.pan.x) / S.zoom, (my - S.pan.y) / S.zoom);
      }
      S.draw();
    };

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }

  // Expose
  S.addNode = addNode;
  S.deleteNode = deleteNode;
  S.onCanvasMouseDown = onCanvasMouseDown;
  S.onCanvasMouseMove = onCanvasMouseMove;
  S.onCanvasMouseUp = onCanvasMouseUp;
  S.onCanvasDblClick = onCanvasDblClick;
  S.onCanvasWheel = onCanvasWheel;
  S.onPaletteDragStart = onPaletteDragStart;
})();
