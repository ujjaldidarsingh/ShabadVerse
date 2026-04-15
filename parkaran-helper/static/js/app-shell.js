/**
 * App Shell — tab switching, URL query param handling, library button wiring.
 *
 * This script runs after graph-explorer.js and parkaran-reviewer.js have
 * defined their globals. It wires up the EXPLORE/REVIEW tab buttons and
 * honors the ?tab= query parameter from legacy /explore and /reviewer
 * redirects.
 */

(function () {
    function wireTabs() {
        const exploreBtn = document.getElementById("tabExplore");
        const reviewBtn = document.getElementById("tabReview");

        if (exploreBtn) {
            exploreBtn.addEventListener("click", () => {
                if (typeof switchToTab === "function") switchToTab("explore");
            });
        }
        if (reviewBtn) {
            reviewBtn.addEventListener("click", () => {
                if (reviewBtn.disabled) return;
                if (typeof switchToTab === "function") switchToTab("review");
            });
        }

        // Close library modal on Escape
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape" && typeof closeLibraryModal === "function") {
                closeLibraryModal();
            }
        });
    }

    function readTabFromURL() {
        const params = new URLSearchParams(window.location.search);
        const tab = params.get("tab");
        if (tab === "review" || tab === "explore") {
            // Wait until graph-explorer's State.parkaran is populated before
            // switching — the Review tab check for empty library needs to
            // reflect what's actually loaded.
            queueMicrotask(() => {
                if (typeof switchToTab === "function") switchToTab(tab);
            });
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => {
            wireTabs();
            readTabFromURL();
        });
    } else {
        wireTabs();
        readTabFromURL();
    }
})();
