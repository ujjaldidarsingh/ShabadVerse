/**
 * Database view: search, filter, and browse shabads.
 * Supports both local filtering and BaniDB first-letter search.
 */

let allShabads = [];
let keertanis = [];
let expandedId = null;
let banidbResults = null; // null = showing local, array = showing BaniDB results

const dbPlaceholders = {
    "1": "First letters e.g. 'h k s j k'...",
    "2": "First letters (anywhere) e.g. 'h k s j k'...",
    "4": "English keyword e.g. 'surrender'...",
    "6": "Transliteration e.g. 'har kar simran'...",
    "local": "Search by title, keertani, theme...",
};

async function init() {
    try {
        const [shabads, keertaniList, raagData] = await Promise.all([
            API.get("/api/shabads"),
            API.get("/api/keertanis"),
            API.get("/api/raags"),
        ]);

        allShabads = shabads;
        keertanis = keertaniList;

        // Populate filter dropdowns
        const keertaniSelect = document.getElementById("filterKeertani");
        const uniqueKeertanis = [...new Set(shabads.map(s => s.keertani))].sort();
        uniqueKeertanis.forEach(k => {
            const opt = document.createElement("option");
            opt.value = k;
            opt.textContent = k;
            keertaniSelect.appendChild(opt);
        });

        const raagSelect = document.getElementById("filterRaag");
        raagData.sggs_raags.forEach(r => {
            const opt = document.createElement("option");
            opt.value = r;
            opt.textContent = r;
            raagSelect.appendChild(opt);
        });

        // Setup search type switcher
        const searchTypeSelect = document.getElementById("searchType");
        const searchInput = document.getElementById("search");

        searchTypeSelect.addEventListener("change", () => {
            searchInput.placeholder = dbPlaceholders[searchTypeSelect.value] || dbPlaceholders["local"];
            searchInput.value = "";
            banidbResults = null;
            renderShabads(allShabads);
            updateStats(allShabads);
        });

        renderShabads(shabads);
        updateStats(shabads);
    } catch (err) {
        document.getElementById("shabadList").innerHTML =
            `<p class="text-red-400 text-center py-8">Error loading data: ${escapeHtml(err.message)}</p>`;
    }
}

function renderShabads(shabads) {
    const container = document.getElementById("shabadList");

    if (shabads.length === 0) {
        container.innerHTML = '<p class="text-gray-500 text-center py-8">No shabads match your search.</p>';
        return;
    }

    container.innerHTML = shabads.map(s => {
        // Support both local shabads and BaniDB results
        const isLocal = !!s.id && !s._banidb_only;
        const shabadId = s.id || s.banidb_shabad_id;

        return `
        <div class="card cursor-pointer" onclick="${isLocal ? `toggleExpand(${shabadId})` : `viewBanidbShabad(${s.banidb_shabad_id})`}">
            <div class="flex items-center justify-between gap-3">
                <div class="flex-1 min-w-0">
                    ${s.title_gurmukhi ? `<div style="font-family:'Noto Sans Gurmukhi',serif;color:var(--star-glow);font-size:16px;line-height:1.8;margin-bottom:2px;">${escapeHtml(s.title_gurmukhi)}</div>` : ""}
                    <div class="font-medium text-gray-100 truncate">${escapeHtml(s.title || s.title_transliteration || "Unknown")}</div>
                    <div class="text-sm text-gray-500 mt-0.5">
                        ${escapeHtml(s.keertani || s.writer || "")}
                        ${s.ang_number ? `<span class="text-gray-600 mx-1">&middot;</span> Ang ${s.ang_number}` : ""}
                        ${(s.writer && s.keertani) ? `<span class="text-gray-600 mx-1">&middot;</span> ${escapeHtml(s.writer)}` : ""}
                    </div>
                </div>
                <div class="flex items-center gap-2 flex-shrink-0">
                    ${s.sggs_raag || s.raag ? `<span class="badge badge-raag">${escapeHtml(s.sggs_raag || s.raag)}</span>` : ""}
                    ${s.primary_theme ? `<span class="badge badge-theme hidden sm:inline-flex">${escapeHtml(s.primary_theme)}</span>` : ""}
                    ${s.confidence ? confidenceBadge(s.confidence) : ""}
                    ${s._banidb_only ? (s.in_personal_db ? '<span class="badge-library">Library</span>' : '<span class="badge-sggs">SGGS</span>') : ""}
                </div>
            </div>
            ${isLocal ? `<div id="details-${shabadId}" class="shabad-details mt-3"><div class="loading-pulse text-gray-500 text-sm">Loading details...</div></div>` : ""}
        </div>`;
    }).join("");
}

async function toggleExpand(id) {
    const el = document.getElementById(`details-${id}`);

    if (expandedId === id) {
        el.classList.remove("open");
        expandedId = null;
        return;
    }

    // Close previous
    if (expandedId) {
        const prev = document.getElementById(`details-${expandedId}`);
        if (prev) prev.classList.remove("open");
    }

    expandedId = id;

    try {
        const s = await API.get(`/api/shabads/${id}`);
        el.innerHTML = `
            <div class="border-t border-white/5 pt-3 space-y-3">
                ${s.gurmukhi_text ? `
                    <div>
                        <div class="detail-label">Gurmukhi</div>
                        <div class="gurmukhi">${escapeHtml(s.gurmukhi_text)}</div>
                    </div>
                ` : ""}
                ${s.english_translation ? `
                    <div>
                        <div class="detail-label">Translation</div>
                        <div class="text-gray-300 text-sm leading-relaxed">${escapeHtml(s.english_translation)}</div>
                    </div>
                ` : ""}
                ${s.brief_meaning ? `
                    <div>
                        <div class="detail-label">Summary</div>
                        <div class="text-gray-400 text-sm">${escapeHtml(s.brief_meaning)}</div>
                    </div>
                ` : ""}
                <div class="flex flex-wrap gap-4 text-sm">
                    ${s.sggs_raag ? `<div><span class="text-gray-600">SGGS Raag:</span> <span class="text-indigo-300">${escapeHtml(s.sggs_raag)}</span></div>` : ""}
                    ${s.performance_raag ? `<div><span class="text-gray-600">Performance Raag:</span> <span class="text-indigo-300">${escapeHtml(s.performance_raag)}</span></div>` : ""}
                    ${s.mood ? `<div><span class="text-gray-600">Mood:</span> <span class="text-gold-400">${escapeHtml(s.mood)}</span></div>` : ""}
                    ${s.ang_number ? `<div><span class="text-gray-600">Ang:</span> <span class="text-gray-300">${s.ang_number}</span></div>` : ""}
                </div>
                ${s.secondary_themes && s.secondary_themes.length ? `
                    <div class="flex flex-wrap gap-1.5">
                        ${s.secondary_themes.map(t => `<span class="badge badge-theme">${escapeHtml(t)}</span>`).join("")}
                    </div>
                ` : ""}
                ${s.link ? `<a href="${escapeHtml(s.link)}" target="_blank" class="text-gold-500 text-sm hover:underline inline-block">Listen &rarr;</a>` : ""}
            </div>
        `;
    } catch (err) {
        el.innerHTML = `<p class="text-red-400 text-sm">Error loading details</p>`;
    }

    el.classList.add("open");
}

// BaniDB shabad detail (redirect to discover page's detail view)
function viewBanidbShabad(banidbId) {
    window.location.href = `/discover?shabad=${banidbId}`;
}

async function filterShabads() {
    const q = document.getElementById("search").value.trim();
    const searchType = document.getElementById("searchType").value;
    const keertani = document.getElementById("filterKeertani").value;
    const raag = document.getElementById("filterRaag").value;
    const confidence = document.getElementById("filterConfidence").value;

    // If search type is not "local", do a BaniDB search
    if (searchType !== "local" && q.length >= 2) {
        try {
            const results = await API.get(`/api/discover/search?q=${encodeURIComponent(q)}&searchtype=${searchType}`);
            banidbResults = results.map(r => ({
                ...r,
                title: r.title_transliteration,
                _banidb_only: true,
            }));

            // Apply local filters on top
            let filtered = banidbResults;
            if (raag) {
                filtered = filtered.filter(s => s.raag === raag);
            }

            renderShabads(filtered);
            updateStats(filtered, true);
        } catch (err) {
            document.getElementById("shabadList").innerHTML =
                `<p class="text-red-400 text-center py-8">Search error: ${escapeHtml(err.message)}</p>`;
        }
        return;
    }

    // Local filtering
    banidbResults = null;
    let filtered = allShabads;

    if (q) {
        const ql = q.toLowerCase();
        filtered = filtered.filter(s =>
            s.title.toLowerCase().includes(ql) ||
            (s.keertani || "").toLowerCase().includes(ql) ||
            (s.primary_theme || "").toLowerCase().includes(ql) ||
            (s.writer || "").toLowerCase().includes(ql)
        );
    }
    if (keertani) {
        filtered = filtered.filter(s => s.keertani === keertani);
    }
    if (raag) {
        filtered = filtered.filter(s => s.sggs_raag === raag || s.performance_raag === raag);
    }
    if (confidence) {
        filtered = filtered.filter(s => s.confidence === confidence);
    }

    expandedId = null;
    renderShabads(filtered);
    updateStats(filtered);
}

function updateStats(shabads, isBanidb = false) {
    if (isBanidb) {
        document.getElementById("stats").textContent =
            `Found ${shabads.length} shabads from SGGS`;
    } else {
        const enriched = shabads.filter(s => s.enrichment_status === "complete").length;
        document.getElementById("stats").textContent =
            `Showing ${shabads.length} shabads (${enriched} enriched)`;
    }
}

// Event listeners
const searchInput = document.getElementById("search");
searchInput.addEventListener("input", debounce(filterShabads, 400));
searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") filterShabads();
});
document.getElementById("filterKeertani").addEventListener("change", filterShabads);
document.getElementById("filterRaag").addEventListener("change", filterShabads);
document.getElementById("filterConfidence").addEventListener("change", filterShabads);

init();
