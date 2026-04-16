/* Birkin Approvals — Pending action review queue (SpaceX theme) */

(function () {
  const container = document.getElementById("view-approvals");
  let loaded = false;

  function render() {
    container.innerHTML = `
      <div class="p2-panel">
        <div class="p2-title">APPROVAL QUEUE</div>
        <div style="margin-bottom:16px">
          <button class="p2-btn p2-btn--sm" id="approvals-refresh">REFRESH</button>
        </div>
        <div id="approvals-list"><div class="p2-loading">LOADING...</div></div>
      </div>`;
    document.getElementById("approvals-refresh").addEventListener("click", fetchApprovals);
  }

  async function fetchApprovals() {
    const list = document.getElementById("approvals-list");
    try {
      const res = await fetch("/api/approvals/pending");
      const actions = await res.json();
      if (actions.length === 0) {
        list.innerHTML = '<div class="p2-empty"><div class="p2-empty-text">NO PENDING APPROVALS</div></div>';
        return;
      }
      list.innerHTML = actions.map(a => `
        <div class="p2-card">
          <div class="p2-card-header">
            <span class="p2-card-title">${a.action_type.toUpperCase()}</span>
            <span class="p2-badge p2-badge--warn">${a.estimated_impact.toUpperCase()}</span>
          </div>
          <div class="p2-card-body">${a.summary}</div>
          <div class="p2-card-meta" style="margin-top:6px">
            ${a.reversible ? "REVERSIBLE" : "IRREVERSIBLE"} &middot; ${a.created_at.slice(0, 19)}
          </div>
          <div style="margin-top:12px;display:flex;gap:8px">
            <button class="p2-btn p2-btn--ok" onclick="approveAction('${a.id}')">APPROVE</button>
            <button class="p2-btn p2-btn--danger" onclick="rejectAction('${a.id}')">REJECT</button>
          </div>
        </div>
      `).join("");
    } catch (e) {
      list.innerHTML = '<div class="p2-empty"><div class="p2-empty-text">FAILED TO LOAD</div></div>';
    }
  }

  window.approveAction = async function (id) {
    await fetch(`/api/approvals/${id}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    fetchApprovals();
  };

  window.rejectAction = async function (id) {
    await fetch(`/api/approvals/${id}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    fetchApprovals();
  };

  const observer = new MutationObserver(() => {
    if (container.classList.contains("active") && !loaded) {
      loaded = true;
      render();
      fetchApprovals();
    }
  });
  observer.observe(container, { attributes: true, attributeFilter: ["class"] });
})();
