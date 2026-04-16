/* Birkin Insights — Personal usage insights and patterns (SpaceX theme) */

(function () {
  const container = document.getElementById("view-insights");
  let loaded = false;

  function render() {
    container.innerHTML = `
      <div class="p2-panel">
        <div class="p2-title">PERSONAL INSIGHTS</div>
        <div class="p2-subtitle">THIS WEEK</div>
        <div class="p2-stats" id="insights-stats">
          <div class="p2-stat"><div class="p2-stat-value" id="ins-sessions">—</div><div class="p2-stat-label">SESSIONS</div></div>
          <div class="p2-stat"><div class="p2-stat-value" id="ins-events">—</div><div class="p2-stat-label">EVENTS</div></div>
          <div class="p2-stat"><div class="p2-stat-value" id="ins-tokens">—</div><div class="p2-stat-label">TOKENS</div></div>
          <div class="p2-stat"><div class="p2-stat-value" id="ins-cost">—</div><div class="p2-stat-label">COST</div></div>
        </div>
        <div class="p2-subtitle">PROVIDERS USED</div>
        <div id="ins-providers" class="p2-card"><div class="p2-card-body">—</div></div>
        <div class="p2-subtitle">TOP TOOLS</div>
        <div id="ins-tools" class="p2-card"><div class="p2-card-body">—</div></div>
        <div class="p2-subtitle">WEEKLY SUMMARY</div>
        <div id="ins-summary" class="p2-card"><div class="p2-card-body" style="white-space:pre-line">—</div></div>
        <div style="margin-top:20px"><button class="p2-btn" id="ins-refresh">REFRESH</button></div>
      </div>`;
    document.getElementById("ins-refresh").addEventListener("click", fetchInsights);
  }

  function getWeekRange() {
    const now = new Date();
    const day = now.getDay();
    const monday = new Date(now);
    monday.setDate(now.getDate() - (day === 0 ? 6 : day - 1));
    const sunday = new Date(monday);
    sunday.setDate(monday.getDate() + 6);
    return {
      start: monday.toISOString().slice(0, 10),
      end: sunday.toISOString().slice(0, 10),
    };
  }

  async function fetchInsights() {
    try {
      const { start, end } = getWeekRange();
      const res = await fetch("/api/observability/spend");
      const spend = await res.json();

      document.getElementById("ins-sessions").textContent = spend.session_count || 0;
      document.getElementById("ins-tokens").textContent = spend.total_tokens ? spend.total_tokens.toLocaleString() : "0";
      document.getElementById("ins-cost").textContent = "$" + (spend.total_cost_usd || 0).toFixed(4);
      document.getElementById("ins-events").textContent = "—";

      const providers = spend.by_provider || {};
      const provEl = document.getElementById("ins-providers");
      if (Object.keys(providers).length > 0) {
        provEl.innerHTML = '<div class="p2-card-body">' +
          Object.entries(providers).map(([k, v]) =>
            `<span class="p2-badge" style="margin-right:6px">${k.toUpperCase()}: ${v.toLocaleString()}</span>`
          ).join("") + '</div>';
      }

      document.getElementById("ins-summary").innerHTML =
        `<div class="p2-card-body" style="white-space:pre-line">Week of ${start} to ${end}\nTokens: ${(spend.total_tokens || 0).toLocaleString()}\nCost: $${(spend.total_cost_usd || 0).toFixed(4)}\nProviders: ${Object.keys(providers).join(", ") || "none"}</div>`;

    } catch (e) {
      document.getElementById("ins-sessions").textContent = "—";
    }
  }

  const observer = new MutationObserver(() => {
    if (container.classList.contains("active") && !loaded) {
      loaded = true;
      render();
      fetchInsights();
    }
  });
  observer.observe(container, { attributes: true, attributeFilter: ["class"] });
})();
