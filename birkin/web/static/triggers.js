/* Birkin Triggers — CRUD for workflow triggers (SpaceX theme) */

(function () {
  const container = document.getElementById("view-triggers");
  let loaded = false;

  function render() {
    container.innerHTML = `
      <div class="p2-panel">
        <div class="p2-title">TRIGGERS</div>
        <div style="margin-bottom:16px">
          <button class="p2-btn" id="trigger-create-btn">+ NEW TRIGGER</button>
          <button class="p2-btn p2-btn--sm" id="trigger-refresh" style="margin-left:8px">REFRESH</button>
        </div>
        <div id="trigger-list"><div class="p2-loading">LOADING...</div></div>
        <div id="trigger-form-area" style="display:none">
          <div class="p2-subtitle">CREATE TRIGGER</div>
          <div class="p2-card">
            <label class="p2-card-meta">TYPE</label>
            <select id="tf-type" style="width:100%;margin:6px 0 12px;padding:8px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);color:var(--text);font-family:var(--font)">
              <option value="cron">CRON</option>
              <option value="file_watch">FILE WATCH</option>
              <option value="webhook">WEBHOOK</option>
              <option value="message">MESSAGE</option>
            </select>
            <label class="p2-card-meta">WORKFLOW ID</label>
            <input id="tf-workflow" placeholder="workflow-id" style="width:100%;margin:6px 0 12px;padding:8px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);color:var(--text);font-family:var(--font)" />
            <label class="p2-card-meta">CONFIG (JSON)</label>
            <textarea id="tf-config" rows="3" placeholder='{"expression":"*/5 * * * *"}' style="width:100%;margin:6px 0 12px;padding:8px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);color:var(--text);font-family:var(--font);resize:vertical"></textarea>
            <button class="p2-btn p2-btn--ok" id="tf-submit">CREATE</button>
            <button class="p2-btn p2-btn--sm" id="tf-cancel" style="margin-left:8px">CANCEL</button>
          </div>
        </div>
      </div>`;

    document.getElementById("trigger-create-btn").addEventListener("click", () => {
      // Reset form fields when opening
      document.getElementById("tf-type").selectedIndex = 0;
      document.getElementById("tf-workflow").value = "";
      document.getElementById("tf-config").value = "";
      document.getElementById("trigger-form-area").style.display = "block";
    });
    document.getElementById("tf-cancel").addEventListener("click", () => {
      document.getElementById("trigger-form-area").style.display = "none";
    });
    document.getElementById("tf-submit").addEventListener("click", createTrigger);
    document.getElementById("trigger-refresh").addEventListener("click", fetchTriggers);
  }

  async function fetchTriggers() {
    const esc = window.birkin.esc;
    const list = document.getElementById("trigger-list");
    try {
      const res = await fetch("/api/triggers");
      if (!res.ok) throw new Error(res.statusText);
      const triggers = await res.json();
      if (!Array.isArray(triggers) || triggers.length === 0) {
        list.innerHTML = '<div class="p2-empty"><div class="p2-empty-text">NO TRIGGERS CONFIGURED</div></div>';
        return;
      }
      list.innerHTML = "";
      triggers.forEach(t => {
        const card = document.createElement("div");
        card.className = "p2-card";
        card.innerHTML = `
          <div class="p2-card-header">
            <span class="p2-card-title">${esc(t.type.toUpperCase())}</span>
            <span class="p2-badge ${t.running ? "p2-badge--ok" : ""}">${t.running ? "RUNNING" : "STOPPED"}</span>
          </div>
          <div class="p2-card-body">
            <div class="p2-card-meta">WORKFLOW: ${esc(t.workflow_id)}</div>
            <div class="p2-card-meta" style="margin-top:4px">CONFIG: ${esc(JSON.stringify(t.config))}</div>
          </div>
          <div style="margin-top:10px;display:flex;gap:8px"></div>`;
        const actions = card.querySelector("div:last-child");
        const delBtn = document.createElement("button");
        delBtn.className = "p2-btn p2-btn--sm p2-btn--danger";
        delBtn.textContent = "DELETE";
        delBtn.onclick = () => deleteTrigger(t.id);
        const fireBtn = document.createElement("button");
        fireBtn.className = "p2-btn p2-btn--sm";
        fireBtn.textContent = "FIRE";
        fireBtn.onclick = () => fireTrigger(t.id);
        actions.append(delBtn, fireBtn);
        list.appendChild(card);
      });
    } catch (e) {
      list.innerHTML = '<div class="p2-empty"><div class="p2-empty-text">FAILED TO LOAD</div></div>';
    }
  }

  async function createTrigger() {
    let config;
    try {
      config = JSON.parse(document.getElementById("tf-config").value || "{}");
    } catch {
      alert("Invalid JSON in config field");
      return;
    }
    const wfId = document.getElementById("tf-workflow").value.trim();
    if (!wfId) { alert("Workflow ID is required"); return; }
    const body = {
      type: document.getElementById("tf-type").value,
      workflow_id: wfId,
      config,
    };
    try {
      const res = await fetch("/api/triggers", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert(err.detail || "Failed to create trigger");
        return;
      }
    } catch { alert("Network error"); return; }
    document.getElementById("trigger-form-area").style.display = "none";
    fetchTriggers();
  }

  window.deleteTrigger = async function (id) {
    try {
      const res = await fetch(`/api/triggers/${id}`, { method: "DELETE" });
      if (!res.ok) { const err = await res.json().catch(() => ({})); alert(err.detail || "Failed to delete"); return; }
      fetchTriggers();
    } catch { alert("Network error"); }
  };

  window.fireTrigger = async function (id) {
    try {
      const res = await fetch(`/api/triggers/${id}/fire`, { method: "POST" });
      if (!res.ok) { const err = await res.json().catch(() => ({})); alert(err.detail || "Failed to fire"); }
    } catch { alert("Network error"); }
  };

  const observer = new MutationObserver(() => {
    if (container.classList.contains("active") && !loaded) {
      loaded = true;
      render();
      fetchTriggers();
    }
  });
  observer.observe(container, { attributes: true, attributeFilter: ["class"] });
})();
