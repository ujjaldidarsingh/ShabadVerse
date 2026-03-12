/**
 * Parkaran Reviewer: input shabads, get thematic flow analysis.
 */

let allShabads = [];
let reviewShabads = [];

async function init() {
    try {
        allShabads = await API.get("/api/shabads");

        // Check if we came from the builder with a parkaran
        const stored = sessionStorage.getItem("reviewParkaran");
        if (stored) {
            const ids = JSON.parse(stored);
            sessionStorage.removeItem("reviewParkaran");
            for (const id of ids) {
                const s = allShabads.find(sh => sh.id === id);
                if (s) reviewShabads.push(s);
            }
            renderReviewList();
        }
    } catch (err) {
        console.error("Init error:", err);
    }
}

// Search autocomplete
const searchInput = document.getElementById("addShabadSearch");
const dropdown = document.getElementById("addDropdown");

searchInput.addEventListener("input", debounce(() => {
    const q = searchInput.value.toLowerCase().trim();
    if (q.length < 2) {
        dropdown.classList.add("hidden");
        return;
    }

    const matches = allShabads
        .filter(s => !reviewShabads.find(rs => rs.id === s.id))
        .filter(s =>
            s.title.toLowerCase().includes(q) ||
            (s.keertani || "").toLowerCase().includes(q)
        )
        .slice(0, 8);

    if (matches.length === 0) {
        dropdown.classList.add("hidden");
        return;
    }

    dropdown.innerHTML = matches.map(s => `
        <div class="autocomplete-item" onclick="addToReview(${s.id})">
            <div class="font-medium text-gray-200">${escapeHtml(s.title)}</div>
            <div class="text-xs text-gray-500">${escapeHtml(s.keertani)}${s.sggs_raag ? ` &middot; ${escapeHtml(s.sggs_raag)}` : ""}</div>
        </div>
    `).join("");
    dropdown.classList.remove("hidden");
}, 200));

document.addEventListener("click", (e) => {
    if (!e.target.closest("#addShabadSearch") && !e.target.closest("#addDropdown")) {
        dropdown.classList.add("hidden");
    }
});

function addToReview(id) {
    const s = allShabads.find(sh => sh.id === id);
    if (!s || reviewShabads.find(rs => rs.id === id)) return;
    reviewShabads.push(s);
    searchInput.value = "";
    dropdown.classList.add("hidden");
    renderReviewList();
}

function removeFromReview(id) {
    reviewShabads = reviewShabads.filter(s => s.id !== id);
    renderReviewList();
}

function renderReviewList() {
    const container = document.getElementById("reviewList");
    const empty = document.getElementById("reviewEmpty");
    const btn = document.getElementById("reviewBtn");

    if (reviewShabads.length === 0) {
        empty.classList.remove("hidden");
        container.innerHTML = "";
        btn.disabled = true;
        return;
    }

    empty.classList.add("hidden");
    btn.disabled = reviewShabads.length < 2;

    container.innerHTML = reviewShabads.map((s, i) => `
        <div class="parkaran-item">
            <span class="text-gray-600 text-sm font-mono w-6">${i + 1}.</span>
            <div class="flex-1 min-w-0">
                <span class="text-gray-200">${escapeHtml(s.title)}</span>
                <span class="text-gray-600 text-sm ml-2">${escapeHtml(s.keertani || "")}</span>
            </div>
            <button onclick="removeFromReview(${s.id})" class="text-gray-600 hover:text-red-400">&times;</button>
        </div>
    `).join("");
}

async function reviewParkaran() {
    if (reviewShabads.length < 2) return;

    const btn = document.getElementById("reviewBtn");
    const resultsDiv = document.getElementById("reviewResults");

    btn.disabled = true;
    btn.textContent = "Reading between the lines...";
    resultsDiv.innerHTML = '<div class="loading-pulse text-gray-500 text-center py-12">Analyzing thematic flow and connections...</div>';

    try {
        const result = await API.post("/api/parkaran/review", {
            shabad_ids: reviewShabads.map(s => s.id),
        });

        resultsDiv.innerHTML = renderReview(result);
    } catch (err) {
        resultsDiv.innerHTML = `<p class="text-red-400 text-center py-8">Error: ${escapeHtml(err.message)}</p>`;
    }

    btn.disabled = false;
    btn.textContent = "Review Parkaran";
}

function renderReview(review) {
    const scoreClass = review.flow_score >= 7 ? "score-high" : review.flow_score >= 4 ? "score-mid" : "score-low";

    let html = `
        <!-- Overall -->
        <div class="card mb-4">
            <div class="flex items-center gap-4 mb-3">
                <div class="score-gauge ${scoreClass}">${review.flow_score}</div>
                <div>
                    <div class="text-sm font-semibold text-gray-300">Flow Score</div>
                    <div class="text-xs text-gray-500">out of 10</div>
                </div>
            </div>
            <div class="text-sm text-gold-400/80 mb-2">${escapeHtml(review.overall_theme)}</div>
            <div class="text-sm text-gray-400">${escapeHtml(review.overall_assessment)}</div>
        </div>
    `;

    // Transitions
    if (review.transitions && review.transitions.length) {
        html += '<h3 class="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-2">Transitions</h3>';
        html += '<div class="space-y-2 mb-4">';
        review.transitions.forEach(t => {
            const cls = `transition-${t.rating}`;
            const ratingColor = t.rating === "strong" ? "text-green-400" : t.rating === "moderate" ? "text-yellow-400" : "text-red-400";
            html += `
                <div class="card ${cls} pl-4">
                    <div class="flex items-center gap-2 mb-1">
                        <span class="text-sm text-gray-300">${escapeHtml(t.from_title)}</span>
                        <span class="text-gray-600">&rarr;</span>
                        <span class="text-sm text-gray-300">${escapeHtml(t.to_title)}</span>
                        <span class="text-xs ${ratingColor} ml-auto">${t.rating}</span>
                    </div>
                    <div class="text-xs text-gray-500">${escapeHtml(t.explanation)}</div>
                </div>
            `;
        });
        html += '</div>';
    }

    // Strongest moment
    if (review.strongest_moment && review.strongest_moment.explanation) {
        html += `
            <div class="card mb-3 border-green-800/30">
                <div class="text-xs text-green-500 uppercase tracking-wider mb-1">Strongest Moment</div>
                <div class="text-sm text-gray-300">${escapeHtml(review.strongest_moment.explanation)}</div>
            </div>
        `;
    }

    // Weakest moment
    if (review.weakest_moment && review.weakest_moment.explanation) {
        html += `
            <div class="card mb-3 border-red-800/30">
                <div class="text-xs text-red-500 uppercase tracking-wider mb-1">Weakest Moment</div>
                <div class="text-sm text-gray-300">${escapeHtml(review.weakest_moment.explanation)}</div>
                ${review.weakest_moment.suggestion ? `<div class="text-xs text-gold-500 mt-1">Suggestion: ${escapeHtml(review.weakest_moment.suggestion)}</div>` : ""}
            </div>
        `;
    }

    return html;
}

init();
