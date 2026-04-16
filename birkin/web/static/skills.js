/* Birkin Skills — List and toggle installed skills (SpaceX theme) */

(function () {
  const container = document.getElementById("view-skills");
  let loaded = false;

  function render() {
    container.innerHTML = `
      <div class="p2-panel">
        <div class="p2-title">INSTALLED SKILLS</div>
        <div id="skills-list"><div class="p2-loading">LOADING...</div></div>
      </div>`;
  }

  async function fetchSkills() {
    const list = document.getElementById("skills-list");
    try {
      const res = await fetch("/api/skills");
      const skills = await res.json();
      if (skills.length === 0) {
        list.innerHTML = '<div class="p2-empty"><div class="p2-empty-text">NO SKILLS INSTALLED</div></div>';
        return;
      }
      list.innerHTML = skills.map(s => `
        <div class="p2-card">
          <div class="p2-card-header">
            <span class="p2-card-title">${s.name}</span>
            <div class="p2-toggle ${s.enabled ? "active" : ""}" data-skill="${s.name}" onclick="toggleSkill('${s.name}', ${!s.enabled})"></div>
          </div>
          <div class="p2-card-body">${s.description}</div>
          <div class="p2-card-meta" style="margin-top:8px">
            V${s.version} &middot; ${s.tool_count} TOOLS &middot; TRIGGERS: ${s.triggers.join(", ") || "NONE"}
          </div>
        </div>
      `).join("");
    } catch (e) {
      list.innerHTML = '<div class="p2-empty"><div class="p2-empty-text">FAILED TO LOAD</div></div>';
    }
  }

  window.toggleSkill = async function (name, enabled) {
    await fetch(`/api/skills/${name}/toggle`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    });
    fetchSkills();
  };

  const observer = new MutationObserver(() => {
    if (container.classList.contains("active") && !loaded) {
      loaded = true;
      render();
      fetchSkills();
    }
  });
  observer.observe(container, { attributes: true, attributeFilter: ["class"] });
})();
