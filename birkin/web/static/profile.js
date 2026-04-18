/* Birkin — Profile View (conversation import + user profile dashboard) */

(function () {
  const B = window.birkin;
  const $ = B.$;
  const esc = B.esc;
  let _initialized = false;
  let _pollTimer = null;

  function init() {
    const container = $("view-profile");
    if (!container) return;

    if (!_initialized) {
      container.innerHTML = buildHTML();
      bindEvents(container);
      _initialized = true;
    }
    loadProfile();
  }

  function t(key, vars) {
    let s = B.t ? B.t(key) : key;
    if (vars) {
      Object.entries(vars).forEach(([k, v]) => {
        s = s.replace("{" + k + "}", v);
      });
    }
    return s;
  }

  function buildHTML() {
    return `
      <div class="profile-container">
        <div class="profile-header">
          <h2 class="profile-title">${esc(t("my_profile"))}</h2>
          <div class="profile-header-actions">
            <button class="profile-btn" id="profile-import-btn">${esc(t("import_conversations"))}</button>
            <button class="profile-btn danger" id="profile-reset-btn">${esc(t("profile_reset"))}</button>
          </div>
        </div>

        <div class="profile-drop-zone" id="profile-drop-zone">
          <div class="profile-drop-icon">📁</div>
          <p class="profile-drop-title">${esc(t("import_drop_hint"))}</p>
          <p class="profile-drop-sub">${esc(t("import_drop_or"))}</p>
          <input type="file" accept=".json" class="profile-drop-input" id="profile-file-input">
          <div class="profile-progress" id="profile-progress" style="display:none">
            <div class="profile-progress-bar"><div class="profile-progress-fill" id="profile-progress-fill"></div></div>
            <p class="profile-progress-text" id="profile-progress-text"></p>
          </div>
        </div>

        <div id="profile-content"></div>
      </div>
    `;
  }

  function bindEvents(container) {
    const dropZone = container.querySelector("#profile-drop-zone");
    const fileInput = container.querySelector("#profile-file-input");
    const importBtn = container.querySelector("#profile-import-btn");
    const resetBtn = container.querySelector("#profile-reset-btn");

    // Drag and drop
    dropZone.addEventListener("dragover", (e) => {
      e.preventDefault();
      dropZone.classList.add("dragover");
    });
    dropZone.addEventListener("dragleave", () => {
      dropZone.classList.remove("dragover");
    });
    dropZone.addEventListener("drop", (e) => {
      e.preventDefault();
      dropZone.classList.remove("dragover");
      const files = e.dataTransfer.files;
      if (files.length > 0) uploadFile(files[0]);
    });

    // Click to select
    dropZone.addEventListener("click", (e) => {
      if (e.target === fileInput) return;
      fileInput.click();
    });
    fileInput.addEventListener("change", () => {
      if (fileInput.files.length > 0) uploadFile(fileInput.files[0]);
    });

    // Import button
    importBtn.addEventListener("click", () => fileInput.click());

    // Reset button
    resetBtn.addEventListener("click", async () => {
      if (!confirm(t("profile_reset_confirm"))) return;
      try {
        const res = await fetch("/api/profile", { method: "DELETE" });
        if (res.ok) {
          showToast(t("profile_reset"), "info");
          loadProfile();
        }
      } catch (err) {
        showToast(err.message, "error");
      }
    });
  }

  async function uploadFile(file) {
    if (!file.name.endsWith(".json")) {
      showToast("Only .json files supported", "error");
      return;
    }

    const dropZone = document.querySelector("#profile-drop-zone");
    const progress = document.querySelector("#profile-progress");
    const progressText = document.querySelector("#profile-progress-text");
    const progressFill = document.querySelector("#profile-progress-fill");

    dropZone.classList.add("importing");
    progress.style.display = "block";
    progressText.textContent = t("import_parsing");
    progressFill.style.width = "5%";

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("/api/profile/import", { method: "POST", body: formData });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Upload failed" }));
        throw new Error(err.detail || "Upload failed");
      }

      const data = await res.json();
      progressText.textContent = t("conversations_found", { count: data.conversations_found });
      progressFill.style.width = "15%";

      // Start polling for progress
      pollJobStatus(data.job_id);
    } catch (err) {
      dropZone.classList.remove("importing");
      progress.style.display = "none";
      showToast(err.message, "error");
    }
  }

  function pollJobStatus(jobId) {
    if (_pollTimer) clearInterval(_pollTimer);

    _pollTimer = setInterval(async () => {
      try {
        const res = await fetch(`/api/profile/import/${jobId}`);
        if (!res.ok) return;

        const job = await res.json();
        const progressFill = document.querySelector("#profile-progress-fill");
        const progressText = document.querySelector("#profile-progress-text");
        const dropZone = document.querySelector("#profile-drop-zone");

        if (job.status === "analyzing" && job.progress_total > 0) {
          const pct = 15 + (job.progress_current / job.progress_total) * 65;
          progressFill.style.width = pct + "%";
          progressText.textContent = t("import_analyzing") + " " + t("import_progress", {
            current: job.progress_current,
            total: job.progress_total,
          });
        } else if (job.status === "merging") {
          progressFill.style.width = "85%";
          progressText.textContent = t("import_merging");
        } else if (job.status === "compiling") {
          progressFill.style.width = "95%";
          progressText.textContent = t("import_compiling");
        } else if (job.status === "done") {
          clearInterval(_pollTimer);
          _pollTimer = null;
          progressFill.style.width = "100%";
          progressText.textContent = t("import_done");
          dropZone.classList.remove("importing");
          showToast(t("import_done"), "success");
          setTimeout(() => {
            document.querySelector("#profile-progress").style.display = "none";
            loadProfile();
          }, 1500);
        } else if (job.status === "error") {
          clearInterval(_pollTimer);
          _pollTimer = null;
          dropZone.classList.remove("importing");
          progressText.textContent = t("import_error");
          showToast(job.errors[0] || t("import_error"), "error");
        }
      } catch (err) {
        /* network error, keep polling */
      }
    }, 2000);
  }

  async function loadProfile() {
    const content = document.querySelector("#profile-content");
    if (!content) return;

    try {
      const res = await fetch("/api/profile");
      if (!res.ok) return;

      const profile = await res.json();

      if (!profile.exists) {
        content.innerHTML = `
          <div class="profile-empty">
            <div class="profile-empty-icon">👤</div>
            <p class="profile-empty-title">${esc(t("profile_empty"))}</p>
            <p class="profile-empty-desc">${esc(t("profile_empty_desc"))}</p>
          </div>
        `;
        return;
      }

      content.innerHTML = buildProfileCards(profile);
    } catch (err) {
      content.innerHTML = `<p style="color:var(--text-dim)">Failed to load profile</p>`;
    }
  }

  function buildProfileCards(p) {
    let html = '<div class="profile-grid">';

    // Role card
    if (p.job_role) {
      html += card(t("profile_job_role"), "👤", `<p class="profile-card-value">${esc(p.job_role)}</p>`);
    }

    // Expertise
    if (p.expertise_areas && p.expertise_areas.length) {
      html += card(t("profile_expertise"), "🎯", tagsHTML(p.expertise_areas, "expertise"));
    }

    // Interests
    if (p.interests && p.interests.length) {
      html += card(t("profile_interests"), "💡", tagsHTML(p.interests, "interest"));
    }

    // Projects
    if (p.active_projects && p.active_projects.length) {
      html += card(t("profile_projects"), "📂", tagsHTML(p.active_projects, "project"));
    }

    // Tools
    if (p.tools_and_tech && p.tools_and_tech.length) {
      html += card(t("profile_tools"), "🛠️", tagsHTML(p.tools_and_tech, "tool"));
    }

    // Communication Style
    if (p.communication_style) {
      html += card(t("profile_style"), "💬", `<p class="profile-card-value">${esc(p.communication_style)}</p>`);
    }

    // Decision Patterns
    if (p.decision_patterns && p.decision_patterns.length) {
      html += card(t("profile_patterns"), "🧭", listHTML(p.decision_patterns));
    }

    // Key People
    if (p.key_people && p.key_people.length) {
      html += card(t("profile_people"), "👥", tagsHTML(p.key_people, ""));
    }

    html += "</div>";
    return html;
  }

  function card(title, icon, bodyHTML) {
    return `
      <div class="profile-card">
        <div class="profile-card-header">
          <span class="profile-card-icon">${icon}</span>
          <h3 class="profile-card-title">${esc(title)}</h3>
        </div>
        ${bodyHTML}
      </div>
    `;
  }

  function tagsHTML(items, cls) {
    return `<div class="profile-tags">${items.map(i =>
      `<span class="profile-tag ${cls}">${esc(i)}</span>`
    ).join("")}</div>`;
  }

  function listHTML(items) {
    return `<ul class="profile-list">${items.map(i =>
      `<li>${esc(i)}</li>`
    ).join("")}</ul>`;
  }

  function showToast(message, type) {
    const el = document.createElement("div");
    el.className = `profile-toast ${type}`;
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 4000);
  }

  // Register view hook
  B.viewHooks.profile = { onActivate: init };
})();
