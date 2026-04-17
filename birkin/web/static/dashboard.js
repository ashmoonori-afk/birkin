/* Birkin Dashboard — Observability metrics (SpaceX theme) */

(function () {
  const container = document.getElementById("view-dashboard");
  let loaded = false;

  function render() {
    container.innerHTML = `
      <div class="p2-panel">
        <div class="p2-title">OBSERVABILITY DASHBOARD</div>
        <div class="p2-hero" id="dash-hero">
          <div class="p2-hero-card"><div class="p2-hero-value" id="hero-tokens">0</div><div class="p2-hero-label">TOKENS SAVED</div><div class="p2-hero-sub">THIS WEEK</div></div>
          <div class="p2-hero-card"><div class="p2-hero-value" id="hero-automations">0</div><div class="p2-hero-label">AUTOMATIONS RUN</div><div class="p2-hero-sub">ALL TIME</div></div>
          <div class="p2-hero-card"><div class="p2-hero-value" id="hero-memory">0</div><div class="p2-hero-label">MEMORY PAGES</div><div class="p2-hero-sub"><span id="hero-memory-delta">+0</span> THIS WEEK</div></div>
        </div>
        <div class="p2-stats" id="dash-stats">
          <div class="p2-stat"><div class="p2-stat-value" id="dash-tokens">—</div><div class="p2-stat-label">TOTAL TOKENS</div></div>
          <div class="p2-stat"><div class="p2-stat-value" id="dash-cost">—</div><div class="p2-stat-label">COST (USD)</div></div>
          <div class="p2-stat"><div class="p2-stat-value" id="dash-latency">—</div><div class="p2-stat-label">AVG LATENCY</div></div>
          <div class="p2-stat"><div class="p2-stat-value" id="dash-errors">—</div><div class="p2-stat-label">ERROR RATE</div></div>
        </div>
        <div class="p2-subtitle">TOKEN SPEND BY PROVIDER</div>
        <div class="p2-bars" id="dash-provider-bars"></div>
        <div class="p2-subtitle">LATENCY DISTRIBUTION</div>
        <div class="p2-stats" id="dash-latency-detail">
          <div class="p2-stat"><div class="p2-stat-value" id="dash-p50">—</div><div class="p2-stat-label">P50 MS</div></div>
          <div class="p2-stat"><div class="p2-stat-value" id="dash-p95">—</div><div class="p2-stat-label">P95 MS</div></div>
          <div class="p2-stat"><div class="p2-stat-value" id="dash-max">—</div><div class="p2-stat-label">MAX MS</div></div>
          <div class="p2-stat"><div class="p2-stat-value" id="dash-spans">—</div><div class="p2-stat-label">TOTAL SPANS</div></div>
        </div>
        <div class="p2-subtitle">TOP ERRORS</div>
        <div id="dash-errors-list"></div>
        <div style="margin-top:20px"><button class="p2-btn" id="dash-refresh">REFRESH</button></div>
      </div>`;
    document.getElementById("dash-refresh").addEventListener("click", fetchAll);
  }

  async function fetchAll() {
    try {
      const [spend, latency, errors, hero] = await Promise.all([
        fetch("/api/observability/spend").then(r => r.json()),
        fetch("/api/observability/latency").then(r => r.json()),
        fetch("/api/observability/errors").then(r => r.json()),
        fetch("/api/observability/hero").then(r => r.json()),
      ]);

      // Hero metrics
      document.getElementById("hero-tokens").textContent = (hero.tokens_saved_this_week || 0).toLocaleString();
      document.getElementById("hero-automations").textContent = (hero.automations_run || 0).toLocaleString();
      document.getElementById("hero-memory").textContent = (hero.memory_pages_total || 0).toLocaleString();
      const delta = hero.memory_pages_delta_week || 0;
      document.getElementById("hero-memory-delta").textContent = (delta >= 0 ? "+" : "") + delta;

      document.getElementById("dash-tokens").textContent = spend.total_tokens.toLocaleString();
      document.getElementById("dash-cost").textContent = "$" + spend.total_cost_usd.toFixed(4);

      document.getElementById("dash-latency").textContent = latency.avg_ms ? Math.round(latency.avg_ms) + "ms" : "—";
      document.getElementById("dash-p50").textContent = latency.p50_ms ? Math.round(latency.p50_ms) : "—";
      document.getElementById("dash-p95").textContent = latency.p95_ms ? Math.round(latency.p95_ms) : "—";
      document.getElementById("dash-max").textContent = latency.max_ms ? Math.round(latency.max_ms) : "—";
      document.getElementById("dash-spans").textContent = latency.span_count || 0;

      document.getElementById("dash-errors").textContent =
        errors.total_traces ? (errors.error_rate * 100).toFixed(1) + "%" : "0%";

      // Provider bars
      const barsEl = document.getElementById("dash-provider-bars");
      const providers = spend.by_provider || {};
      const maxTokens = Math.max(...Object.values(providers), 1);
      if (Object.keys(providers).length === 0) {
        barsEl.innerHTML = '<div class="p2-empty-text">NO PROVIDER DATA</div>';
      } else {
        barsEl.innerHTML = Object.entries(providers).map(([name, tokens]) => {
          const pct = (tokens / maxTokens) * 100;
          return `<div class="p2-bar" style="height:${Math.max(pct, 5)}%"><div class="p2-bar-label">${name}</div></div>`;
        }).join("");
      }

      // Error list
      const errList = document.getElementById("dash-errors-list");
      if (errors.top_errors && errors.top_errors.length > 0) {
        errList.innerHTML = errors.top_errors.map(e =>
          `<div class="p2-card"><div class="p2-card-body" style="color:var(--danger)">${e}</div></div>`
        ).join("");
      } else {
        errList.innerHTML = '<div class="p2-card"><div class="p2-card-body">NO ERRORS</div></div>';
      }
    } catch (e) {
      document.getElementById("dash-tokens").textContent = "—";
    }
  }

  const observer = new MutationObserver(() => {
    if (container.classList.contains("active") && !loaded) {
      loaded = true;
      render();
      fetchAll();
    }
  });
  observer.observe(container, { attributes: true, attributeFilter: ["class"] });
})();
