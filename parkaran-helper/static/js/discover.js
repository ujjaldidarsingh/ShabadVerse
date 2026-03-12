/**
 * Discover page: BaniDB search, detail view, enrichment, and seed handoff.
 */

let searchResults = [];
let currentDetail = null; // full shabad data for the modal

const searchInput = document.getElementById("discoverSearch");
const searchTypeSelect = document.getElementById("searchType");

const placeholders = {
    "1": "First letters e.g. 'h k s j k' for Har Kar Simran Jo Karai...",
    "2": "First letters (anywhere) e.g. 'h k s j k'...",
    "4": "English keyword e.g. 'surrender', 'protection', 'love'...",
    "6": "Transliteration e.g. 'har kar simran'...",
};

searchTypeSelect.addEventListener("change", () => {
    searchInput.placeholder = placeholders[searchTypeSelect.value] || placeholders["1"];
    searchInput.value = "";
    searchInput.focus();
});

// Enter key triggers search
searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") doSearch();
});

async function doSearch() {
    const q = searchInput.value.trim();
    const searchType = searchTypeSelect.value;
    if (q.length < 2) return;

    const resultsDiv = document.getElementById("results");
    const countDiv = document.getElementById("resultsCount");
    resultsDiv.innerHTML = '<div class="loading-pulse text-gray-500 text-center py-12">Searching BaniDB...</div>';
    countDiv.classList.add("hidden");

    try {
        const results = await API.get(`/api/discover/search?q=${encodeURIComponent(q)}&searchtype=${searchType}`);
        searchResults = results;

        if (results.length === 0) {
            resultsDiv.innerHTML = '<p class="text-gray-600 text-center py-12">No shabads found. Try a different keyword.</p>';
            return;
        }

        countDiv.textContent = `${results.length} shabad${results.length !== 1 ? "s" : ""} found`;
        countDiv.classList.remove("hidden");

        resultsDiv.innerHTML = results.map((s, i) => `
            <div class="discover-card cursor-pointer" onclick="viewShabad(${s.banidb_shabad_id})">
                <div class="flex items-start gap-3">
                    <div class="flex-1 min-w-0">
                        <div class="text-xl text-gold-300/80 leading-relaxed">${escapeHtml(s.title_gurmukhi || "")}</div>
                        <div class="font-medium text-gray-200 mt-1">${escapeHtml(s.title_transliteration || "")}</div>
                        <div class="text-sm text-gray-400 mt-1 line-clamp-2">${escapeHtml(s.first_line_translation || "")}</div>
                        <div class="flex items-center gap-3 mt-2 text-xs text-gray-500">
                            ${s.ang_number ? `<span>Ang ${s.ang_number}</span>` : ""}
                            ${s.raag ? `<span>&middot; ${escapeHtml(s.raag)}</span>` : ""}
                            ${s.writer ? `<span>&middot; ${escapeHtml(s.writer)}</span>` : ""}
                        </div>
                    </div>
                    <div class="flex flex-col items-end gap-1 flex-shrink-0">
                        ${s.in_personal_db
                            ? '<span class="badge-library">In Library</span>'
                            : '<span class="badge-sggs">SGGS</span>'}
                    </div>
                </div>
            </div>
        `).join("");
    } catch (err) {
        resultsDiv.innerHTML = `<p class="text-red-400 text-center py-8">Error: ${escapeHtml(err.message)}</p>`;
    }
}

async function viewShabad(banidbId) {
    const modal = document.getElementById("detailModal");
    const titleEl = document.getElementById("detailTitle");
    const metaEl = document.getElementById("detailMeta");
    const gurmukhiEl = document.getElementById("detailGurmukhi");
    const translationEl = document.getElementById("detailTranslation");
    const themesDiv = document.getElementById("detailThemes");
    const enrichBtn = document.getElementById("enrichBtn");

    // Show modal with loading state
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    titleEl.textContent = "Loading...";
    metaEl.textContent = "";
    gurmukhiEl.textContent = "";
    translationEl.textContent = "";
    themesDiv.classList.add("hidden");
    enrichBtn.disabled = false;
    enrichBtn.textContent = "Extract Themes (AI)";

    try {
        const detail = await API.get(`/api/discover/shabad/${banidbId}`);
        currentDetail = detail;

        // Title: first line of transliteration
        const firstLine = (detail.transliteration || "").split(" ").slice(0, 8).join(" ");
        titleEl.textContent = firstLine || `Shabad ${banidbId}`;

        metaEl.innerHTML = [
            detail.ang_number ? `Ang ${detail.ang_number}` : "",
            detail.sggs_raag || "",
            detail.writer || "",
            `${detail.verse_count || "?"} verses`,
        ].filter(Boolean).join(" &middot; ");

        // Gurmukhi text (show line breaks)
        gurmukhiEl.innerHTML = (detail.gurmukhi_text || "").split("\n").map(l => escapeHtml(l)).join("<br>");

        // English translation
        translationEl.textContent = detail.english_translation || "Translation not available.";

        // If themes already cached, show them
        if (detail.primary_theme) {
            showThemes(detail);
        }
    } catch (err) {
        titleEl.textContent = "Error loading shabad";
        translationEl.textContent = err.message;
    }
}

function closeDetail() {
    const modal = document.getElementById("detailModal");
    modal.classList.add("hidden");
    modal.classList.remove("flex");
    currentDetail = null;
}

// Close modal on backdrop click
document.getElementById("detailModal").addEventListener("click", (e) => {
    if (e.target === e.currentTarget) closeDetail();
});

// Close modal on Escape
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDetail();
});

async function enrichCurrent() {
    if (!currentDetail) return;

    const btn = document.getElementById("enrichBtn");
    btn.disabled = true;
    btn.textContent = "Analyzing with AI...";

    try {
        const themes = await API.post("/api/discover/enrich", {
            banidb_shabad_id: currentDetail.banidb_shabad_id,
            english_translation: currentDetail.english_translation || "",
            transliteration: currentDetail.transliteration || "",
            raag: currentDetail.sggs_raag || "",
            writer: currentDetail.writer || "",
        });

        // Merge into current detail
        Object.assign(currentDetail, themes);
        showThemes(currentDetail);
        btn.textContent = "Themes Extracted";
    } catch (err) {
        btn.textContent = "Error — Try Again";
        btn.disabled = false;
    }
}

function showThemes(detail) {
    const themesDiv = document.getElementById("detailThemes");
    const content = document.getElementById("detailThemeContent");

    let html = "";
    if (detail.primary_theme) {
        html += `<div class="text-sm text-gold-400 font-medium mb-1">${escapeHtml(detail.primary_theme)}</div>`;
    }
    if (detail.secondary_themes && detail.secondary_themes.length) {
        html += `<div class="text-xs text-gray-400 mb-1">${detail.secondary_themes.map(t => escapeHtml(t)).join(" &middot; ")}</div>`;
    }
    if (detail.mood) {
        html += `<div class="text-xs text-gray-500">Mood: ${escapeHtml(detail.mood)}</div>`;
    }
    if (detail.brief_meaning) {
        html += `<div class="text-sm text-gray-300 mt-2">${escapeHtml(detail.brief_meaning)}</div>`;
    }

    content.innerHTML = html;
    themesDiv.classList.remove("hidden");

    // Update enrich button
    const btn = document.getElementById("enrichBtn");
    btn.textContent = "Themes Extracted";
    btn.disabled = true;
}

function useAsSeed() {
    if (!currentDetail) return;

    // Store the seed in sessionStorage for the builder to pick up
    const seedData = {
        banidb_shabad_id: currentDetail.banidb_shabad_id,
        title: (currentDetail.transliteration || "").split(" ").slice(0, 8).join(" "),
        title_gurmukhi: currentDetail.gurmukhi_text ? currentDetail.gurmukhi_text.split("\n")[0] : "",
        english_translation: currentDetail.english_translation || "",
        transliteration: currentDetail.transliteration || "",
        sggs_raag: currentDetail.sggs_raag || "",
        writer: currentDetail.writer || "",
        ang_number: currentDetail.ang_number,
        primary_theme: currentDetail.primary_theme || null,
        secondary_themes: currentDetail.secondary_themes || [],
        mood: currentDetail.mood || null,
        brief_meaning: currentDetail.brief_meaning || null,
    };

    sessionStorage.setItem("discoverSeed", JSON.stringify(seedData));
    window.location.href = "/builder";
}
