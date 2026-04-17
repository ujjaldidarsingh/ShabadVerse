/**
 * Parkaran Reviewer — Display the library flow with translations, tags, connections.
 *
 * As of the unified UI (Batch 3), this module no longer runs on page load.
 * Instead, initReviewTab() is called by graph-explorer.js whenever the user
 * switches to the Review tab, pulling the current library from State.parkaran
 * (not localStorage) so both tabs share the same source of truth.
 */

const ReviewState = {
    parkaran: [],       // [{id, title, gurmukhi, raag, ang, tags, ...}]
    fullData: [],       // Full shabad data from /api/graph/shabads
    selectedIdx: -1,    // Currently selected shabad index
    selectedId: null,   // ID of selected shabad (survives reorder)
};

/* ===== INIT (called by tab switch) ===== */

async function initReviewTab() {
    const loadingEl = document.getElementById("reviewLoading");
    const emptyEl = document.getElementById("reviewEmpty");
    const contentEl = document.getElementById("reviewContent");

    // Read the current library directly from the shared State object
    const items = (typeof State !== "undefined" && State.parkaran) ? State.parkaran : [];

    if (!items.length) {
        loadingEl?.classList.add("hidden");
        contentEl?.classList.add("hidden");
        emptyEl?.classList.remove("hidden");
        return;
    }

    // If the review panel is already showing the same set, do nothing
    const sameLength = ReviewState.parkaran.length === items.length;
    const sameIds = sameLength && ReviewState.parkaran.every((p, i) => String(p.id) === String(items[i].id));
    if (sameIds && ReviewState.fullData.length) {
        emptyEl?.classList.add("hidden");
        loadingEl?.classList.add("hidden");
        contentEl?.classList.remove("hidden");
        return;
    }

    ReviewState.parkaran = [...items];
    ReviewState.selectedIdx = 0;

    emptyEl?.classList.add("hidden");
    contentEl?.classList.add("hidden");
    loadingEl?.classList.remove("hidden");

    try {
        const ids = ReviewState.parkaran
            .map((p) => parseInt(p.id, 10))
            .filter((id) => !isNaN(id));
        const response = await API.post("/api/graph/shabads", { ids });
        ReviewState.fullData = response.shabads || [];

        loadingEl?.classList.add("hidden");
        contentEl?.classList.remove("hidden");

        // Auto-select first shabad
        if (ReviewState.fullData.length > 0) {
            selectShabad(0);
        }
    } catch (err) {
        console.error("Review init error:", err);
        if (loadingEl) {
            loadingEl.innerHTML = `<div style="font-family:'IBM Plex Mono';color:#ef4444;font-size:10px;">ERROR: ${escapeHtml(err.message)}</div>`;
        }
    }
}

/* ===== DETAIL PANEL ===== */

function selectShabad(idx) {
    ReviewState.selectedIdx = idx;
    const s = ReviewState.fullData[idx];
    if (!s) return;

    // Track by ID so reordering the library doesn't change what's reviewed
    ReviewState.selectedId = s.id || s.shabad_id || null;

    // Highlight the matching row in the shared library list (left column)
    document.querySelectorAll("#libraryList .parkaran-sidebar-item").forEach((item) => {
        item.classList.toggle("selected", item.dataset.id === String(ReviewState.selectedId));
    });

    // Build detail
    const detail = document.getElementById("detailContent");

    const tagPills = (s.tags || [])
        .map((t) => `<span class="rv-tag">${escapeHtml(t)}</span>`)
        .join("");

    const gurmukhiLines = (s.gurmukhi_text || "").split("\n").filter(Boolean);
    const gurmukhiHtml = gurmukhiLines.length > 0
        ? gurmukhiLines.map((line) => `<div class="rv-gurbani-line">${escapeHtml(line)}</div>`).join("")
        : '<div class="rv-empty-text">Gurmukhi text not available</div>';

    const translationText = s.english_translation || "";

    detail.innerHTML = `
        <div class="rv-header">
            <span class="rv-position">${idx + 1} / ${ReviewState.fullData.length}</span>
            <span class="rv-meta">${escapeHtml([s.raag, s.writer, s.ang ? "Ang " + s.ang : ""].filter(Boolean).join(" / "))}</span>
        </div>

        ${s.rahao_gurmukhi ? `
        <div class="rv-rahao">
            <div class="rv-label">RAHAO</div>
            <div class="rv-rahao-gurmukhi">${escapeHtml(s.rahao_gurmukhi)}</div>
            ${s.rahao_english ? `<div class="rv-rahao-english">${escapeHtml(s.rahao_english)}</div>` : ""}
        </div>
        ` : ""}

        ${s.primary_theme || s.mood ? `
        <div class="rv-theme-mood">
            ${s.primary_theme ? `<div><div class="rv-label">THEME</div><div class="rv-value">${escapeHtml(s.primary_theme)}</div></div>` : ""}
            ${s.mood ? `<div><div class="rv-label">MOOD</div><div class="rv-value">${escapeHtml(s.mood)}</div></div>` : ""}
        </div>
        ` : ""}

        ${tagPills ? `<div class="rv-tags">${tagPills}</div>` : ""}

        ${s.brief_meaning ? `
        <div class="rv-summary-box">
            <div class="rv-label">SUMMARY</div>
            <div class="rv-summary-text">${escapeHtml(s.brief_meaning)}</div>
        </div>
        ` : ""}

        <div class="rv-section">
            <div class="rv-label">GURBANI</div>
            <div class="rv-gurbani">${gurmukhiHtml}</div>
        </div>

        ${translationText ? `
        <div class="rv-section">
            <div class="rv-label">TRANSLATION</div>
            <div class="rv-translation">${escapeHtml(translationText)}</div>
        </div>
        ` : ""}

        ${idx < ReviewState.fullData.length - 1 ? renderConnectionDetail(s, ReviewState.fullData[idx + 1], idx) : ""}

        <div class="rv-nav">
            <div>${idx > 0 ? `<button onclick="selectShabad(${idx - 1})" class="btn-secondary">&larr; PREVIOUS</button>` : ""}</div>
            <div>${idx < ReviewState.fullData.length - 1 ? `<button onclick="selectShabad(${idx + 1})" class="btn-secondary">NEXT &rarr;</button>` : ""}</div>
        </div>
    `;
}

function renderConnectionDetail(current, next, idx) {
    const shared = current.shared_tags_with_next || [];
    const strength = shared.length >= 3 ? "STRONG" : shared.length >= 1 ? "MODERATE" : "WEAK";
    const color = shared.length >= 3 ? "rgba(16,185,129,0.8)" : shared.length >= 1 ? "rgba(245,158,11,0.7)" : "rgba(107,95,82,0.7)";
    const bgColor = shared.length >= 3 ? "rgba(16,185,129,0.06)" : shared.length >= 1 ? "rgba(245,158,11,0.06)" : "rgba(107,95,82,0.06)";
    const borderColor = shared.length >= 3 ? "rgba(16,185,129,0.25)" : shared.length >= 1 ? "rgba(245,158,11,0.2)" : "rgba(107,95,82,0.2)";

    const nextGurmukhi = next.gurmukhi || "";
    const nextTitle = next.title || "Unknown";

    return `
        <div onclick="selectShabad(${idx + 1})" style="margin-top:20px;padding:12px 16px;background:${bgColor};border:1px solid ${borderColor};border-radius:6px;cursor:pointer;transition:all 0.15s;" onmouseover="this.style.borderColor='${color}';this.style.background='${bgColor.replace(/[\d.]+\)$/, (m) => (parseFloat(m) * 2).toFixed(2) + ')')}';" onmouseout="this.style.borderColor='${borderColor}';this.style.background='${bgColor}'">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                <span style="font-family:'IBM Plex Mono';font-size:8px;color:${color};font-weight:700;letter-spacing:0.1em;">TRANSITION TO ${idx + 2}</span>
                <span style="font-family:'IBM Plex Mono';font-size:8px;color:${color};opacity:0.7;">${strength} (${shared.length} shared tag${shared.length !== 1 ? "s" : ""})</span>
            </div>
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                <span style="font-family:'Noto Sans Gurmukhi';font-size:11px;color:rgba(251,191,36,0.4);">${escapeHtml(nextGurmukhi.substring(0, 30))}</span>
                <span style="font-family:'IBM Plex Mono';font-size:8px;color:#6b5f52;">${escapeHtml(nextTitle.substring(0, 30))}</span>
            </div>
            ${shared.length > 0
                ? `<div style="display:flex;flex-wrap:wrap;gap:4px;">${shared.map((t) => `<span style="font-family:'IBM Plex Mono';font-size:8px;color:${color};background:rgba(255,255,255,0.02);padding:2px 6px;border-radius:2px;border:1px solid ${borderColor};">${escapeHtml(t)}</span>`).join("")}</div>`
                : `<div style="font-family:'IBM Plex Mono';font-size:9px;color:rgba(107,95,82,0.5);">No shared thematic tags. Consider rearranging or adding a bridging shabad.</div>`
            }
        </div>
    `;
}

/* Save/library/delete logic now lives in graph-explorer.js — reviewer no
 * longer maintains its own library management UI. The unified LIBRARY button
 * in the left column opens a single manage-libraries modal that serves both
 * tabs.
 */
