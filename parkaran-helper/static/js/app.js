/**
 * Shared utilities for Parkaran Helper.
 */

const API = {
    async get(url) {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`API error: ${resp.status}`);
        return resp.json();
    },
    async post(url, data) {
        const resp = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        });
        if (!resp.ok) throw new Error(`API error: ${resp.status}`);
        return resp.json();
    },
};

function confidenceBadge(level) {
    const cls = level === "High" ? "badge-high" : level === "Medium" ? "badge-medium" : "badge-low";
    return `<span class="badge ${cls}">${level}</span>`;
}

function scoreGauge(score) {
    const cls = score >= 7 ? "score-high" : score >= 4 ? "score-mid" : "score-low";
    return `<div class="score-gauge ${cls}">${score}</div>`;
}

function positionTag(position) {
    const cls = `position-${position}`;
    return `<span class="position-tag ${cls}">${position}</span>`;
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text || "";
    return div.innerHTML;
}

function debounce(fn, delay = 300) {
    let timer;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), delay);
    };
}
