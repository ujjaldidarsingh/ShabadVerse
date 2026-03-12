/**
 * Parkaran Builder: seed selection (personal + BaniDB), suggestion display, and parkaran assembly.
 */

let allShabads = [];
let seeds = [];       // Mixed: personal DB shabads (have .id) and BaniDB shabads (have .banidb_shabad_id)
let parkaran = [];    // Mixed: same types
let lastSuggestions = []; // Store last build suggestions for lookup
let currentSeedSource = "my"; // "my" or "discover"

function isBanidbSeed(s) {
    return !!s.banidb_shabad_id && !s.id;
}

function seedKey(s) {
    return isBanidbSeed(s) ? `banidb_${s.banidb_shabad_id}` : `personal_${s.id}`;
}

async function init() {
    try {
        const [shabads, raags] = await Promise.all([
            API.get("/api/shabads"),
            API.get("/api/raags"),
        ]);
        allShabads = shabads;

        const keertaniSelect = document.getElementById("builderFilterKeertani");
        const uniqueKeertanis = [...new Set(shabads.map(s => s.keertani))].sort();
        uniqueKeertanis.forEach(k => {
            const opt = document.createElement("option");
            opt.value = k;
            opt.textContent = k;
            keertaniSelect.appendChild(opt);
        });

        const raagSelect = document.getElementById("builderFilterRaag");
        raags.sggs_raags.forEach(r => {
            const opt = document.createElement("option");
            opt.value = r;
            opt.textContent = r;
            raagSelect.appendChild(opt);
        });

        // Check for seed passed from Discover page
        const discoverSeedJson = sessionStorage.getItem("discoverSeed");
        if (discoverSeedJson) {
            sessionStorage.removeItem("discoverSeed");
            const discoverSeed = JSON.parse(discoverSeedJson);
            seeds.push(discoverSeed);
            switchSeedSource("discover");
            renderSeeds();
        }
    } catch (err) {
        console.error("Init error:", err);
    }
}

// --- Seed source switching ---

function switchSeedSource(source) {
    currentSeedSource = source;
    const myTab = document.getElementById("tabMyDb");
    const discoverTab = document.getElementById("tabDiscover");
    const mySearch = document.getElementById("seedSourceMy");
    const discoverSearch = document.getElementById("seedSourceDiscover");

    if (source === "my") {
        myTab.classList.add("active");
        discoverTab.classList.remove("active");
        mySearch.classList.remove("hidden");
        discoverSearch.classList.add("hidden");
    } else {
        myTab.classList.remove("active");
        discoverTab.classList.add("active");
        mySearch.classList.add("hidden");
        discoverSearch.classList.remove("hidden");
    }
}

// --- Personal DB seed search (existing autocomplete) ---

const seedSearch = document.getElementById("seedSearch");
const seedDropdown = document.getElementById("seedDropdown");

seedSearch.addEventListener("input", debounce(() => {
    const q = seedSearch.value.toLowerCase().trim();
    if (q.length < 2) {
        seedDropdown.classList.add("hidden");
        return;
    }

    const matches = allShabads
        .filter(s => !seeds.find(seed => seed.id === s.id))
        .filter(s =>
            s.title.toLowerCase().includes(q) ||
            (s.keertani || "").toLowerCase().includes(q) ||
            (s.primary_theme || "").toLowerCase().includes(q)
        )
        .slice(0, 8);

    if (matches.length === 0) {
        seedDropdown.classList.add("hidden");
        return;
    }

    seedDropdown.innerHTML = matches.map(s => `
        <div class="autocomplete-item" onclick="addPersonalSeed(${s.id})">
            <div class="font-medium text-gray-200">${escapeHtml(s.title)}</div>
            <div class="text-xs text-gray-500 mt-0.5">
                ${escapeHtml(s.keertani || "")}
                ${s.sggs_raag ? ` &middot; ${escapeHtml(s.sggs_raag)}` : ""}
                ${s.primary_theme ? ` &middot; ${escapeHtml(s.primary_theme)}` : ""}
            </div>
        </div>
    `).join("");
    seedDropdown.classList.remove("hidden");
}, 200));

// --- Discover seed search (BaniDB API) ---

const discoverSeedSearch = document.getElementById("discoverSeedSearch");
const discoverSeedDropdown = document.getElementById("discoverSeedDropdown");
const discoverSearchTypeSelect = document.getElementById("discoverSearchType");

const builderPlaceholders = {
    "1": "First letters e.g. 'h k s j k'...",
    "2": "First letters (anywhere) e.g. 'h k s j k'...",
    "4": "English keyword e.g. 'surrender'...",
    "6": "Transliteration e.g. 'har kar simran'...",
};

discoverSearchTypeSelect.addEventListener("change", () => {
    discoverSeedSearch.placeholder = builderPlaceholders[discoverSearchTypeSelect.value] || builderPlaceholders["1"];
    discoverSeedSearch.value = "";
    discoverSeedDropdown.classList.add("hidden");
    discoverSeedSearch.focus();
});

discoverSeedSearch.addEventListener("input", debounce(async () => {
    const q = discoverSeedSearch.value.trim();
    if (q.length < 2) {
        discoverSeedDropdown.classList.add("hidden");
        return;
    }

    const searchType = document.getElementById("discoverSearchType").value;

    try {
        const results = await API.get(`/api/discover/search?q=${encodeURIComponent(q)}&searchtype=${searchType}`);

        if (results.length === 0) {
            discoverSeedDropdown.innerHTML = '<div class="autocomplete-item text-gray-500">No results found</div>';
            discoverSeedDropdown.classList.remove("hidden");
            return;
        }

        discoverSeedDropdown.innerHTML = results.slice(0, 8).map(s => `
            <div class="autocomplete-item" onclick='addBanidbSeed(${JSON.stringify(s).replace(/'/g, "&#39;")})'>
                <div class="flex items-center gap-2">
                    <span class="text-gold-300/70">${escapeHtml(s.title_gurmukhi || "")}</span>
                    ${s.in_personal_db ? '<span class="badge-library text-[10px]">In Library</span>' : '<span class="badge-sggs text-[10px]">SGGS</span>'}
                </div>
                <div class="text-sm text-gray-300 mt-0.5">${escapeHtml(s.title_transliteration || "")}</div>
                <div class="text-xs text-gray-500 mt-0.5">
                    ${s.ang_number ? `Ang ${s.ang_number}` : ""}
                    ${s.raag ? ` &middot; ${escapeHtml(s.raag)}` : ""}
                    ${s.writer ? ` &middot; ${escapeHtml(s.writer)}` : ""}
                </div>
            </div>
        `).join("");
        discoverSeedDropdown.classList.remove("hidden");
    } catch (err) {
        console.error("Discover search error:", err);
    }
}, 500));

// Hide dropdowns when clicking outside
document.addEventListener("click", (e) => {
    if (!e.target.closest("#seedSearch") && !e.target.closest("#seedDropdown")) {
        seedDropdown.classList.add("hidden");
    }
    if (!e.target.closest("#discoverSeedSearch") && !e.target.closest("#discoverSeedDropdown")) {
        discoverSeedDropdown.classList.add("hidden");
    }
});

// --- Add/remove seeds ---

function addPersonalSeed(id) {
    if (seeds.length >= 3) return;
    const shabad = allShabads.find(s => s.id === id);
    if (!shabad || seeds.find(s => s.id === id)) return;

    seeds.push(shabad);
    seedSearch.value = "";
    seedDropdown.classList.add("hidden");
    renderSeeds();
}

function addBanidbSeed(shabadData) {
    if (seeds.length >= 3) return;
    // If it's already in personal DB, add the personal version instead
    if (shabadData.in_personal_db && shabadData.personal_db_id) {
        addPersonalSeed(shabadData.personal_db_id);
        return;
    }
    // Check not already added
    if (seeds.find(s => s.banidb_shabad_id === shabadData.banidb_shabad_id)) return;

    // Fetch full shabad data for richer seed info
    API.get(`/api/discover/shabad/${shabadData.banidb_shabad_id}`).then(detail => {
        const seed = {
            banidb_shabad_id: shabadData.banidb_shabad_id,
            title: shabadData.title_transliteration || `Ang ${shabadData.ang_number}`,
            title_gurmukhi: shabadData.title_gurmukhi || "",
            english_translation: detail.english_translation || shabadData.first_line_translation || "",
            transliteration: detail.transliteration || "",
            sggs_raag: shabadData.raag || detail.sggs_raag || "",
            writer: shabadData.writer || detail.writer || "",
            ang_number: shabadData.ang_number || detail.ang_number,
            primary_theme: detail.primary_theme || null,
            secondary_themes: detail.secondary_themes || [],
            mood: detail.mood || null,
            brief_meaning: detail.brief_meaning || null,
        };
        seeds.push(seed);
        discoverSeedSearch.value = "";
        discoverSeedDropdown.classList.add("hidden");
        renderSeeds();
    });
}

function removeSeed(key) {
    seeds = seeds.filter(s => seedKey(s) !== key);
    renderSeeds();
}

function renderSeeds() {
    const container = document.getElementById("seedList");
    const empty = document.getElementById("seedEmpty");
    const btn = document.getElementById("buildBtn");

    if (seeds.length === 0) {
        empty.classList.remove("hidden");
        container.innerHTML = "";
        btn.disabled = true;
        enableSeedInputs();
        return;
    }

    empty.classList.add("hidden");
    container.innerHTML = seeds.map(s => {
        const key = seedKey(s);
        const isBanidb = isBanidbSeed(s);
        const title = s.title || s.title_transliteration || "Unknown";
        const subtitle = isBanidb
            ? [s.sggs_raag, s.writer, s.ang_number ? `Ang ${s.ang_number}` : ""].filter(Boolean).join(" \u00b7 ")
            : [s.keertani, s.sggs_raag].filter(Boolean).join(" \u00b7 ");
        const badge = isBanidb ? '<span class="badge-sggs text-[10px] ml-2">SGGS</span>' : '';

        return `
            <div class="seed-card flex items-center justify-between">
                <div>
                    <div class="font-medium text-gold-300">${escapeHtml(title)}${badge}</div>
                    <div class="text-xs text-gray-500">${escapeHtml(subtitle)}</div>
                </div>
                <button onclick="removeSeed('${key}')" class="text-gray-600 hover:text-red-400 text-lg">&times;</button>
            </div>
        `;
    }).join("");

    btn.disabled = false;

    if (seeds.length >= 3) {
        disableSeedInputs();
    } else {
        enableSeedInputs();
    }
}

function enableSeedInputs() {
    seedSearch.disabled = false;
    seedSearch.placeholder = "Search your shabads...";
    discoverSeedSearch.disabled = false;
    discoverSeedSearch.placeholder = builderPlaceholders[discoverSearchTypeSelect.value] || "Search entire SGGS...";
}

function disableSeedInputs() {
    seedSearch.disabled = true;
    seedSearch.placeholder = "Maximum 3 seeds selected";
    discoverSeedSearch.disabled = true;
    discoverSeedSearch.placeholder = "Maximum 3 seeds selected";
}

// --- Build parkaran ---

async function buildParkaran() {
    if (seeds.length === 0) return;

    const btn = document.getElementById("buildBtn");
    const suggestionsDiv = document.getElementById("suggestions");
    const themeDiv = document.getElementById("parkaranTheme");

    btn.disabled = true;
    btn.textContent = "Analyzing thematic connections...";
    suggestionsDiv.innerHTML = '<div class="loading-pulse text-gray-500 text-center py-8">Finding shabads with connected meanings...</div>';

    try {
        const filters = {};
        const keertani = document.getElementById("builderFilterKeertani").value;
        const raag = document.getElementById("builderFilterRaag").value;
        if (keertani) filters.keertani = keertani;
        if (raag) filters.sggs_raag = raag;

        const personalSeeds = seeds.filter(s => !isBanidbSeed(s));
        const banidbSeeds = seeds.filter(s => isBanidbSeed(s));

        const result = await API.post("/api/parkaran/build", {
            seed_shabads: personalSeeds.map(s => s.id),
            seed_banidb_shabads: banidbSeeds.map(s => ({
                banidb_shabad_id: s.banidb_shabad_id,
                title: s.title,
                english_translation: s.english_translation || "",
                transliteration: s.transliteration || "",
                primary_theme: s.primary_theme || null,
                secondary_themes: s.secondary_themes || [],
                mood: s.mood || null,
                brief_meaning: s.brief_meaning || null,
                sggs_raag: s.sggs_raag || null,
                writer: s.writer || null,
            })),
            max_results: 10,
            filters: Object.keys(filters).length ? filters : null,
        });

        // Store suggestions for later lookup
        lastSuggestions = result.suggestions || [];

        if (result.parkaran_theme) {
            themeDiv.classList.remove("hidden");
            document.getElementById("themeText").textContent = result.parkaran_theme;
        }

        if (!result.suggestions || result.suggestions.length === 0) {
            suggestionsDiv.innerHTML = '<p class="text-gray-500 text-center py-8">No suggestions found. Try different seeds or adjust filters.</p>';
        } else {
            suggestionsDiv.innerHTML = result.suggestions.map((s, idx) => {
                const isBanidb = s.source === "banidb";
                const sourceBadge = isBanidb
                    ? '<span class="badge-sggs text-[10px] ml-1">SGGS</span>'
                    : '<span class="badge-library text-[10px] ml-1">Library</span>';
                const subtitle = isBanidb
                    ? [s.sggs_raag, s.ang_number ? `Ang ${s.ang_number}` : "", s.writer].filter(Boolean).join(" \u00b7 ")
                    : [s.keertani || "", s.sggs_raag || "", s.ang_number ? `Ang ${s.ang_number}` : ""].filter(Boolean).join(" \u00b7 ");

                return `
                    <div class="suggestion-card" data-suggestion-idx="${idx}">
                        <div class="flex items-start gap-3">
                            ${scoreGauge(s.connection_score)}
                            <div class="flex-1 min-w-0">
                                <div class="flex items-center gap-2 flex-wrap">
                                    <span class="font-medium text-gray-100">${escapeHtml(s.title)}</span>
                                    ${s.suggested_position ? positionTag(s.suggested_position) : ""}
                                    ${sourceBadge}
                                </div>
                                <div class="text-xs text-gray-500 mt-0.5">${escapeHtml(subtitle)}</div>
                                <div class="text-sm text-gold-400/80 mt-1.5">${escapeHtml(s.connection_explanation)}</div>
                                ${s.brief_meaning ? `<div class="text-xs text-gray-500 mt-1">${escapeHtml(s.brief_meaning)}</div>` : ""}
                            </div>
                            <button onclick="event.stopPropagation(); addToParkaran(${idx})" class="btn-add flex-shrink-0" title="Add to parkaran">
                                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                            </button>
                        </div>
                    </div>
                `;
            }).join("");
        }
    } catch (err) {
        suggestionsDiv.innerHTML = `<p class="text-red-400 text-center py-8">Error: ${escapeHtml(err.message)}</p>`;
    }

    btn.disabled = false;
    btn.textContent = "Build Parkaran";
}

// --- Parkaran assembly ---

function addToParkaran(idx) {
    const suggestion = lastSuggestions[idx];
    if (!suggestion) return;

    // Build a unique key for dedup
    const key = suggestion.source === "banidb"
        ? `banidb_${suggestion.banidb_shabad_id || suggestion.id}`
        : `personal_${suggestion.id}`;

    if (parkaran.find(p => p._parkaran_key === key)) return;

    parkaran.push({
        ...suggestion,
        _parkaran_key: key,
        _parkaran_id: suggestion.id,
        _source: suggestion.source || "personal",
    });
    renderParkaran();
}

function addSeedsToParkaran() {
    seeds.forEach(s => {
        const key = seedKey(s);
        if (parkaran.find(p => p._parkaran_key === key)) return;
        parkaran.push({
            ...s,
            _parkaran_key: key,
            _parkaran_id: isBanidbSeed(s) ? s.banidb_shabad_id : s.id,
            _source: isBanidbSeed(s) ? "banidb" : "personal",
        });
    });
    renderParkaran();
}

function removeFromParkaran(key) {
    parkaran = parkaran.filter(p => p._parkaran_key !== key);
    renderParkaran();
}

function renderParkaran() {
    const container = document.getElementById("parkaranList");
    const empty = document.getElementById("parkaranEmpty");
    const reviewBtn = document.getElementById("reviewBtn");

    if (parkaran.length === 0) {
        empty.classList.remove("hidden");
        container.innerHTML = "";
        reviewBtn.classList.add("hidden");
        return;
    }

    empty.classList.add("hidden");
    reviewBtn.classList.remove("hidden");

    container.innerHTML = parkaran.map((s, i) => {
        const isBanidb = s._source === "banidb";
        const badge = isBanidb ? ' <span class="badge-sggs text-[10px]">SGGS</span>' : '';
        const subtitle = isBanidb ? "" : (s.keertani ? `<span class="text-gray-600 text-sm ml-2">${escapeHtml(s.keertani)}</span>` : "");
        const key = s._parkaran_key;

        return `
            <div class="parkaran-item" draggable="true" data-parkaran-idx="${i}" data-parkaran-key="${escapeHtml(key)}">
                <span class="drag-handle">&#9776;</span>
                <span class="parkaran-num">${i + 1}.</span>
                <div class="flex-1 min-w-0">
                    <span class="text-gray-200">${escapeHtml(s.title || "Unknown")}</span>${badge}
                    ${subtitle}
                </div>
                <button onclick="removeFromParkaran('${escapeHtml(key)}')" class="text-gray-600 hover:text-red-400 transition-colors">&times;</button>
            </div>
        `;
    }).join("");

    // Setup drag and drop
    setupDragAndDrop();
}

// --- Drag & Drop reordering ---

function setupDragAndDrop() {
    const container = document.getElementById("parkaranList");
    const items = container.querySelectorAll(".parkaran-item");
    let draggedIdx = null;

    items.forEach(item => {
        item.addEventListener("dragstart", (e) => {
            draggedIdx = parseInt(item.dataset.parkaranIdx);
            item.classList.add("dragging");
            e.dataTransfer.effectAllowed = "move";
        });

        item.addEventListener("dragend", () => {
            item.classList.remove("dragging");
            container.querySelectorAll(".parkaran-item").forEach(el => el.classList.remove("drag-over"));
            draggedIdx = null;
        });

        item.addEventListener("dragover", (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = "move";
            const targetIdx = parseInt(item.dataset.parkaranIdx);
            if (targetIdx !== draggedIdx) {
                item.classList.add("drag-over");
            }
        });

        item.addEventListener("dragleave", () => {
            item.classList.remove("drag-over");
        });

        item.addEventListener("drop", (e) => {
            e.preventDefault();
            item.classList.remove("drag-over");
            const targetIdx = parseInt(item.dataset.parkaranIdx);
            if (draggedIdx !== null && draggedIdx !== targetIdx) {
                // Reorder the array
                const [moved] = parkaran.splice(draggedIdx, 1);
                parkaran.splice(targetIdx, 0, moved);
                renderParkaran();
            }
        });
    });
}

function sendToReview() {
    // Only personal DB shabads can be reviewed by ID
    const personalIds = [...seeds.filter(s => !isBanidbSeed(s)).map(s => s.id), ...parkaran.filter(p => p._source === "personal").map(p => p.id || p._parkaran_id)];
    const unique = [...new Set(personalIds)].filter(Boolean);

    if (unique.length >= 2) {
        sessionStorage.setItem("reviewParkaran", JSON.stringify(unique));
        window.location.href = "/reviewer";
    } else {
        alert("Need at least 2 shabads from your library to review. SGGS-discovered shabads are not yet supported in the reviewer.");
    }
}

init();
