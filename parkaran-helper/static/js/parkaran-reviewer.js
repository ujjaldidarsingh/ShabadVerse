/**
 * Parkaran Reviewer — Display parkaran flow with translations, tags, connections.
 * No AI required. All data comes from the precomputed taxonomy + graph.
 */

const ReviewState = {
    parkaran: [],       // [{id, title, gurmukhi, raag, ang, tags, ...}]
    fullData: [],       // Full shabad data from /api/graph/shabads
    selectedIdx: -1,    // Currently selected shabad index
};

/* ===== INIT ===== */

async function init() {
    const loadingEl = document.getElementById("reviewLoading");
    const emptyEl = document.getElementById("reviewEmpty");
    const contentEl = document.getElementById("reviewContent");
    const countEl = document.getElementById("reviewCount");

    try {
        // Load parkaran from localStorage (set by explorer's sendToReview)
        const stored = localStorage.getItem("reviewParkaran");
        if (!stored) {
            loadingEl.classList.add("hidden");
            emptyEl.classList.remove("hidden");
            return;
        }

        ReviewState.parkaran = JSON.parse(stored);
        if (!ReviewState.parkaran.length) {
            loadingEl.classList.add("hidden");
            emptyEl.classList.remove("hidden");
            return;
        }

        countEl.textContent = `${ReviewState.parkaran.length} SHABADS`;

        // Display parkaran name if available
        const parkaranName = localStorage.getItem("reviewParkaranName");
        const titleEl = document.getElementById("reviewTitle");
        if (parkaranName && titleEl) {
            titleEl.textContent = parkaranName;
        }

        // Fetch full data for all shabads in one call
        const ids = ReviewState.parkaran.map((p) => parseInt(p.id, 10)).filter((id) => !isNaN(id));
        const response = await API.post("/api/graph/shabads", { ids });
        ReviewState.fullData = response.shabads || [];

        // Show content
        loadingEl.classList.add("hidden");
        contentEl.classList.remove("hidden");
        contentEl.style.display = "flex";

        renderFlow();

        // Auto-select first shabad
        if (ReviewState.fullData.length > 0) {
            selectShabad(0);
        }
    } catch (err) {
        console.error("Review init error:", err);
        loadingEl.innerHTML = `<div style="font-family:'IBM Plex Mono';color:#ef4444;font-size:10px;">ERROR: ${escapeHtml(err.message)}</div>`;
    }
}

/* ===== FLOW LIST (left panel) ===== */

function renderFlow() {
    const container = document.getElementById("flowList");
    let html = "";

    ReviewState.fullData.forEach((s, i) => {
        const isSelected = i === ReviewState.selectedIdx;
        const isRep = s.is_repertoire;
        const gurmukhi = s.gurmukhi || "";
        const title = s.title || "Unknown";

        // Shabad card
        html += `
            <div class="reviewer-flow-item ${isSelected ? "selected" : ""}" onclick="selectShabad(${i})" data-idx="${i}">
                <div style="display:flex;align-items:flex-start;gap:8px;">
                    <span style="font-family:'IBM Plex Mono';color:rgba(245,158,11,0.25);font-size:11px;width:14px;flex-shrink:0;padding-top:2px;">${i + 1}</span>
                    <div style="flex:1;min-width:0;">
                        ${gurmukhi ? `<div style="font-family:'Noto Sans Gurmukhi','GurbaniWeb';color:${isSelected ? "#f5e6c8" : "rgba(245,230,200,0.5)"};font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${isRep ? "&#9733; " : ""}${escapeHtml(gurmukhi.substring(0, 35))}</div>` : ""}
                        <div style="font-family:'IBM Plex Mono';color:#6b5f52;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(title.substring(0, 40))}</div>
                        <div style="display:flex;flex-wrap:wrap;gap:2px;margin-top:3px;">
                            ${(s.tags || []).slice(0, 3).map((t) => `<span style="font-family:'IBM Plex Mono';font-size:10px;color:rgba(245,158,11,0.35);background:rgba(245,158,11,0.04);padding:1px 4px;border-radius:2px;">${escapeHtml(t)}</span>`).join("")}
                        </div>
                    </div>
                </div>
            </div>
        `;

        // Connection indicator between shabads
        if (i < ReviewState.fullData.length - 1) {
            const shared = s.shared_tags_with_next || [];
            const strength = shared.length >= 3 ? "strong" : shared.length >= 1 ? "moderate" : "weak";
            const color = strength === "strong" ? "rgba(16,185,129,0.5)" : strength === "moderate" ? "rgba(245,158,11,0.35)" : "rgba(107,95,82,0.4)";
            const lineColor = strength === "strong" ? "rgba(16,185,129,0.15)" : strength === "moderate" ? "rgba(245,158,11,0.08)" : "rgba(255,255,255,0.03)";

            html += `
                <div class="reviewer-connection" style="border-left:1px solid ${lineColor};margin-left:18px;padding:4px 0 4px 14px;">
                    ${shared.length > 0
                        ? shared.slice(0, 3).map((t) => `<span style="font-family:'IBM Plex Mono';font-size:10px;color:${color};letter-spacing:0.02em;">${escapeHtml(t)}</span>`).join('<span style="color:#1f2937;font-size:10px;"> / </span>')
                        : '<span style="font-family:\'IBM Plex Mono\';font-size:10px;color:rgba(107,95,82,0.5);letter-spacing:0.02em;">NO SHARED TAGS</span>'
                    }
                </div>
            `;
        }
    });

    container.innerHTML = html;
}

/* ===== DETAIL PANEL (right panel) ===== */

function selectShabad(idx) {
    ReviewState.selectedIdx = idx;
    const s = ReviewState.fullData[idx];
    if (!s) return;

    // Update flow list selection
    renderFlow();

    // Scroll selected into view
    const flowItem = document.querySelector(`.reviewer-flow-item[data-idx="${idx}"]`);
    if (flowItem) flowItem.scrollIntoView({ behavior: "smooth", block: "nearest" });

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

/* ===== SAVE & LIBRARY (shared storage with explorer) ===== */

const PARKARAN_LIBRARY_KEY = "parkaran_library_v1";

function getLibrary() {
    try {
        const raw = localStorage.getItem(PARKARAN_LIBRARY_KEY);
        if (raw) return JSON.parse(raw);
    } catch (e) { /* ignore */ }
    return { parkarans: {}, currentId: null };
}

function setLibrary(lib) {
    localStorage.setItem(PARKARAN_LIBRARY_KEY, JSON.stringify(lib));
}

function generateId() {
    return Date.now().toString(36) + Math.random().toString(36).substring(2, 7);
}

function autoName(items) {
    const tagCounts = {};
    items.forEach((p) => (p.tags || []).forEach((t) => { tagCounts[t] = (tagCounts[t] || 0) + 1; }));
    const topTags = Object.entries(tagCounts).sort((a, b) => b[1] - a[1]).slice(0, 2).map((e) => e[0]);
    return topTags.join(" & ") || `Set (${items.length} shabads)`;
}

function showReviewerSaveDialog() {
    if (!ReviewState.parkaran.length) return;
    const dialog = document.getElementById("reviewerSaveDialog");
    const input = document.getElementById("reviewerSaveName");
    const existingName = localStorage.getItem("reviewParkaranName");
    input.value = existingName || autoName(ReviewState.parkaran);
    dialog.classList.remove("hidden");
    document.getElementById("reviewerLibraryModal").classList.add("hidden");
    input.focus();
    input.select();
}

function reviewerSave() {
    const name = document.getElementById("reviewerSaveName").value.trim();
    if (!name || !ReviewState.parkaran.length) return;

    const lib = getLibrary();
    const id = generateId();
    lib.parkarans[id] = {
        name: name,
        items: [...ReviewState.parkaran],
        created: new Date().toISOString(),
        updated: new Date().toISOString(),
    };
    setLibrary(lib);

    document.getElementById("reviewerSaveDialog").classList.add("hidden");

    // Update title to show saved name
    const titleEl = document.getElementById("reviewTitle");
    if (titleEl) titleEl.textContent = name;

    // Toast
    const toast = document.createElement("div");
    toast.className = "parkaran-toast";
    toast.textContent = `Saved: ${name}`;
    document.body.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add("show"));
    setTimeout(() => {
        toast.classList.remove("show");
        setTimeout(() => toast.remove(), 300);
    }, 2000);
}

function showReviewerLibrary() {
    const modal = document.getElementById("reviewerLibraryModal");
    const list = document.getElementById("reviewerLibraryList");
    document.getElementById("reviewerSaveDialog").classList.add("hidden");

    const lib = getLibrary();
    const saved = Object.entries(lib.parkarans)
        .map(([id, p]) => ({ id, name: p.name, count: p.items.length, created: p.created, updated: p.updated }))
        .sort((a, b) => (b.updated || b.created || "").localeCompare(a.updated || a.created || ""));

    if (saved.length === 0) {
        list.innerHTML = '<div style="font-family:\'IBM Plex Mono\';color:#6b5f52;font-size:10px;text-align:center;padding:12px;">No saved parkarans</div>';
    } else {
        list.innerHTML = saved.map((p) => `
            <div style="display:flex;align-items:center;justify-content:space-between;padding:8px;border-bottom:1px solid rgba(255,255,255,0.03);cursor:pointer;" onclick="loadReviewerParkaran('${p.id}')" onmouseover="this.style.background='rgba(245,158,11,0.05)'" onmouseout="this.style.background='transparent'">
                <div>
                    <div style="font-family:'IBM Plex Mono';color:#fbbf24;font-size:11px;">${escapeHtml(p.name)}</div>
                    <div style="font-family:'IBM Plex Mono';color:#4a3f35;font-size:9px;">${p.count} shabads &middot; ${new Date(p.updated || p.created).toLocaleDateString()}</div>
                </div>
                <button onclick="event.stopPropagation(); deleteReviewerParkaran('${p.id}')" style="color:#4a3f35;cursor:pointer;font-size:14px;background:none;border:none;" onmouseover="this.style.color='#ef4444'" onmouseout="this.style.color='#4a3f35'">&times;</button>
            </div>
        `).join("");
    }

    modal.classList.remove("hidden");
}

function loadReviewerParkaran(id) {
    const lib = getLibrary();
    const entry = lib.parkarans[id];
    if (!entry) return;

    // Store as current reviewParkaran and reload
    localStorage.setItem("reviewParkaran", JSON.stringify(entry.items));
    localStorage.setItem("reviewParkaranName", entry.name);
    window.location.reload();
}

function deleteReviewerParkaran(id) {
    const lib = getLibrary();
    delete lib.parkarans[id];
    setLibrary(lib);
    showReviewerLibrary(); // refresh
}

/* ===== START ===== */
init();
