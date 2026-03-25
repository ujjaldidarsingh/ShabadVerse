/**
 * Graph Explorer — Interactive SGGS shabad connection explorer.
 *
 * Design: tap-to-select nodes, persistent tooltip, smooth radial expansion,
 * localStorage-backed parkaran state, proper BaniDB ID handling.
 */

/* ===== STATE ===== */
const State = {
    cy: null,
    metadata: {},       // {shabadId: {title, gurmukhi, raag, writer, ang, tags, is_repertoire, ...}}
    tagIndex: {},       // {tag: [shabadId, ...]}
    tagVocab: {},       // {tag: {description, gurbani_term}}
    neighborCache: {},  // {shabadId: neighborData}
    centerNode: null,
    expandedNodes: [],  // ordered breadcrumb trail
    parkaran: [],       // [{id, title, gurmukhi, raag, ang, tags}, ...]
    allTags: [],
    activeTooltipId: null,
    expanding: false,   // guard against concurrent expandShabad calls
    selectedTuk: {},    // {shabadId: {gurmukhi, english, index}} — per-shabad tuk selection
    verseCache: {},     // {shabadId: versesArray} — cached verse data
    forces: {           // Obsidian-style force parameters
        center: 0.08,   // gravity: 0.01-0.5 (low = spread out)
        repel: 50000,   // nodeRepulsion: 5000-200000 (high = push apart)
        link: 0.20,     // edgeElasticity: 0.01-1.0 (low = loose springs)
        distance: 200,  // idealEdgeLength: 50-500 (high = long edges)
    },
    tagClusters: {},    // {tag: [nodeId, ...]} for post-layout label positioning
};

/** Escape for safe insertion into onclick attribute string literals. */
function escAttr(s) {
    return escapeHtml(String(s)).replace(/'/g, "&#39;").replace(/\\/g, "&#92;").replace(/\n/g, "&#10;");
}

/** Generation counter for loadVerseSelector race condition guard. */
let verseLoadGeneration = 0;
const VERSE_CACHE_MAX = 50;

/* ===== INIT ===== */

async function init() {
    const loadingEl = document.getElementById("graphLoading");
    const emptyEl = document.getElementById("graphEmpty");
    const statsEl = document.getElementById("graphStats");

    try {
        const data = await API.get("/api/graph/init");
        State.metadata = data.metadata || {};
        State.tagIndex = data.tag_index || {};
        State.tagVocab = data.tag_vocab || {};
        State.allTags = await API.get("/api/tags");

        // Restore parkaran from localStorage
        restoreParkaran();

        initCytoscape();
        initSearch();
        initThresholdSlider();
        initForceControls();

        if (statsEl) {
            const n = Object.keys(State.metadata).length;
            const t = Object.keys(State.tagIndex).length;
            statsEl.textContent = `${n.toLocaleString()} SHABADS / ${t} TAGS`;
        }

        loadingEl.classList.add("hidden");
        emptyEl.classList.remove("hidden");
    } catch (err) {
        loadingEl.innerHTML = `<div class="text-red-400/80 text-xs" style="font-family:'IBM Plex Mono',monospace;">LOAD FAILED: ${escapeHtml(err.message)}</div>`;
    }
}

/* ===== CYTOSCAPE SETUP ===== */

function initCytoscape() {
    State.cy = cytoscape({
        container: document.getElementById("cy"),
        elements: [],
        style: getStyles(),
        layout: { name: "preset" },
        minZoom: 0.25,
        maxZoom: 2.5,
        wheelSensitivity: 0.2,
        boxSelectionEnabled: false,
        selectionType: "single",
    });

    // Tap node → show tooltip (not hover — avoids flicker)
    State.cy.on("tap", "node[type='shabad']", (evt) => {
        evt.stopPropagation();
        const sid = evt.target.data("shabadId");
        if (sid) showTooltip(sid, evt.target);
    });

    // Tap background → hide tooltip
    State.cy.on("tap", (evt) => {
        if (evt.target === State.cy) hideTooltip();
    });

    // Double-tap node → expand (navigate into it)
    State.cy.on("dbltap", "node[type='shabad']", (evt) => {
        const sid = evt.target.data("shabadId");
        if (sid) {
            hideTooltip();
            expandShabad(sid);
        }
    });
}

function getStyles() {
    return [
        // ── Shabad node (small filled dot, larger hit area for tapping) ──
        {
            selector: "node[type='shabad']",
            style: {
                label: "data(label)",
                "background-color": "rgba(170,170,190,0.6)",
                "border-width": 0,
                color: "rgba(200,200,210,0.45)",
                "font-family": "'Noto Sans Gurmukhi', sans-serif",
                "font-size": "7px",
                "text-wrap": "ellipsis",
                "text-max-width": "70px",
                width: 8,
                height: 8,
                "text-valign": "bottom",
                "text-margin-y": 3,
                // Larger overlay for easier tapping (visual is 8px, hit area is 20px)
                "overlay-opacity": 0,
                "overlay-padding": 6,
            },
        },
        // Repertoire node (amber fill)
        {
            selector: "node[type='shabad'][?isRepertoire]",
            style: {
                "background-color": "rgba(245,158,11,0.7)",
                width: 10,
                height: 10,
            },
        },
        // Hover state
        {
            selector: "node[type='shabad']:active",
            style: {
                "background-color": "rgba(245,158,11,0.8)",
                width: 12,
                height: 12,
                color: "rgba(251,191,36,0.9)",
                "font-size": "7px",
            },
        },
        // Selected node
        {
            selector: "node[type='shabad']:selected",
            style: {
                "background-color": "rgba(245,158,11,0.8)",
                width: 12,
                height: 12,
                color: "rgba(251,191,36,0.9)",
                "font-size": "7px",
            },
        },
        // ── Center node (larger, bright) ──
        {
            selector: "node.center",
            style: {
                "background-color": "rgba(245,158,11,0.9)",
                width: 14,
                height: 14,
                color: "rgba(251,191,36,1)",
                "font-size": "8px",
                "font-weight": "bold",
                "text-max-width": "90px",
            },
        },
        // ── Tag label (hub node — same visual weight as shabads) ──
        {
            selector: "node[type='tagLabel']",
            style: {
                label: "data(label)",
                "background-color": "rgba(245,158,11,0.15)",
                "border-width": 0,
                color: "rgba(245,158,11,0.5)",
                "font-family": "'IBM Plex Mono', monospace",
                "font-size": "6px",
                "font-weight": 600,
                "text-halign": "center",
                "text-valign": "center",
                "text-max-width": "80px",
                "text-wrap": "ellipsis",
                width: 6,
                height: 6,
                "overlay-opacity": 0,
                events: "no",
            },
        },
        // ── Edge (curved bezier, clustered look) ──
        {
            selector: "edge",
            style: {
                width: 0.6,
                "line-color": "rgba(170,170,190,0.18)",
                "curve-style": "unbundled-bezier",
                "control-point-distances": [12],
                "control-point-weights": [0.5],
                "target-arrow-shape": "none",
                "overlay-opacity": 0,
            },
        },
        // ── Faded (previous expansions) ──
        {
            selector: ".faded",
            style: { opacity: 0.08 },
        },
        // ── In parkaran (green dot) ──
        {
            selector: "node.in-parkaran",
            style: {
                "background-color": "rgba(16,185,129,0.8)",
                width: 10,
                height: 10,
            },
        },
    ];
}

/* ===== EXPAND SHABAD (core navigation) ===== */

async function expandShabad(shabadId) {
    const sid = String(shabadId);
    if (State.expanding) return; // guard against concurrent calls
    State.expanding = true;

    document.getElementById("graphEmpty").classList.add("hidden");
    hideTooltip();

    // Show threshold slider once a shabad is expanded
    showThresholdSlider();

    // Fetch neighbors — pass tuk English if user searched a specific verse
    const threshold = getThreshold();
    const tuk = State.selectedTuk[sid];
    const tukEnglish = tuk?.english || "";
    const cacheKey = `${sid}_${threshold}_${tukEnglish ? simpleHash(tukEnglish) : "graph"}`;
    if (!State.neighborCache[cacheKey]) {
        try {
            let url = `/api/graph/neighbors/${sid}?threshold=${threshold}`;
            if (tukEnglish) {
                url += `&tuk_english=${encodeURIComponent(tukEnglish)}`;
            }
            State.neighborCache[cacheKey] = await API.get(url);
        } catch (err) {
            console.error("Neighbor fetch failed:", err);
            State.expanding = false;
            return;
        }
    }

    const neighborData = State.neighborCache[cacheKey];
    const byTag = neighborData.by_tag || {};
    const cy = State.cy;

    // Fade all existing elements
    cy.elements().addClass("faded");
    cy.nodes(".in-parkaran").removeClass("faded");

    // Remove old tag hub nodes and their edges — we'll recreate for new expansion
    const oldTagNodes = cy.nodes("[type='tagLabel']");
    oldTagNodes.connectedEdges().remove();
    oldTagNodes.remove();

    // Add or update center node — use searched tuk if available
    const meta = State.metadata[sid] || {};
    const centerLabel = tuk ? trunc(tuk.gurmukhi, 12) : trunc(meta.gurmukhi || meta.title || "?", 10);
    let centerEl = cy.getElementById(sid);
    if (centerEl.length === 0) {
        cy.add({
            group: "nodes",
            data: {
                id: sid,
                shabadId: sid,
                type: "shabad",
                label: centerLabel,
                isRepertoire: meta.is_repertoire || false,
            },
            position: { x: 0, y: 0 },
        });
        centerEl = cy.getElementById(sid);
    } else {
        // Update label to reflect searched tuk (may differ from default rahao)
        centerEl.data("label", centerLabel);
    }
    centerEl.removeClass("faded").addClass("center");

    // Unmark previous center
    if (State.centerNode && State.centerNode !== sid) {
        cy.getElementById(State.centerNode).removeClass("center");
    }
    State.centerNode = sid;

    // Update breadcrumbs
    if (!State.expandedNodes.includes(sid)) {
        State.expandedNodes.push(sid);
    }
    renderBreadcrumbs();

    // Radial layout: tag-clustered slices with curved bezier edges.
    // Each tag cluster occupies a tight angular wedge with gaps between clusters.
    // Nodes within a cluster are packed close; clusters are separated visually.
    const centerPos = centerEl.position();
    const tagEntries = Object.entries(byTag).filter(([_, n]) => n.length > 0);
    const radius = State.forces.distance;
    State.tagClusters = {};

    const numTags = tagEntries.length;
    // Gap between clusters: 15% of each slice is padding (7.5% on each side)
    const gapFraction = 0.15;
    const fullSlice = (2 * Math.PI) / Math.max(numTags, 1);
    const gapAngle = fullSlice * gapFraction;
    const usableSlice = fullSlice - gapAngle;

    let globalAngleOffset = 0;

    for (let ti = 0; ti < tagEntries.length; ti++) {
        const [tag, neighbors] = tagEntries[ti];
        State.tagClusters[tag] = [];

        const baseAngle = globalAngleOffset + gapAngle / 2; // start after gap
        globalAngleOffset += fullSlice;
        const tagAngle = baseAngle + usableSlice / 2;

        // Vary radius per cluster for depth (alternating near/far)
        const clusterRadius = radius * (0.9 + (ti % 2) * 0.2);

        // Place tag label between center and cluster (closer to cluster)
        const tagId = `tl_${sid}_${tag.replace(/\W/g, "_")}`;
        const labelR = clusterRadius * 0.55;
        cy.add({
            group: "nodes",
            data: { id: tagId, type: "tagLabel", label: tag },
            position: {
                x: centerPos.x + Math.cos(tagAngle) * labelR,
                y: centerPos.y + Math.sin(tagAngle) * labelR,
            },
        });

        // Place shabad neighbors in a tight arc within this tag's usable slice
        for (let j = 0; j < neighbors.length; j++) {
            const n = neighbors[j];
            const nid = String(n.id);
            if (nid === sid) continue;

            // Pack nodes tightly within the usable slice
            const neighborAngle = baseAngle + ((j + 0.5) / Math.max(neighbors.length, 1)) * usableSlice;
            // Slight radial jitter to avoid perfect arc (but stay within cluster band)
            const jitter = 0.92 + Math.random() * 0.16;
            const nx = centerPos.x + Math.cos(neighborAngle) * clusterRadius * jitter;
            const ny = centerPos.y + Math.sin(neighborAngle) * clusterRadius * jitter;

            let nodeEl = cy.getElementById(nid);
            if (nodeEl.length === 0) {
                const nmeta = State.metadata[nid] || {};
                cy.add({
                    group: "nodes",
                    data: {
                        id: nid,
                        shabadId: nid,
                        type: "shabad",
                        label: trunc(nmeta.gurmukhi || n.gurmukhi || n.title || "?", 9),
                        isRepertoire: n.is_repertoire || nmeta.is_repertoire || false,
                    },
                    position: { x: nx, y: ny },
                });
            } else {
                nodeEl.removeClass("faded");
                nodeEl.animate({ position: { x: nx, y: ny } }, { duration: 400, easing: "ease-out-cubic" });
            }

            // Edge: center → shabad (curved bezier within the tag slice)
            const edgeId = `e_${sid}_${nid}`;
            if (cy.getElementById(edgeId).length === 0) {
                cy.add({
                    group: "edges",
                    data: { id: edgeId, source: sid, target: nid },
                });
            }
            cy.getElementById(edgeId).removeClass("faded");

            State.tagClusters[tag].push(nid);
        }
    }

    // Re-apply parkaran styling
    State.parkaran.forEach((p) => {
        const el = cy.getElementById(String(p.id));
        if (el.length) el.addClass("in-parkaran").removeClass("faded");
    });

    // Smooth fit to visible nodes
    const visibleNodes = cy.nodes().not(".faded").not("[type='tagLabel']");
    if (visibleNodes.length > 0) {
        cy.animate({
            fit: { eles: visibleNodes, padding: 50 },
        }, {
            duration: 450,
            easing: "ease-out-cubic",
            complete: () => { State.expanding = false; },
        });
    } else {
        State.expanding = false;
    }
}

/** Position tag label nodes at the centroid of their cluster after force layout. */
/** Tag labels are now hub nodes in the graph — force layout positions them naturally. */
function positionTagLabels(_centerSid) {
    // No-op: tag hub nodes are connected to center + shabads,
    // so the force layout places them at the cluster centroid automatically.
}

/** Re-run layout when distance slider changes. Simply re-expands from current center. */
function relayout() {
    if (!State.centerNode) return;
    State.expanding = false;
    expandShabad(State.centerNode);
}

function resetGraph() {
    State.cy.elements().remove();
    State.centerNode = null;
    State.expandedNodes = [];
    State.neighborCache = {};
    State.activeTooltipId = null;
    hideTooltip();
    renderBreadcrumbs();
    document.getElementById("graphEmpty").classList.remove("hidden");
}

/* ===== TOOLTIP (tap-to-show, persistent) ===== */

function showTooltip(shabadId, nodeEl) {
    const sid = String(shabadId);
    const meta = State.metadata[sid] || {};
    const tooltip = document.getElementById("nodeTooltip");
    const isRep = meta.is_repertoire || false;
    const inParkaran = State.parkaran.some((p) => String(p.id) === sid);

    State.activeTooltipId = sid;

    const tagPills = (meta.tags || [])
        .slice(0, 5)
        .map((t) => `<span class="tt-tag">${escapeHtml(t)}</span>`)
        .join("");

    // Summary: prefer brief_meaning, fall back to primary_theme
    const summary = meta.brief_meaning || meta.primary_theme || "";

    // Selected tuk for this shabad (if any)
    const tuk = State.selectedTuk[sid];
    const tukHtml = tuk ? `<div lang="pa-Guru" style="font-family:'Noto Sans Gurmukhi';color:rgba(16,185,129,0.6);font-size:10px;margin-top:4px;padding:3px 6px;background:rgba(16,185,129,0.04);border-radius:3px;border-left:2px solid rgba(16,185,129,0.3);">${escapeHtml((tuk.gurmukhi || "").substring(0, 50))}</div>` : "";

    tooltip.innerHTML = `
        <div class="tt-body">
            ${meta.gurmukhi ? `<div class="tt-gurmukhi">${isRep ? "&#9733; " : ""}${escapeHtml(meta.gurmukhi.substring(0, 45))}</div>` : ""}
            ${tukHtml}
            <div class="tt-meta">${escapeHtml([meta.raag, meta.writer, meta.ang ? "ANG " + meta.ang : ""].filter(Boolean).join(" / "))}</div>
            ${summary ? `<div class="tt-summary">${escapeHtml(summary.substring(0, 120))}</div>` : ""}
            ${tagPills ? `<div class="tt-tags">${tagPills}</div>` : ""}
            <div class="tt-actions">
                <button class="tt-btn tt-btn-add" data-action="add" data-id="${sid}">${inParkaran ? "&#10003; IN PARKARAN" : "+ ADD"}</button>
                <button class="tt-btn tt-btn-explore" data-action="explore" data-id="${sid}">EXPLORE &rarr;</button>
                <button class="tt-btn" data-action="preview" data-id="${sid}" style="color:rgba(200,200,210,0.4);">PREVIEW</button>
                <button class="tt-btn" data-action="verses" data-id="${sid}" style="color:rgba(200,200,210,0.4);">VERSES</button>
            </div>
            <div id="tt-preview-${sid}" class="hidden" style="margin-top:6px;max-height:150px;overflow-y:auto;font-size:6px;line-height:1.4;"></div>
            <div id="tt-verses-${sid}" class="hidden" style="margin-top:6px;max-height:120px;overflow-y:auto;"></div>
        </div>
    `;

    // Bind button clicks via event delegation (no inline onclick)
    tooltip.querySelectorAll("[data-action]").forEach((btn) => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const action = btn.dataset.action;
            const id = btn.dataset.id;
            if (action === "add") {
                addToParkaran(id);
                showTooltip(id, nodeEl); // refresh to show "IN PARKARAN"
            } else if (action === "explore") {
                hideTooltip();
                expandShabad(id);
            } else if (action === "preview") {
                loadPreview(id);
            } else if (action === "verses") {
                loadVerseSelector(id, nodeEl);
            }
        });
    });

    // Position tooltip near node, clamped to viewport
    const pos = nodeEl.renderedPosition();
    const container = document.getElementById("cy").getBoundingClientRect();
    const ttWidth = 240;
    const ttHeight = 220;

    let left = pos.x + 24;
    let top = pos.y - 30;

    // Clamp to container bounds
    if (left + ttWidth > container.width - 10) left = pos.x - ttWidth - 10;
    if (top + ttHeight > container.height - 10) top = container.height - ttHeight - 10;
    if (top < 10) top = 10;
    if (left < 10) left = 10;

    tooltip.style.left = left + "px";
    tooltip.style.top = top + "px";
    tooltip.classList.remove("hidden");
}

function hideTooltip() {
    State.activeTooltipId = null;
    document.getElementById("nodeTooltip").classList.add("hidden");
}

/** Show shabad preview with translation in the tooltip. */
async function loadPreview(shabadId) {
    const sid = String(shabadId);
    const container = document.getElementById(`tt-preview-${sid}`);
    if (!container) return;

    // Toggle
    if (!container.classList.contains("hidden")) {
        container.classList.add("hidden");
        return;
    }
    container.classList.remove("hidden");
    container.innerHTML = '<div style="font-family:\'IBM Plex Mono\';color:#374151;font-size:7px;">LOADING...</div>';

    // Use cached verses if available
    if (!State.verseCache[sid]) {
        try {
            const data = await API.get(`/api/graph/shabad/${sid}/verses`);
            State.verseCache[sid] = data.verses || [];
        } catch (err) {
            container.innerHTML = `<div style="color:#ef4444;font-size:7px;">Could not load preview</div>`;
            return;
        }
    }

    const verses = State.verseCache[sid];
    if (!verses.length) {
        container.innerHTML = '<div style="color:#374151;font-size:7px;">No verse data available</div>';
        return;
    }

    // Render Gurmukhi + English, rahao highlighted
    container.innerHTML = verses.map((v) => {
        const isRahao = v.is_rahao;
        const gurmukhi = v.gurmukhi || "";
        const english = v.english || "";
        const rahaoStyle = isRahao ? "border-left:2px solid rgba(245,158,11,0.4);padding-left:4px;background:rgba(245,158,11,0.03);" : "";
        return `<div style="margin-bottom:3px;${rahaoStyle}">
            ${gurmukhi ? `<div lang="pa-Guru" style="font-family:'Noto Sans Gurmukhi';color:rgba(251,191,36,0.7);font-size:7px;">${escapeHtml(gurmukhi)}</div>` : ""}
            ${english ? `<div style="font-family:'IBM Plex Mono';color:rgba(200,200,210,0.35);font-size:6px;">${escapeHtml(english)}</div>` : ""}
        </div>`;
    }).join("");
}

async function loadVerseSelector(shabadId, nodeEl) {
    const sid = String(shabadId);
    const container = document.getElementById(`tt-verses-${sid}`);
    if (!container) return;

    // Toggle visibility
    if (!container.classList.contains("hidden")) {
        container.classList.add("hidden");
        return;
    }

    container.classList.remove("hidden");
    container.innerHTML = '<div style="font-family:\'IBM Plex Mono\';color:#374151;font-size:8px;">LOADING...</div>';

    // Race condition guard: if tooltip changes during fetch, abort
    const gen = ++verseLoadGeneration;

    // Fetch verses (cached with LRU eviction)
    if (!State.verseCache[sid]) {
        try {
            const data = await API.get(`/api/discover/shabad/${sid}/verses`);
            if (gen !== verseLoadGeneration) return; // stale, tooltip changed
            // LRU eviction
            const keys = Object.keys(State.verseCache);
            if (keys.length >= VERSE_CACHE_MAX) {
                delete State.verseCache[keys[0]];
            }
            State.verseCache[sid] = data.verses || [];
        } catch (err) {
            if (gen !== verseLoadGeneration) return;
            container.innerHTML = '<div style="font-family:\'IBM Plex Mono\';color:#ef4444;font-size:8px;">FAILED</div>';
            return;
        }
    }

    // Check container still exists in DOM (tooltip may have been replaced)
    if (gen !== verseLoadGeneration || !document.getElementById(`tt-verses-${sid}`)) return;

    const verses = State.verseCache[sid];
    const currentTuk = State.selectedTuk[sid];

    container.innerHTML = verses.map((v, i) => {
        if (!v.gurmukhi) return "";
        const isSelected = currentTuk && currentTuk.index === i;
        const isRahao = v.is_rahao;
        const borderColor = isSelected ? "rgba(16,185,129,0.4)" : isRahao ? "rgba(245,158,11,0.2)" : "transparent";
        const bg = isSelected ? "rgba(16,185,129,0.04)" : isRahao ? "rgba(245,158,11,0.02)" : "transparent";
        return `
            <div data-action="select-verse" data-sid="${escAttr(sid)}" data-vidx="${i}"
                 style="padding:3px 6px;margin-bottom:2px;cursor:pointer;border-left:2px solid ${borderColor};background:${bg};border-radius:0 2px 2px 0;"
                 onmouseover="this.style.background='rgba(255,255,255,0.02)'" onmouseout="this.style.background='${bg}'">
                <div lang="pa-Guru" style="font-family:'Noto Sans Gurmukhi';color:${isSelected ? 'rgba(16,185,129,0.7)' : 'rgba(251,191,36,0.5)'};font-size:10px;">${escapeHtml(v.gurmukhi.substring(0, 45))}</div>
                ${isRahao ? '<span style="font-family:\'IBM Plex Mono\';font-size:7px;color:rgba(245,158,11,0.3);">RAHAO</span>' : ""}
            </div>
        `;
    }).filter(Boolean).join("");

    // Bind verse selection clicks
    container.querySelectorAll("[data-action='select-verse']").forEach((el) => {
        el.addEventListener("click", (e) => {
            e.stopPropagation();
            const vsid = el.dataset.sid;
            const vidx = parseInt(el.dataset.vidx, 10);
            const v = State.verseCache[vsid]?.[vidx];
            if (v) {
                State.selectedTuk[vsid] = { gurmukhi: v.gurmukhi, english: v.english || "", index: vidx };
                // Re-expand with new tuk context (different suggestions)
                hideTooltip();
                expandShabad(vsid);
            }
        });
    });
}

/* ===== THRESHOLD SLIDER ===== */

function initThresholdSlider() {
    const slider = document.getElementById("thresholdSlider");
    if (!slider) return;

    slider.addEventListener("input", debounce(() => {
        if (!State.centerNode) return;
        // Invalidate ALL cache entries for current center (threshold changed)
        const sid = State.centerNode;
        for (const key of Object.keys(State.neighborCache)) {
            if (key.startsWith(sid + "_")) delete State.neighborCache[key];
        }
        expandShabad(sid);
    }, 300));
}

function getThreshold() {
    const slider = document.getElementById("thresholdSlider");
    return slider ? parseFloat(slider.value) : 0.35;
}

function showThresholdSlider() {
    const control = document.getElementById("thresholdControl");
    if (control) control.style.display = "flex";
}

/* ===== SPREAD CONTROL ===== */

function initForceControls() {
    const slider = document.getElementById("forceDistance");
    const valEl = document.getElementById("forceDistanceVal");
    if (!slider) return;

    slider.addEventListener("input", debounce(() => {
        const val = parseInt(slider.value, 10);
        State.forces.distance = val;
        if (valEl) valEl.textContent = String(val);
        if (State.centerNode) relayout();
    }, 300));
}

/* ===== SEARCH (first-letter default) ===== */

function initSearch() {
    const input = document.getElementById("graphSearch");
    const dropdown = document.getElementById("searchDropdown");

    input.addEventListener("input", debounce(async () => {
        const q = input.value.trim();
        if (q.length < 2) {
            dropdown.classList.add("hidden");
            return;
        }

        // First-letter search (strip spaces)
        const flQuery = q.replace(/\s+/g, "");

        try {
            const results = await API.get(`/api/discover/search?q=${encodeURIComponent(flQuery)}&searchtype=1`);

            if (!results || results.length === 0) {
                // Fallback: local tag/theme search
                const ql = q.toLowerCase();
                const local = [];
                for (const [sid, m] of Object.entries(State.metadata)) {
                    if (local.length >= 8) break;
                    if ((m.tags || []).join(" ").toLowerCase().includes(ql) ||
                        (m.primary_theme || "").toLowerCase().includes(ql)) {
                        local.push({ id: sid, ...m });
                    }
                }
                dropdown.innerHTML = local.length === 0
                    ? '<div class="autocomplete-item text-gray-600" style="font-family:\'IBM Plex Mono\';font-size:10px;">NO RESULTS</div>'
                    : local.map((m) => searchResultHTML(m.id, m)).join("");
            } else {
                dropdown.innerHTML = results.slice(0, 10).map((r) => {
                    const sid = String(r.banidb_shabad_id);
                    const m = State.metadata[sid] || {};
                    const matchedVerse = r.title_gurmukhi || m.gurmukhi || "";
                    const matchedEnglish = r.first_line_translation || "";
                    return searchResultHTML(sid, {
                        gurmukhi: matchedVerse,
                        title: r.title_transliteration || m.title || "",
                        raag: r.raag || m.raag || "",
                        writer: r.writer || m.writer || "",
                        ang: r.ang_number || m.ang || 0,
                        is_repertoire: m.is_repertoire || false,
                        brief_meaning: m.brief_meaning || "",
                    }, matchedVerse, matchedEnglish);
                }).join("");
            }
            dropdown.classList.remove("hidden");
        } catch (err) {
            console.error("Search error:", err);
        }
    }, 300));

    document.addEventListener("click", (e) => {
        if (!e.target.closest("#graphSearch") && !e.target.closest("#searchDropdown")) {
            dropdown.classList.add("hidden");
        }
    });
}

function searchResultHTML(sid, m, matchedVerse, matchedEnglish) {
    const summary = m.brief_meaning || m.primary_theme || "";
    const verseAttr = matchedVerse ? escAttr(matchedVerse.substring(0, 80)) : "";
    const engAttr = matchedEnglish ? escAttr(matchedEnglish.substring(0, 150)) : "";
    return `
        <div class="autocomplete-item" onclick="selectSearch('${escAttr(sid)}', '${verseAttr}', '${engAttr}')">
            ${m.gurmukhi ? `<div lang="pa-Guru" style="font-family:'Noto Sans Gurmukhi';color:#fbbf24;font-size:13px;">${escapeHtml(m.gurmukhi.substring(0, 45))}</div>` : ""}
            <div style="font-family:'IBM Plex Mono';color:#374151;font-size:9px;">
                ${escapeHtml([m.raag, m.writer, m.ang ? "ANG " + m.ang : ""].filter(Boolean).join(" / "))}
                ${m.is_repertoire ? " &#9733;" : ""}
            </div>
            ${summary ? `<div style="font-family:'IBM Plex Mono';color:#6b7280;font-size:9px;margin-top:2px;">${escapeHtml(summary.substring(0, 80))}</div>` : ""}
        </div>
    `;
}

function selectSearch(sid, matchedVerse, englishTranslation) {
    document.getElementById("searchDropdown").classList.add("hidden");
    document.getElementById("graphSearch").value = "";
    // Store the searched tuk with its English translation for tuk-aware suggestions
    if (matchedVerse) {
        State.selectedTuk[sid] = {
            gurmukhi: matchedVerse,
            english: englishTranslation || "",
            index: -1,
        };
    }
    expandShabad(sid);
}

/* ===== TAG BROWSER ===== */

function openTagBrowser() {
    const modal = document.getElementById("tagModal");
    const grid = document.getElementById("tagGrid");

    grid.innerHTML = State.allTags
        .filter((t) => t.tag !== "Repertoire")
        .map((t) => `<div class="tag-chip" onclick="selectTag('${escAttr(t.tag)}')">${escapeHtml(t.tag)} <span class="count">${t.count}</span></div>`)
        .join("");

    document.getElementById("tagDetail").classList.add("hidden");
    modal.classList.remove("hidden");
}

function closeTagBrowser() {
    document.getElementById("tagModal").classList.add("hidden");
}

async function selectTag(tag) {
    const detail = document.getElementById("tagDetail");
    const title = document.getElementById("tagDetailTitle");
    const list = document.getElementById("tagDetailList");

    title.textContent = `${tag} — pick a shabad`;
    detail.classList.remove("hidden");
    list.innerHTML = '<div style="font-family:\'IBM Plex Mono\';color:#374151;font-size:10px;">LOADING...</div>';

    try {
        const data = await API.get(`/api/tags/${encodeURIComponent(tag)}/shabads?limit=20`);
        list.innerHTML = data.shabads.map((s) => `
            <div class="autocomplete-item" onclick="closeTagBrowser(); expandShabad('${escAttr(s.id)}')">
                <div lang="pa-Guru" style="font-family:'Noto Sans Gurmukhi';color:#fbbf24;font-size:12px;">${escapeHtml((State.metadata[s.id]?.gurmukhi || s.title || "").substring(0, 40))}</div>
                <div style="font-family:'IBM Plex Mono';color:#4b5563;font-size:9px;">${escapeHtml([s.raag, s.writer, s.ang ? "ANG " + s.ang : ""].filter(Boolean).join(" / "))}</div>
            </div>
        `).join("");
    } catch (err) {
        list.innerHTML = `<div style="color:#ef4444;font-size:10px;">${escapeHtml(err.message)}</div>`;
    }
}

function surpriseMe() {
    const ids = Object.keys(State.metadata);
    if (!ids.length) return;
    expandShabad(ids[Math.floor(Math.random() * ids.length)]);
}

/* ===== BREADCRUMBS ===== */

function renderBreadcrumbs() {
    const el = document.getElementById("breadcrumbs");
    el.innerHTML = State.expandedNodes.map((sid) => {
        const m = State.metadata[sid] || {};
        const label = trunc(m.gurmukhi || m.title || sid, 12);
        const active = sid === State.centerNode;
        return `<span class="breadcrumb-node ${active ? "active" : ""}" onclick="event.stopPropagation(); expandShabad('${escAttr(sid)}')">${escapeHtml(label)}</span>`;
    }).join('<span style="color:#1f2937;font-size:9px;"> &rsaquo; </span>');
}

/* ===== PARKARAN (localStorage-backed) ===== */

const PARKARAN_KEY = "parkaran_explorer_v2";

function restoreParkaran() {
    try {
        const stored = localStorage.getItem(PARKARAN_KEY);
        if (stored) State.parkaran = JSON.parse(stored);
    } catch (e) { /* ignore */ }
    renderParkaran();
}

function saveParkaran() {
    localStorage.setItem(PARKARAN_KEY, JSON.stringify(State.parkaran));
}

function addToParkaran(shabadId) {
    const sid = String(shabadId);
    if (State.parkaran.some((p) => String(p.id) === sid)) return;

    const m = State.metadata[sid] || {};
    State.parkaran.push({
        id: sid,
        title: m.title || "Unknown",
        gurmukhi: m.gurmukhi || "",
        raag: m.raag || "",
        ang: m.ang || 0,
        tags: m.tags || [],
        is_repertoire: m.is_repertoire || false,
    });

    // Mark on graph
    const el = State.cy?.getElementById(sid);
    if (el?.length) el.addClass("in-parkaran");

    saveParkaran();
    renderParkaran();
}

function removeFromParkaran(shabadId) {
    const sid = String(shabadId);
    State.parkaran = State.parkaran.filter((p) => String(p.id) !== sid);

    const el = State.cy?.getElementById(sid);
    if (el?.length) el.removeClass("in-parkaran");

    saveParkaran();
    renderParkaran();
}

function renderParkaran() {
    const container = document.getElementById("parkaranList");
    const empty = document.getElementById("parkaranEmpty");
    const countEl = document.getElementById("parkaranCount");
    const reviewBtn = document.getElementById("reviewBtn");

    countEl.textContent = String(State.parkaran.length);

    if (State.parkaran.length === 0) {
        empty.classList.remove("hidden");
        container.innerHTML = "";
        reviewBtn.classList.add("hidden");
        return;
    }

    empty.classList.add("hidden");
    reviewBtn.classList.remove("hidden");

    // Rebuild all items (parkaranEmpty lives as a sibling outside the item list area)
    let html = "";
    State.parkaran.forEach((s, i) => {
        const rep = s.is_repertoire ? " &#9733;" : "";
        html += `
            <div class="parkaran-sidebar-item" draggable="true" data-idx="${i}" data-id="${escAttr(s.id)}">
                <span style="font-family:'IBM Plex Mono';color:rgba(245,158,11,0.3);font-size:10px;width:14px;flex-shrink:0;">${i + 1}</span>
                <div style="flex:1;min-width:0;user-select:none;">
                    ${s.gurmukhi ? `<div lang="pa-Guru" style="font-family:'Noto Sans Gurmukhi';color:#fbbf24;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(trunc(s.gurmukhi, 22))}${rep}</div>` : ""}
                    <div style="font-family:'IBM Plex Mono';color:#4b5563;font-size:8px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(trunc(s.title, 25))}</div>
                </div>
                <button onclick="event.stopPropagation(); removeFromParkaran('${escAttr(s.id)}')" style="color:#374151;cursor:pointer;font-size:12px;flex-shrink:0;background:none;border:none;" onmouseover="this.style.color='#ef4444'" onmouseout="this.style.color='#374151'">&times;</button>
            </div>
        `;
    });
    container.innerHTML = html;

    setupParkaranDrag();
}

function setupParkaranDrag() {
    const container = document.getElementById("parkaranList");
    const items = container.querySelectorAll(".parkaran-sidebar-item");
    let dragIdx = null;

    items.forEach((item) => {
        item.addEventListener("dragstart", () => {
            dragIdx = parseInt(item.dataset.idx, 10);
            item.style.opacity = "0.3";
        });
        item.addEventListener("dragend", () => {
            item.style.opacity = "1";
            dragIdx = null;
        });
        item.addEventListener("dragover", (e) => {
            e.preventDefault();
            item.style.borderColor = "rgba(245,158,11,0.4)";
        });
        item.addEventListener("dragleave", () => {
            item.style.borderColor = "";
        });
        item.addEventListener("drop", (e) => {
            e.preventDefault();
            item.style.borderColor = "";
            const targetIdx = parseInt(item.dataset.idx, 10);
            if (dragIdx !== null && dragIdx !== targetIdx) {
                const [moved] = State.parkaran.splice(dragIdx, 1);
                State.parkaran.splice(targetIdx, 0, moved);
                saveParkaran();
                renderParkaran();
            }
        });
    });
}

function sendToReview() {
    if (State.parkaran.length < 2) return;

    // Pass full parkaran data via localStorage (not sessionStorage — survives navigation)
    localStorage.setItem("reviewParkaran", JSON.stringify(State.parkaran));
    window.location.href = "/reviewer";
}

/* ===== UTILITIES ===== */

function trunc(text, max) {
    if (!text) return "";
    return text.length > max ? text.substring(0, max) + "..." : text;
}

function simpleHash(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        hash = ((hash << 5) - hash) + str.charCodeAt(i);
        hash |= 0;
    }
    return String(Math.abs(hash));
}

/* ===== START ===== */
init();
