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
    const esc = window.birkin.esc;
    const list = document.getElementById("skills-list");
    try {
      const res = await fetch("/api/skills");
      if (!res.ok) throw new Error(res.statusText);
      const skills = await res.json();
      if (!Array.isArray(skills) || skills.length === 0) {
        list.innerHTML = '<div class="p2-empty"><div class="p2-empty-text">NO SKILLS INSTALLED</div></div>';
        return;
      }
      list.innerHTML = "";
      skills.forEach(s => {
        const card = document.createElement("div");
        card.className = "p2-card";
        card.innerHTML = `
          <div class="p2-card-header">
            <span class="p2-card-title">${esc(s.name)}</span>
            <div class="p2-toggle ${s.enabled ? "active" : ""}" data-skill="${esc(s.name)}"></div>
          </div>
          <div class="p2-card-body">${esc(s.description)}</div>
          <div class="p2-card-meta" style="margin-top:8px">
            V${esc(s.version)} &middot; ${s.tool_count} TOOLS &middot; TRIGGERS: ${esc(s.triggers.join(", ") || "NONE")}
          </div>`;
        card.querySelector(".p2-toggle").onclick = () => toggleSkill(s.name, !s.enabled);
        list.appendChild(card);
      });
    } catch (e) {
      list.innerHTML = '<div class="p2-empty"><div class="p2-empty-text">FAILED TO LOAD</div></div>';
    }
  }

  window.toggleSkill = async function (name, enabled) {
    try {
      const res = await fetch(`/api/skills/${name}/toggle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert(err.detail || "Failed to toggle skill");
        return;
      }
      fetchSkills();
    } catch {
      alert("Network error — failed to toggle skill");
    }
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
