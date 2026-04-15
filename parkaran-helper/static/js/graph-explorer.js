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
        distance: 250,  // idealEdgeLength: 50-500 (high = long edges)
    },
    tagClusters: {},    // {tag: [nodeId, ...]} for post-layout label positioning
};

/** Escape for safe insertion into onclick attribute string literals. */
function escAttr(s) {
    return escapeHtml(String(s)).replace(/'/g, "&#39;").replace(/\\/g, "&#92;").replace(/\n/g, "&#10;");
}

/** Map a shabad's primary theme to a node color. */
function themeColor(theme) {
    if (!theme) return "rgba(200,195,185,0.5)";
    const t = theme.toLowerCase();
    if (t.includes("devotion") || t.includes("prem") || t.includes("love")) return "#f59e0b";
    if (t.includes("birha") || t.includes("longing") || t.includes("separation")) return "#e879a0";
    if (t.includes("vismad") || t.includes("awe") || t.includes("wonder")) return "#a78bfa";
    if (t.includes("shanti") || t.includes("peace") || t.includes("calm")) return "#2dd4bf";
    if (t.includes("grace") || t.includes("kirpa") || t.includes("nadar")) return "#fbbf24";
    if (t.includes("maya") || t.includes("attachment") || t.includes("world")) return "#8a7d6c";
    if (t.includes("anand") || t.includes("joy") || t.includes("celeb")) return "#fb923c";
    if (t.includes("hukam") || t.includes("will") || t.includes("command")) return "#60a5fa";
    if (t.includes("surrender") || t.includes("humility")) return "#d4850a";
    return "rgba(200,195,185,0.5)";
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

        // Escape key closes modals and tooltip
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape") {
                hidePreview();
                closeTagShabadsModal();
                hideTooltip();
            }
        });

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

    // Tap tag label → open tag-shabads modal
    State.cy.on("tap", "node[type='tagLabel']", (evt) => {
        evt.stopPropagation();
        const tag = evt.target.data("tag") || evt.target.data("label");
        if (tag) openTagShabadsModal(tag);
    });

    // Hover tag label → show pointer cursor
    State.cy.on("mouseover", "node[type='tagLabel']", () => {
        State.cy.container().style.cursor = "pointer";
    });
    State.cy.on("mouseout", "node[type='tagLabel']", () => {
        State.cy.container().style.cursor = "";
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

    // Tag labels follow their cluster when nodes are dragged
    setupDragTagFollow();
}

function getStyles() {
    return [
        // ── Shabad node (theme-colored dot) ──
        {
            selector: "node[type='shabad']",
            style: {
                label: "data(label)",
                "background-color": "data(themeColor)",
                "border-width": 0,
                color: "rgba(232,220,200,0.5)",
                "font-family": "Noto Sans Gurmukhi, sans-serif",
                "font-size": "13px",
                "text-wrap": "ellipsis",
                "text-max-width": "160px",
                width: 10,
                height: 10,
                "text-valign": "bottom",
                "text-margin-y": 4,
                "overlay-opacity": 0,
                "overlay-padding": 8,
                "text-outline-width": 2,
                "text-outline-color": "#0f0d13",
                "text-outline-opacity": 0.7,
            },
        },
        // Repertoire node (amber ring)
        {
            selector: "node[type='shabad'][?isRepertoire]",
            style: {
                "border-color": "rgba(245,158,11,0.8)",
                "border-width": 2,
                width: 12,
                height: 12,
            },
        },
        // Active/hover state
        {
            selector: "node[type='shabad']:active",
            style: {
                width: 14,
                height: 14,
                color: "#f5e6c8",
                "font-size": "13px",
            },
        },
        // Selected node
        {
            selector: "node[type='shabad']:selected",
            style: {
                width: 14,
                height: 14,
                color: "#f5e6c8",
                "font-size": "13px",
            },
        },
        // ── Center node (star — largest, brightest) ──
        {
            selector: "node.center",
            style: {
                "background-color": "rgba(245,158,11,0.9)",
                width: 18,
                height: 18,
                color: "#f5e6c8",
                "font-size": "14px",
                "font-weight": "bold",
                "text-max-width": "200px",
                "border-color": "rgba(245,158,11,0.6)",
                "border-width": 2,
            },
        },
        // ── Tag label (clickable: opens tag-shabads modal) ──
        {
            selector: "node[type='tagLabel']",
            style: {
                label: "data(label)",
                "background-color": "rgba(245,158,11,0.08)",
                "border-width": 0,
                color: "rgba(245,158,11,0.45)",
                "font-family": "IBM Plex Mono, monospace",
                "font-size": "13px",
                "font-weight": 600,
                "text-halign": "center",
                "text-valign": "center",
                "text-max-width": "200px",
                "text-wrap": "wrap",
                width: 6,
                height: 6,
                "overlay-opacity": 0,
                "text-outline-width": 2,
                "text-outline-color": "#0f0d13",
                "text-outline-opacity": 0.6,
            },
        },
        // Tag label hover style — indicate it's interactive
        {
            selector: "node[type='tagLabel']:active, node[type='tagLabel'].cy-hover",
            style: {
                color: "rgba(245,158,11,0.95)",
                "text-outline-color": "#0f0d13",
                "text-outline-opacity": 1,
            },
        },
        // ── Edge with score-based strength ──
        {
            selector: "edge[score]",
            style: {
                width: "mapData(score, 0, 1, 0.3, 2.0)",
                "line-color": "data(targetTheme)",
                "line-opacity": "mapData(score, 0, 1, 0.06, 0.4)",
                "curve-style": "unbundled-bezier",
                "control-point-distances": [12],
                "control-point-weights": [0.5],
                "target-arrow-shape": "none",
                "overlay-opacity": 0,
            },
        },
        // Edge fallback (no score data)
        {
            selector: "edge[!score]",
            style: {
                width: 0.6,
                "line-color": "rgba(200,195,185,0.15)",
                "line-opacity": 0.15,
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
            style: { opacity: 0.06 },
        },
        // ── In parkaran (emerald) ──
        {
            selector: "node.in-parkaran",
            style: {
                "background-color": "rgba(16,185,129,0.8)",
                "border-color": "rgba(16,185,129,0.6)",
                "border-width": 2,
                width: 12,
                height: 10,
            },
        },
        // ── Parkaran trail edges (green arrows connecting selected shabads) ──
        {
            selector: "edge.parkaran-trail",
            style: {
                width: 2,
                "line-color": "rgba(16,185,129,0.5)",
                "line-style": "solid",
                "curve-style": "unbundled-bezier",
                "control-point-distances": [15],
                "control-point-weights": [0.5],
                "target-arrow-shape": "triangle",
                "target-arrow-color": "rgba(16,185,129,0.5)",
                "arrow-scale": 0.8,
                "overlay-opacity": 0,
                "z-index": 10,
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
    const centerLabel = tuk ? trunc(tuk.gurmukhi, 28) : trunc(meta.gurmukhi || meta.title || "?", 28);
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
                themeColor: themeColor(meta.primary_theme || ""),
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
            // Skip shabads already in parkaran (they remain visible but shouldn't be re-suggested)
            if (State.parkaran.some((p) => String(p.id) === nid)) continue;

            // Pack nodes tightly within the usable slice
            const neighborAngle = baseAngle + ((j + 0.5) / Math.max(neighbors.length, 1)) * usableSlice;
            // Slight radial jitter to avoid perfect arc (but stay within cluster band)
            const jitter = 0.92 + Math.random() * 0.16;
            const nx = centerPos.x + Math.cos(neighborAngle) * clusterRadius * jitter;
            const ny = centerPos.y + Math.sin(neighborAngle) * clusterRadius * jitter;

            let nodeEl = cy.getElementById(nid);
            const nmeta = State.metadata[nid] || {};
            const nTheme = nmeta.primary_theme || n.primary_theme || "";
            if (nodeEl.length === 0) {
                cy.add({
                    group: "nodes",
                    data: {
                        id: nid,
                        shabadId: nid,
                        type: "shabad",
                        label: trunc(nmeta.gurmukhi || n.gurmukhi || n.title || "?", 22),
                        isRepertoire: n.is_repertoire || nmeta.is_repertoire || false,
                        themeColor: themeColor(nTheme),
                    },
                    position: { x: nx, y: ny },
                });
            } else {
                nodeEl.removeClass("faded");
                nodeEl.animate({ position: { x: nx, y: ny } }, { duration: 400, easing: "ease-out-cubic" });
            }

            // Edge: center → shabad (curved bezier, strength-encoded)
            const edgeId = `e_${sid}_${nid}`;
            if (cy.getElementById(edgeId).length === 0) {
                cy.add({
                    group: "edges",
                    data: {
                        id: edgeId,
                        source: sid,
                        target: nid,
                        score: n.score || 0,
                        targetTheme: themeColor(nTheme),
                    },
                });
            }
            cy.getElementById(edgeId).removeClass("faded");

            State.tagClusters[tag].push(nid);
        }
    }

    // Re-apply parkaran styling and draw trail
    State.parkaran.forEach((p) => {
        const el = cy.getElementById(String(p.id));
        if (el.length) el.addClass("in-parkaran").removeClass("faded");
    });
    redrawParkaranTrail();

    // Fit to visible nodes — immediate fit first, then smooth refine
    const visibleNodes = cy.nodes().not(".faded").not("[type='tagLabel']");
    if (visibleNodes.length > 0) {
        cy.fit(visibleNodes, 50); // immediate fit so nodes are visible
        cy.animate({
            fit: { eles: visibleNodes, padding: 60 },
        }, {
            duration: 400,
            easing: "ease-out-cubic",
            complete: () => { State.expanding = false; },
        });
    } else {
        State.expanding = false;
    }
}

/** Position tag label nodes at the centroid of their cluster after force layout. */
/** Tag labels are now hub nodes in the graph — force layout positions them naturally. */
function positionTagLabels(centerSid) {
    // Reposition each tag label to the centroid of its cluster nodes
    const cy = State.cy;
    if (!cy) return;
    const centerEl = cy.getElementById(centerSid);
    const centerPos = centerEl.length ? centerEl.position() : { x: 0, y: 0 };

    for (const [tag, nodeIds] of Object.entries(State.tagClusters || {})) {
        const tagId = `tl_${centerSid}_${tag.replace(/\W/g, "_")}`;
        const labelEl = cy.getElementById(tagId);
        if (!labelEl.length || !nodeIds.length) continue;

        // Centroid of cluster nodes
        let sumX = 0, sumY = 0, count = 0;
        for (const nid of nodeIds) {
            const el = cy.getElementById(nid);
            if (el.length && !el.hasClass("faded")) {
                const pos = el.position();
                sumX += pos.x;
                sumY += pos.y;
                count++;
            }
        }
        if (count === 0) continue;

        // Place label between center and cluster centroid (55% toward cluster)
        const cx = sumX / count;
        const cy2 = sumY / count;
        const lx = centerPos.x + (cx - centerPos.x) * 0.55;
        const ly = centerPos.y + (cy2 - centerPos.y) * 0.55;

        labelEl.position({ x: lx, y: ly });
    }
}

function setupDragTagFollow() {
    // When user drags shabad nodes, update tag label positions in real-time
    const cy = State.cy;
    if (!cy) return;
    cy.on("drag", "node[type='shabad']", () => {
        if (State.centerNode) positionTagLabels(State.centerNode);
    });
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
    State.expanding = false;
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
        .map((t) => `<span class="tt-tag tt-tag-clickable" data-tag="${escAttr(t)}" title="Browse shabads in ${escAttr(t)}">${escapeHtml(t)}</span>`)
        .join("");

    // Summary: prefer brief_meaning, fall back to primary_theme
    const summary = meta.brief_meaning || meta.primary_theme || "";

    // Selected tuk for this shabad (if any)
    const tuk = State.selectedTuk[sid];
    const tukHtml = tuk ? `<div lang="pa-Guru" style="font-family:'Noto Sans Gurmukhi';color:rgba(16,185,129,0.6);font-size:10px;margin-top:4px;padding:3px 6px;background:rgba(16,185,129,0.04);border-radius:3px;border-left:2px solid rgba(16,185,129,0.3);">${escapeHtml((tuk.gurmukhi || "").substring(0, 50))}</div>` : "";

    // If this shabad is already the graph center, EXPLORE would be a no-op — disable it
    const isCurrentCenter = String(State.centerNode) === sid;

    tooltip.innerHTML = `
        <div class="tt-body">
            ${meta.gurmukhi ? `<div class="tt-gurmukhi">${isRep ? "&#9733; " : ""}${escapeHtml(meta.gurmukhi.substring(0, 45))}</div>` : ""}
            ${tukHtml}
            <div class="tt-meta">${escapeHtml([meta.raag, meta.writer, meta.ang ? "ANG " + meta.ang : ""].filter(Boolean).join(" / "))}</div>
            ${summary ? `<div class="tt-summary">${escapeHtml(summary.substring(0, 120))}</div>` : ""}
            ${tagPills ? `<div class="tt-tags">${tagPills}</div>` : ""}
            <div class="tt-actions">
                <button class="tt-btn tt-btn-add" data-action="add" data-id="${sid}">${inParkaran ? "&#10003; IN SET" : "+ ADD"}</button>
                <button class="tt-btn tt-btn-explore${isCurrentCenter ? " tt-btn-disabled" : ""}" data-action="explore" data-id="${sid}"${isCurrentCenter ? ' disabled title="Already centered"' : ""}>EXPLORE &rarr;</button>
                <button class="tt-btn tt-btn-preview" data-action="preview" data-id="${sid}">PREVIEW</button>
                <button class="tt-btn" data-action="verses" data-id="${sid}" style="color:rgba(200,200,210,0.4);">VERSES</button>
            </div>
            <div id="tt-preview-${sid}" class="hidden" style="margin-top:6px;max-height:200px;overflow-y:auto;font-size:12px;line-height:1.6;"></div>
            <div id="tt-verses-${sid}" class="hidden" style="margin-top:6px;max-height:180px;overflow-y:auto;"></div>
        </div>
    `;

    // Bind button clicks via event delegation (no inline onclick)
    tooltip.querySelectorAll("[data-action]").forEach((btn) => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            if (btn.disabled) return;
            const action = btn.dataset.action;
            const id = btn.dataset.id;
            if (action === "add") {
                addToParkaran(id);
                showTooltip(id, nodeEl); // refresh to show "IN PARKARAN"
            } else if (action === "explore") {
                hideTooltip();
                // If no tuk was selected for this shabad, use brief_meaning as semantic proxy
                if (!State.selectedTuk[id]) {
                    const nmeta = State.metadata[id] || {};
                    const meaning = nmeta.brief_meaning || nmeta.primary_theme || "";
                    if (meaning) {
                        State.selectedTuk[id] = { gurmukhi: "", english: meaning, index: -1 };
                    }
                }
                expandShabad(id);
            } else if (action === "preview") {
                loadPreview(id);
            } else if (action === "verses") {
                loadVerseSelector(id, nodeEl);
            }
        });
    });

    // Bind tag pill clicks → open tag-shabads modal
    tooltip.querySelectorAll(".tt-tag-clickable").forEach((pill) => {
        pill.addEventListener("click", (e) => {
            e.stopPropagation();
            const tag = pill.dataset.tag;
            if (tag) openTagShabadsModal(tag);
        });
    });

    // Position tooltip near node, clamped to viewport
    const pos = nodeEl.renderedPosition();
    const container = document.getElementById("cy").getBoundingClientRect();
    const ttWidth = 340;
    const ttHeight = 280;

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
    hidePreview();
}

/** Show shabad preview as a centered modal with backdrop. */
async function loadPreview(shabadId) {
    const sid = String(shabadId);
    const modal = document.getElementById("shabadPreviewModal");
    const preview = document.getElementById("shabadPreview");

    // Toggle off if showing same shabad
    if (!modal.classList.contains("hidden") && modal.dataset.sid === sid) {
        hidePreview();
        return;
    }

    modal.dataset.sid = sid;
    preview.innerHTML = '<div class="preview-header"><span>LOADING...</span><button class="preview-close" aria-label="Close preview">&times;</button></div>';
    modal.classList.remove("hidden");
    wirePreviewCloseButtons();

    // Use cached verses if available
    if (!State.verseCache[sid]) {
        try {
            const data = await API.get(`/api/graph/shabad/${sid}/verses`);
            // Evict oldest cache entry if over 50
            const keys = Object.keys(State.verseCache);
            if (keys.length >= 50) delete State.verseCache[keys[0]];
            State.verseCache[sid] = data.verses || [];
        } catch (err) {
            preview.innerHTML = '<div class="preview-header"><span>Could not load preview</span><button class="preview-close" aria-label="Close preview">&times;</button></div>';
            wirePreviewCloseButtons();
            return;
        }
    }

    const verses = State.verseCache[sid];
    const meta = State.metadata[sid] || {};
    if (!verses.length) {
        preview.innerHTML = '<div class="preview-header"><span>No verse data</span><button class="preview-close" aria-label="Close preview">&times;</button></div>';
        wirePreviewCloseButtons();
        return;
    }

    const headerText = escapeHtml(meta.raag ? `${meta.raag} / ANG ${meta.ang || "?"}` : `ANG ${meta.ang || "?"}`);
    preview.innerHTML = `
        <div class="preview-header">
            <span>${headerText}</span>
            <button class="preview-close" aria-label="Close preview">&times;</button>
        </div>
        ${verses.map((v) => {
            const rahaoClass = v.is_rahao ? " preview-rahao" : "";
            return `<div class="preview-verse${rahaoClass}">
                ${v.gurmukhi ? `<div lang="pa-Guru" class="preview-gurmukhi">${escapeHtml(v.gurmukhi)}</div>` : ""}
                ${v.english ? `<div class="preview-english">${escapeHtml(v.english)}</div>` : ""}
            </div>`;
        }).join("")}
    `;

    wirePreviewCloseButtons();
    // Reset scroll to top for each new preview
    preview.scrollTop = 0;
}

function wirePreviewCloseButtons() {
    document.querySelectorAll("#shabadPreview .preview-close").forEach((btn) => {
        btn.onclick = (e) => {
            e.stopPropagation();
            hidePreview();
        };
    });
}

function hidePreview() {
    const modal = document.getElementById("shabadPreviewModal");
    modal.classList.add("hidden");
    modal.removeAttribute("data-sid");
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
    container.innerHTML = '<div style="font-family:\'IBM Plex Mono\';color:#4a3f35;font-size:8px;">LOADING...</div>';

    // Race condition guard: if tooltip changes during fetch, abort
    const gen = ++verseLoadGeneration;

    // Fetch verses (cached with LRU eviction)
    if (!State.verseCache[sid]) {
        try {
            const data = await API.get(`/api/graph/shabad/${sid}/verses`);
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
    const scoreEl = document.getElementById("thresholdScore");
    if (!slider) return;

    // Update displayed score on every drag
    slider.addEventListener("input", () => {
        if (scoreEl) scoreEl.textContent = parseFloat(slider.value).toFixed(2);
    });

    // Re-expand on release (debounced)
    slider.addEventListener("change", debounce(() => {
        if (!State.centerNode) return;
        const sid = State.centerNode;
        for (const key of Object.keys(State.neighborCache)) {
            if (key.startsWith(sid + "_")) delete State.neighborCache[key];
        }
        expandShabad(sid);
    }, 200));
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
            const results = await API.get(`/api/graph/search?q=${encodeURIComponent(flQuery)}&searchtype=1`);

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
            <div style="font-family:'IBM Plex Mono';color:#4a3f35;font-size:9px;">
                ${escapeHtml([m.raag, m.writer, m.ang ? "ANG " + m.ang : ""].filter(Boolean).join(" / "))}
                ${m.is_repertoire ? " &#9733;" : ""}
            </div>
            ${summary ? `<div style="font-family:'IBM Plex Mono';color:#8a7d6c;font-size:9px;margin-top:2px;">${escapeHtml(summary.substring(0, 80))}</div>` : ""}
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
    list.innerHTML = '<div style="font-family:\'IBM Plex Mono\';color:#4a3f35;font-size:10px;">LOADING...</div>';

    try {
        const data = await API.get(`/api/tags/${encodeURIComponent(tag)}/shabads?limit=20`);
        list.innerHTML = data.shabads.map((s) => `
            <div class="autocomplete-item" onclick="closeTagBrowser(); expandShabad('${escAttr(s.id)}')">
                <div lang="pa-Guru" style="font-family:'Noto Sans Gurmukhi';color:#fbbf24;font-size:12px;">${escapeHtml((State.metadata[s.id]?.gurmukhi || s.title || "").substring(0, 40))}</div>
                <div style="font-family:'IBM Plex Mono';color:#6b5f52;font-size:9px;">${escapeHtml([s.raag, s.writer, s.ang ? "ANG " + s.ang : ""].filter(Boolean).join(" / "))}</div>
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

/* ===== TAG SHABADS MODAL (opened by clicking a tag label or tag pill) ===== */

async function openTagShabadsModal(tag) {
    if (!tag) return;
    hideTooltip();
    hidePreview();

    const modal = document.getElementById("tagShabadsModal");
    const content = document.getElementById("tagShabadsContent");

    modal.dataset.tag = tag;
    content.innerHTML = `
        <div class="preview-header">
            <span>${escapeHtml(tag.toUpperCase())} &mdash; LOADING...</span>
            <button class="preview-close" aria-label="Close tag list">&times;</button>
        </div>
    `;
    modal.classList.remove("hidden");
    wireTagShabadsCloseButtons();

    try {
        const data = await API.get(`/api/tags/${encodeURIComponent(tag)}/shabads?limit=50`);
        const shabads = data.shabads || [];
        const count = shabads.length;

        if (count === 0) {
            content.innerHTML = `
                <div class="preview-header">
                    <span>${escapeHtml(tag.toUpperCase())} &mdash; NO SHABADS</span>
                    <button class="preview-close" aria-label="Close tag list">&times;</button>
                </div>
                <div class="preview-english" style="padding:16px 4px;">No shabads found in this tag.</div>
            `;
        } else {
            content.innerHTML = `
                <div class="preview-header">
                    <span>${escapeHtml(tag.toUpperCase())} &mdash; ${count} SHABAD${count === 1 ? "" : "S"}</span>
                    <button class="preview-close" aria-label="Close tag list">&times;</button>
                </div>
                <div class="tag-shabads-list">
                    ${shabads.map((s) => {
                        const gurmukhi = State.metadata[s.id]?.gurmukhi || s.title || "";
                        const meta = [s.raag, s.writer, s.ang ? `ANG ${s.ang}` : ""].filter(Boolean).join(" / ");
                        return `
                            <div class="tag-shabad-row" data-sid="${escAttr(s.id)}">
                                <div lang="pa-Guru" class="tag-shabad-gurmukhi">${escapeHtml(gurmukhi.substring(0, 60))}</div>
                                <div class="tag-shabad-meta">${escapeHtml(meta)}</div>
                            </div>
                        `;
                    }).join("")}
                </div>
            `;
        }

        wireTagShabadsCloseButtons();
        content.querySelectorAll(".tag-shabad-row").forEach((row) => {
            row.addEventListener("click", () => {
                const sid = row.dataset.sid;
                closeTagShabadsModal();
                expandShabad(sid);
            });
        });
    } catch (err) {
        content.innerHTML = `
            <div class="preview-header">
                <span>${escapeHtml(tag.toUpperCase())} &mdash; ERROR</span>
                <button class="preview-close" aria-label="Close tag list">&times;</button>
            </div>
            <div class="preview-english" style="padding:16px 4px;color:#ef4444;">Could not load shabads: ${escapeHtml(err.message)}</div>
        `;
        wireTagShabadsCloseButtons();
    }
}

function wireTagShabadsCloseButtons() {
    document.querySelectorAll("#tagShabadsContent .preview-close").forEach((btn) => {
        btn.onclick = (e) => {
            e.stopPropagation();
            closeTagShabadsModal();
        };
    });
}

function closeTagShabadsModal() {
    const modal = document.getElementById("tagShabadsModal");
    modal.classList.add("hidden");
    modal.removeAttribute("data-tag");
}

/* ===== BREADCRUMBS ===== */

function renderBreadcrumbs() {
    const el = document.getElementById("breadcrumbs");
    if (State.expandedNodes.length === 0) {
        el.innerHTML = "";
        return;
    }

    const chips = State.expandedNodes.map((sid, idx) => {
        const m = State.metadata[sid] || {};
        const label = trunc(m.gurmukhi || m.title || sid, 20);
        const active = sid === State.centerNode;
        return `
            <span class="breadcrumb-chip ${active ? "active" : ""}">
                <span class="breadcrumb-label" data-sid="${escAttr(sid)}">${escapeHtml(label)}</span>
                <button class="breadcrumb-close" data-sid="${escAttr(sid)}" data-idx="${idx}" aria-label="Remove from trail" title="Remove from trail">&times;</button>
            </span>
        `;
    }).join('<span class="breadcrumb-sep">&rsaquo;</span>');

    el.innerHTML = `
        ${chips}
        <button class="breadcrumb-reset" id="breadcrumbReset" title="Clear exploration trail">RESET</button>
    `;

    // Label click → jump to that crumb
    el.querySelectorAll(".breadcrumb-label").forEach((label) => {
        label.addEventListener("click", (e) => {
            e.stopPropagation();
            const sid = label.dataset.sid;
            if (sid && sid !== String(State.centerNode)) {
                expandShabad(sid);
            }
        });
    });

    // × click → truncate trail at that point (browser-history pattern)
    el.querySelectorAll(".breadcrumb-close").forEach((btn) => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const idx = parseInt(btn.dataset.idx, 10);
            removeBreadcrumbAt(idx);
        });
    });

    // RESET button → confirm then clear
    const resetBtn = document.getElementById("breadcrumbReset");
    if (resetBtn) {
        resetBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            confirmResetGraph();
        });
    }
}

/**
 * Remove a single breadcrumb from the trail (not the ones after it).
 * If the removed crumb is the current center, re-center on the next crumb
 * (preferring the one after, then the one before). If no crumbs remain,
 * fall through to a full reset.
 */
function removeBreadcrumbAt(idx) {
    if (idx < 0 || idx >= State.expandedNodes.length) return;

    const removedSid = State.expandedNodes[idx];
    const isCenter = removedSid === State.centerNode;

    // Remove just this one
    State.expandedNodes = [
        ...State.expandedNodes.slice(0, idx),
        ...State.expandedNodes.slice(idx + 1),
    ];

    if (State.expandedNodes.length === 0) {
        resetGraph();
        return;
    }

    if (isCenter) {
        // Jump to the crumb that was after the removed one, or the one before
        // if we removed the last crumb
        const newIdx = Math.min(idx, State.expandedNodes.length - 1);
        const newCenter = State.expandedNodes[newIdx];
        // expandShabad pushes to expandedNodes, so pop the item at newIdx to
        // avoid duplication (it will be re-added by expandShabad)
        State.expandedNodes = [
            ...State.expandedNodes.slice(0, newIdx),
            ...State.expandedNodes.slice(newIdx + 1),
        ];
        expandShabad(newCenter);
    } else {
        renderBreadcrumbs();
    }
}

function confirmResetGraph() {
    if (State.expandedNodes.length === 0) {
        resetGraph();
        return;
    }
    const ok = window.confirm("Clear exploration trail?\n\nThis will reset the graph and remove all breadcrumbs. Your saved set is unaffected.");
    if (ok) resetGraph();
}

/* ===== PARKARAN LIBRARY (multi-parkaran, localStorage-backed) ===== */

const PARKARAN_LIBRARY_KEY = "parkaran_library_v1";
const OLD_PARKARAN_KEY = "parkaran_explorer_v2";
let libraryView = false; // tracks whether the sidebar shows library or active parkaran

function generateId() {
    return Date.now().toString(36) + Math.random().toString(36).substring(2, 7);
}

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

function autoName(items) {
    const tagCounts = {};
    items.forEach((p) => (p.tags || []).forEach((t) => { tagCounts[t] = (tagCounts[t] || 0) + 1; }));
    const topTags = Object.entries(tagCounts).sort((a, b) => b[1] - a[1]).slice(0, 2).map((e) => e[0]);
    return topTags.join(" & ") || `Set (${items.length} shabads)`;
}

function restoreParkaran() {
    // Migrate old single-parkaran key
    try {
        const old = localStorage.getItem(OLD_PARKARAN_KEY);
        if (old) {
            const items = JSON.parse(old);
            if (items.length > 0) {
                const lib = getLibrary();
                const id = generateId();
                lib.parkarans[id] = {
                    name: autoName(items),
                    items: items,
                    created: new Date().toISOString(),
                };
                lib.currentId = id;
                setLibrary(lib);
                State.parkaran = items;
            }
            localStorage.removeItem(OLD_PARKARAN_KEY);
            ensureCurrentLibrary();
            renderParkaran();
            updateLibraryNameDisplay();
            return;
        }
    } catch (e) { /* ignore */ }

    // Ensure a current library exists (auto-create if first visit)
    ensureCurrentLibrary();

    // Load current parkaran from library
    const lib = getLibrary();
    if (lib.currentId && lib.parkarans[lib.currentId]) {
        State.parkaran = [...lib.parkarans[lib.currentId].items];
    }
    renderParkaran();
    updateLibraryNameDisplay();
}

function saveParkaran() {
    // Ensure a current library exists before writing (auto-creates on first
    // mutation after page load if we somehow got into a detached state).
    const currentId = ensureCurrentLibrary();
    const lib = getLibrary();
    if (lib.parkarans[currentId]) {
        lib.parkarans[currentId].items = [...State.parkaran];
        lib.parkarans[currentId].updated = new Date().toISOString();
        setLibrary(lib);
    }
    // Also keep a working copy for fast restore
    localStorage.setItem("parkaran_working", JSON.stringify(State.parkaran));
    updateLibraryNameDisplay();
}

function saveCurrentParkaran(name) {
    if (State.parkaran.length === 0) return;
    const lib = getLibrary();
    const id = lib.currentId || generateId();
    lib.parkarans[id] = {
        name: name || autoName(State.parkaran),
        items: [...State.parkaran],
        created: lib.parkarans[id]?.created || new Date().toISOString(),
        updated: new Date().toISOString(),
    };
    lib.currentId = null; // detach — we're starting fresh
    setLibrary(lib);

    // Reset explore to clean slate
    resetExplore();
    showToast(`Saved: ${lib.parkarans[id].name}`);
}

function loadParkaran(id) {
    const lib = getLibrary();
    const entry = lib.parkarans[id];
    if (!entry) return;

    State.parkaran = [...entry.items];
    lib.currentId = id;
    setLibrary(lib);

    // Re-apply in-parkaran markers on graph
    if (State.cy) {
        State.cy.nodes(".in-parkaran").removeClass("in-parkaran");
        State.parkaran.forEach((p) => {
            const el = State.cy.getElementById(String(p.id));
            if (el?.length) el.addClass("in-parkaran");
        });
    }

    libraryView = false;
    renderParkaran();
    redrawParkaranTrail();
    updateLibraryNameDisplay();

    // Fix #9: re-center the graph on the first shabad in the loaded library so
    // the user has an immediately explorable context that matches the set they
    // just loaded. Previously the graph would stay on whatever was there before
    // (or be empty), leaving no connection between the library and the graph view.
    if (State.parkaran.length > 0) {
        const firstId = String(State.parkaran[0].id);
        if (firstId !== String(State.centerNode)) {
            expandShabad(firstId);
        }
    }
}

function deleteParkaran(id) {
    const lib = getLibrary();
    delete lib.parkarans[id];
    if (lib.currentId === id) {
        lib.currentId = null;
        State.parkaran = [];
    }
    setLibrary(lib);
    showLibrary(); // refresh library view
}

function listSavedParkarans() {
    const lib = getLibrary();
    return Object.entries(lib.parkarans)
        .map(([id, p]) => ({ id, name: p.name, count: p.items.length, created: p.created, updated: p.updated }))
        .sort((a, b) => (b.updated || b.created || "").localeCompare(a.updated || a.created || ""));
}

function resetExplore() {
    State.parkaran = [];
    const lib = getLibrary();
    lib.currentId = null;
    setLibrary(lib);
    resetGraph();
    // Clear search
    const searchInput = document.getElementById("graphSearch");
    if (searchInput) searchInput.value = "";
    const dropdown = document.getElementById("searchDropdown");
    if (dropdown) dropdown.classList.add("hidden");
    // Hide threshold
    const thresholdControl = document.getElementById("thresholdControl");
    if (thresholdControl) thresholdControl.style.display = "none";
    libraryView = false;
    renderParkaran();
}

function showSaveDialog() {
    if (State.parkaran.length === 0) return;
    const container = document.getElementById("libraryList");
    const suggested = autoName(State.parkaran);
    container.innerHTML = `
        <div style="padding:12px;">
            <div style="font-family:'IBM Plex Mono';color:#6b5f52;font-size:10px;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:8px;">Save Set</div>
            <input id="saveNameInput" type="text" value="${escAttr(suggested)}"
                   style="width:100%;background:rgba(255,255,255,0.03);border:1px solid rgba(245,158,11,0.15);border-radius:4px;color:#fbbf24;font-family:'IBM Plex Mono';font-size:12px;padding:8px;outline:none;"
                   onfocus="this.select()">
            <div style="display:flex;gap:6px;margin-top:8px;">
                <button onclick="saveCurrentParkaran(document.getElementById('saveNameInput').value)"
                        style="flex:1;background:rgba(245,158,11,0.15);color:#fbbf24;border:1px solid rgba(245,158,11,0.3);border-radius:4px;padding:6px;font-family:'IBM Plex Mono';font-size:10px;cursor:pointer;text-transform:uppercase;letter-spacing:0.05em;">Save</button>
                <button onclick="renderParkaran()"
                        style="flex:1;background:transparent;color:#6b5f52;border:1px solid rgba(255,255,255,0.05);border-radius:4px;padding:6px;font-family:'IBM Plex Mono';font-size:10px;cursor:pointer;text-transform:uppercase;">Cancel</button>
            </div>
        </div>
    `;
    document.getElementById("saveNameInput").focus();
}

function showLibrary() {
    libraryView = true;
    const container = document.getElementById("libraryList");
    const empty = document.getElementById("libraryEmpty");
    const countEl = document.getElementById("libraryCount");
    empty.classList.add("hidden");

    const saved = listSavedParkarans();
    countEl.textContent = String(saved.length);

    if (saved.length === 0) {
        container.innerHTML = `
            <div style="text-align:center;padding:24px 12px;">
                <div style="font-family:'IBM Plex Mono';color:#6b5f52;font-size:10px;letter-spacing:0.05em;">No saved sets yet</div>
                <div style="font-family:'IBM Plex Mono';color:#4a3f35;font-size:9px;margin-top:4px;">Build a set and click SAVE</div>
            </div>
        `;
    } else {
        container.innerHTML = saved.map((p) => `
            <div class="parkaran-sidebar-item" style="cursor:pointer;" onclick="loadParkaran('${escAttr(p.id)}')">
                <div style="flex:1;min-width:0;">
                    <div style="font-family:'IBM Plex Mono';color:#fbbf24;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(p.name)}</div>
                    <div style="font-family:'IBM Plex Mono';color:#4a3f35;font-size:9px;">${p.count} shabads &middot; ${new Date(p.updated || p.created).toLocaleDateString()}</div>
                </div>
                <button onclick="event.stopPropagation(); deleteParkaran('${escAttr(p.id)}')"
                        style="color:#4a3f35;cursor:pointer;font-size:14px;flex-shrink:0;background:none;border:none;"
                        onmouseover="this.style.color='#ef4444'" onmouseout="this.style.color='#4a3f35'">&times;</button>
            </div>
        `).join("");
    }

    // Add NEW + BACK buttons
    container.insertAdjacentHTML("beforeend", `
        <div style="display:flex;gap:6px;padding:8px 4px;margin-top:4px;">
            <button onclick="resetExplore()"
                    style="flex:1;background:rgba(245,158,11,0.1);color:#fbbf24;border:1px solid rgba(245,158,11,0.2);border-radius:4px;padding:6px;font-family:'IBM Plex Mono';font-size:10px;cursor:pointer;text-transform:uppercase;letter-spacing:0.05em;">+ New</button>
            <button onclick="libraryView=false; renderParkaran();"
                    style="flex:1;background:transparent;color:#6b5f52;border:1px solid rgba(255,255,255,0.05);border-radius:4px;padding:6px;font-family:'IBM Plex Mono';font-size:10px;cursor:pointer;text-transform:uppercase;">Back</button>
        </div>
    `);
}

function showToast(message) {
    const toast = document.createElement("div");
    toast.className = "parkaran-toast";
    toast.textContent = message;
    document.body.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add("show"));
    setTimeout(() => {
        toast.classList.remove("show");
        setTimeout(() => toast.remove(), 300);
    }, 2000);
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
    redrawParkaranTrail();
}

function removeFromParkaran(shabadId) {
    const sid = String(shabadId);
    State.parkaran = State.parkaran.filter((p) => String(p.id) !== sid);

    const el = State.cy?.getElementById(sid);
    if (el?.length) el.removeClass("in-parkaran");

    saveParkaran();
    renderParkaran();
    redrawParkaranTrail();
}

function redrawParkaranTrail() {
    const cy = State.cy;
    if (!cy) return;
    // Remove old trail edges
    cy.edges(".parkaran-trail").remove();
    // Draw green directed edges between consecutive parkaran shabads
    for (let pi = 0; pi < State.parkaran.length - 1; pi++) {
        const fromId = String(State.parkaran[pi].id);
        const toId = String(State.parkaran[pi + 1].id);
        const fromEl = cy.getElementById(fromId);
        const toEl = cy.getElementById(toId);
        if (fromEl.length && toEl.length) {
            const trailEdgeId = `ptrail_${fromId}_${toId}`;
            if (cy.getElementById(trailEdgeId).length === 0) {
                cy.add({
                    group: "edges",
                    data: { id: trailEdgeId, source: fromId, target: toId },
                    classes: "parkaran-trail",
                });
            }
        }
    }
}

function renderParkaran() {
    const container = document.getElementById("libraryList");
    const empty = document.getElementById("libraryEmpty");
    const countEl = document.getElementById("libraryCount");

    countEl.textContent = String(State.parkaran.length);

    // Update the Review tab's disabled state whenever library changes
    if (typeof updateReviewTabState === "function") {
        updateReviewTabState();
    }

    // If the reviewer tab is currently visible, re-render its detail
    if (typeof refreshReviewTabIfActive === "function") {
        refreshReviewTabIfActive();
    }

    if (State.parkaran.length === 0) {
        empty.classList.remove("hidden");
        container.innerHTML = "";
        return;
    }

    empty.classList.add("hidden");

    // Rebuild all items (libraryEmpty lives as a sibling outside the item list area)
    let html = "";
    State.parkaran.forEach((s, i) => {
        const rep = s.is_repertoire ? " &#9733;" : "";
        html += `
            <div class="parkaran-sidebar-item" draggable="true" data-idx="${i}" data-id="${escAttr(s.id)}">
                <span style="font-family:'IBM Plex Mono';color:rgba(245,158,11,0.3);font-size:12px;width:16px;flex-shrink:0;">${i + 1}</span>
                <div style="flex:1;min-width:0;user-select:none;">
                    ${s.gurmukhi ? `<div lang="pa-Guru" style="font-family:'Noto Sans Gurmukhi';color:#fbbf24;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(trunc(s.gurmukhi, 22))}${rep}</div>` : ""}
                    <div style="font-family:'IBM Plex Mono';color:#6b5f52;font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(trunc(s.title, 25))}</div>
                </div>
                <button onclick="event.stopPropagation(); removeFromParkaran('${escAttr(s.id)}')" style="color:#4a3f35;cursor:pointer;font-size:14px;flex-shrink:0;background:none;border:none;" onmouseover="this.style.color='#ef4444'" onmouseout="this.style.color='#4a3f35'">&times;</button>
            </div>
        `;
    });
    container.innerHTML = html;

    setupParkaranDrag();
}

function setupParkaranDrag() {
    const container = document.getElementById("libraryList");
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

/* ===== TAB SWITCHING (Batch 3 unified UI) ===== */

let activeTab = "explore";

function switchToTab(tabName) {
    if (tabName !== "explore" && tabName !== "review") return;

    // Block switch to review if library is empty
    if (tabName === "review" && State.parkaran.length === 0) {
        return;
    }

    activeTab = tabName;

    // Toggle pane visibility
    document.getElementById("exploreTab")?.classList.toggle("hidden", tabName !== "explore");
    document.getElementById("reviewTab")?.classList.toggle("hidden", tabName !== "review");

    // Toggle explore command bar (search, tags, random) — only show in explore mode
    const cmdBar = document.getElementById("exploreCommandBar");
    if (cmdBar) cmdBar.style.display = tabName === "explore" ? "flex" : "none";

    // Tab button active state
    document.getElementById("tabExplore")?.classList.toggle("active", tabName === "explore");
    document.getElementById("tabReview")?.classList.toggle("active", tabName === "review");

    // When switching to explore, recompute Cytoscape layout (container may have been hidden)
    if (tabName === "explore" && State.cy) {
        requestAnimationFrame(() => {
            State.cy.resize();
            if (State.centerNode) State.cy.fit(50);
        });
    }

    // When switching to review, initialize the detail view from current library
    if (tabName === "review" && typeof initReviewTab === "function") {
        initReviewTab();
    }
}

function updateReviewTabState() {
    const reviewTab = document.getElementById("tabReview");
    if (!reviewTab) return;
    const empty = State.parkaran.length === 0;
    reviewTab.disabled = empty;
    reviewTab.title = empty ? "Add shabads to your library first" : "";
    // If currently on review tab but library became empty, bounce back to explore
    if (activeTab === "review" && empty) {
        switchToTab("explore");
    }
}

function refreshReviewTabIfActive() {
    if (activeTab === "review" && typeof initReviewTab === "function") {
        initReviewTab();
    }
}

/* ===== LIBRARY AUTO-CREATE + MANAGEMENT ===== */

function ensureCurrentLibrary() {
    const lib = getLibrary();
    if (lib.currentId && lib.parkarans[lib.currentId]) {
        return lib.currentId;
    }
    // Create a new library named by date
    const id = generateId();
    const now = new Date();
    const dateStr = now.toLocaleDateString(undefined, {
        month: "short", day: "numeric", year: "numeric",
    });
    const timeStr = now.toLocaleTimeString(undefined, {
        hour: "2-digit", minute: "2-digit",
    });
    lib.parkarans[id] = {
        name: `Library ${dateStr} ${timeStr}`,
        items: [],
        created: now.toISOString(),
        updated: now.toISOString(),
    };
    lib.currentId = id;
    setLibrary(lib);
    return id;
}

function updateLibraryNameDisplay() {
    const nameEl = document.getElementById("libraryName");
    if (!nameEl) return;
    const lib = getLibrary();
    const current = lib.currentId ? lib.parkarans[lib.currentId] : null;
    const name = current?.name || "LIBRARY";
    nameEl.textContent = name;
    nameEl.title = name;
}

function openLibraryModal() {
    const modal = document.getElementById("libraryModal");
    const content = document.getElementById("libraryModalContent");
    if (!modal || !content) return;

    const lib = getLibrary();
    const saved = listSavedParkarans();
    const currentId = lib.currentId;

    const rowsHtml = saved.length === 0
        ? `<div class="preview-english" style="padding:16px 4px;text-align:center;opacity:0.6;">No saved libraries yet.</div>`
        : saved.map((p) => {
            const isCurrent = p.id === currentId;
            return `
                <div class="library-modal-row ${isCurrent ? "current" : ""}" data-id="${escAttr(p.id)}">
                    <div style="min-width:0;flex:1;">
                        <div class="library-modal-row-name">${escapeHtml(p.name)}${isCurrent ? " <span style='opacity:0.6;font-size:9px;'>&middot; current</span>" : ""}</div>
                        <div class="library-modal-row-meta">${p.count} shabad${p.count === 1 ? "" : "s"} &middot; ${new Date(p.updated || p.created).toLocaleDateString()}</div>
                    </div>
                    <button class="library-modal-delete" data-id="${escAttr(p.id)}" aria-label="Delete library">&times;</button>
                </div>
            `;
        }).join("");

    content.innerHTML = `
        <div class="preview-header">
            <span>MANAGE LIBRARIES</span>
            <button class="preview-close" onclick="closeLibraryModal()" aria-label="Close library manager">&times;</button>
        </div>
        <div class="library-modal-list">
            ${rowsHtml}
        </div>
        <div class="library-modal-actions">
            <button class="btn-secondary" onclick="newLibrary()">+ New library</button>
            <button class="btn-ghost" onclick="renameCurrentLibrary()">Rename current</button>
        </div>
    `;

    // Wire up row clicks (load) and delete clicks (delete)
    content.querySelectorAll(".library-modal-row").forEach((row) => {
        row.addEventListener("click", (e) => {
            if (e.target.closest(".library-modal-delete")) return;
            const id = row.dataset.id;
            loadParkaran(id);
            closeLibraryModal();
        });
    });
    content.querySelectorAll(".library-modal-delete").forEach((btn) => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const id = btn.dataset.id;
            const entry = getLibrary().parkarans[id];
            if (entry && window.confirm(`Delete "${entry.name}"?\n\nThis cannot be undone.`)) {
                deleteParkaran(id);
                openLibraryModal(); // refresh
            }
        });
    });

    modal.classList.remove("hidden");
}

function closeLibraryModal() {
    document.getElementById("libraryModal")?.classList.add("hidden");
}

function newLibrary() {
    // Detach current and auto-create a fresh library
    const lib = getLibrary();
    lib.currentId = null;
    setLibrary(lib);
    State.parkaran = [];
    ensureCurrentLibrary();
    resetGraph();
    renderParkaran();
    updateLibraryNameDisplay();
    closeLibraryModal();
}

function renameCurrentLibrary() {
    const lib = getLibrary();
    const current = lib.currentId ? lib.parkarans[lib.currentId] : null;
    if (!current) return;
    const newName = window.prompt("Rename this library:", current.name);
    if (newName && newName.trim()) {
        current.name = newName.trim();
        current.updated = new Date().toISOString();
        setLibrary(lib);
        updateLibraryNameDisplay();
        openLibraryModal(); // refresh
    }
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
