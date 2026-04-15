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

    // Highlight the matching row in the shared library list (left column)
    document.querySelectorAll("#libraryList .parkaran-sidebar-item").forEach((item, i) => {
        item.classList.toggle("selected", i === idx);
    });

    // Build detail
    const detail = document.getElementById("detailContent");

    const tagPills = (s.tags || [])
        .map((t) => `<span style="font-family:'IBM Plex Mono';font-size:11px;color:rgba(245,158,11,0.5);background:rgba(245,158,11,0.06);padding:2px 8px;border-radius:3px;border:1px solid rgba(245,158,11,0.08);">${escapeHtml(t)}</span>`)
        .join("");

    // Format Gurmukhi text with line breaks
    const gurmukhiLines = (s.gurmukhi_text || "").split("\n").filter(Boolean);
    const gurmukhiHtml = gurmukhiLines.length > 0
        ? gurmukhiLines.map((line) => `<div style="margin-bottom:6px;">${escapeHtml(line)}</div>`).join("")
        : '<div style="color:#4a3f35;font-style:italic;">Gurmukhi text not available</div>';

    // Format English translation
    const translationText = s.english_translation || "";

    detail.innerHTML = `
        <!-- Header -->
        <div style="margin-bottom:20px;">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                <span style="font-family:'IBM Plex Mono';font-size:9px;color:rgba(245,158,11,0.3);font-weight:700;">${idx + 1} / ${ReviewState.fullData.length}</span>
                ${s.is_repertoire ? '<span style="font-family:\'IBM Plex Mono\';font-size:8px;color:rgba(245,158,11,0.5);border:1px solid rgba(245,158,11,0.15);padding:1px 5px;border-radius:2px;">&#9733; REPERTOIRE</span>' : ""}
            </div>
            <div style="font-family:'IBM Plex Mono';font-size:9px;color:#6b5f52;">
                ${escapeHtml([s.raag, s.writer, s.ang ? "Ang " + s.ang : ""].filter(Boolean).join(" / "))}
            </div>
        </div>

        <!-- Rahao / Core verse -->
        ${s.rahao_gurmukhi ? `
        <div style="margin-bottom:20px;padding:12px 16px;background:rgba(245,158,11,0.03);border-left:2px solid rgba(245,158,11,0.2);border-radius:0 4px 4px 0;">
            <div style="font-family:'IBM Plex Mono';font-size:8px;color:rgba(245,158,11,0.35);letter-spacing:0.1em;margin-bottom:6px;">RAHAO</div>
            <div style="font-family:'Noto Serif Gurmukhi','Noto Sans Gurmukhi','GurbaniWeb';font-size:20px;color:#f5e6c8;line-height:1.8;">${escapeHtml(s.rahao_gurmukhi)}</div>
            ${s.rahao_english ? `<div style="font-family:'IBM Plex Mono';font-size:13px;color:#8a7d6c;margin-top:6px;line-height:1.5;">${escapeHtml(s.rahao_english)}</div>` : ""}
        </div>
        ` : ""}

        <!-- Theme & Mood -->
        ${s.primary_theme || s.mood ? `
        <div style="margin-bottom:16px;display:flex;gap:16px;">
            ${s.primary_theme ? `<div><div style="font-family:'IBM Plex Mono';font-size:8px;color:#4a3f35;letter-spacing:0.05em;margin-bottom:2px;">THEME</div><div style="font-family:'IBM Plex Mono';font-size:13px;color:#a89b8a;">${escapeHtml(s.primary_theme)}</div></div>` : ""}
            ${s.mood ? `<div><div style="font-family:'IBM Plex Mono';font-size:8px;color:#4a3f35;letter-spacing:0.05em;margin-bottom:2px;">MOOD</div><div style="font-family:'IBM Plex Mono';font-size:13px;color:#a89b8a;">${escapeHtml(s.mood)}</div></div>` : ""}
        </div>
        ` : ""}

        <!-- Tags -->
        ${tagPills ? `<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:20px;">${tagPills}</div>` : ""}

        <!-- Brief meaning -->
        ${s.brief_meaning ? `
        <div style="margin-bottom:20px;padding:10px 14px;background:rgba(255,255,255,0.015);border-radius:4px;border:1px solid rgba(255,255,255,0.03);">
            <div style="font-family:'IBM Plex Mono';font-size:8px;color:#4a3f35;letter-spacing:0.05em;margin-bottom:4px;">SUMMARY</div>
            <div style="font-family:'IBM Plex Mono';font-size:13px;color:#a89b8a;line-height:1.6;">${escapeHtml(s.brief_meaning)}</div>
        </div>
        ` : ""}

        <!-- Full Gurmukhi text -->
        <div style="margin-bottom:20px;">
            <div style="font-family:'IBM Plex Mono';font-size:8px;color:#4a3f35;letter-spacing:0.05em;margin-bottom:8px;">GURBANI</div>
            <div style="font-family:'Noto Serif Gurmukhi','Noto Sans Gurmukhi','GurbaniWeb';font-size:20px;color:rgba(245,230,200,0.7);line-height:2;">${gurmukhiHtml}</div>
        </div>

        <!-- English translation -->
        ${translationText ? `
        <div style="margin-bottom:20px;">
            <div style="font-family:'IBM Plex Mono';font-size:8px;color:#4a3f35;letter-spacing:0.05em;margin-bottom:8px;">TRANSLATION</div>
            <div style="font-family:'IBM Plex Mono';font-size:13px;color:#8a7d6c;line-height:1.8;">${escapeHtml(translationText)}</div>
        </div>
        ` : ""}

        <!-- Connection to next -->
        ${idx < ReviewState.fullData.length - 1 ? renderConnectionDetail(s, ReviewState.fullData[idx + 1], idx) : ""}

        <!-- Nav buttons -->
        <div style="display:flex;gap:8px;margin-top:24px;padding-top:16px;border-top:1px solid rgba(255,255,255,0.03);">
            ${idx > 0 ? `<button onclick="selectShabad(${idx - 1})" class="btn-ghost">&larr; PREVIOUS</button>` : ""}
            ${idx < ReviewState.fullData.length - 1 ? `<button onclick="selectShabad(${idx + 1})" class="btn-secondary">NEXT &rarr;</button>` : ""}
        </div>
    `;
}

function renderConnectionDetail(current, next, idx) {
    const shared = current.shared_tags_with_next || [];
    const strength = shared.length >= 3 ? "STRONG" : shared.length >= 1 ? "MODERATE" : "WEAK";
    const color = shared.length >= 3 ? "rgba(16,185,129,0.6)" : shared.length >= 1 ? "rgba(245,158,11,0.5)" : "rgba(107,95,82,0.5)";
    const bgColor = shared.length >= 3 ? "rgba(16,185,129,0.03)" : shared.length >= 1 ? "rgba(245,158,11,0.03)" : "rgba(107,95,82,0.03)";
    const borderColor = shared.length >= 3 ? "rgba(16,185,129,0.15)" : shared.length >= 1 ? "rgba(245,158,11,0.1)" : "rgba(107,95,82,0.1)";

    const nextGurmukhi = next.gurmukhi || "";
    const nextTitle = next.title || "Unknown";

    return `
        <div style="margin-top:20px;padding:12px 16px;background:${bgColor};border:1px solid ${borderColor};border-radius:6px;">
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
