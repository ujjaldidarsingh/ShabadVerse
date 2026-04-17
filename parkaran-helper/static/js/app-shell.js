/**
 * App Shell — tab switching, URL query param handling, library button wiring.
 *
 * This script runs after graph-explorer.js and parkaran-reviewer.js have
 * defined their globals. It wires up the EXPLORE/REVIEW tab buttons and
 * honors the ?tab= query parameter from legacy /explore and /reviewer
 * redirects.
 */

/* ===== THEME (light/dark, OS-aware with user override) ===== */

function initTheme() {
    const saved = localStorage.getItem("shabadverse_theme");
    // Always set data-theme explicitly so themeColor() in graph-explorer.js
    // has a definitive value when Cytoscape initializes. Without this,
    // data-theme is null on first load and themeColor's isLightTheme() check
    // can race with Cytoscape style initialization.
    const theme = saved || "dark";
    document.documentElement.setAttribute("data-theme", theme);
    updateThemeToggleUI(theme);
}

function updateThemeToggleUI(theme) {
    const icon = document.getElementById("themeIcon");
    const label = document.getElementById("themeLabel");
    if (icon) icon.textContent = theme === "light" ? "☀" : "☾";
    if (label) label.textContent = theme === "light" ? "DARK" : "LIGHT";
}

window.toggleTheme = function () {
    const current = document.documentElement.getAttribute("data-theme");
    const next = current === "light" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("shabadverse_theme", next);
    updateThemeToggleUI(next);

    // Re-render Cytoscape — node/edge/label colors are hardcoded at init time.
    // Update the styles that depend on theme, then re-render.
    if (typeof State !== "undefined" && State.cy) {
        const isLight = next === "light";
        const outlineColor = isLight ? "#f8f5f0" : "#0f0d13";
        const labelColor = isLight ? "rgba(28,22,16,0.5)" : "rgba(232,220,200,0.5)";
        const tagLabelColor = isLight ? "rgba(163,92,0,0.55)" : "rgba(245,158,11,0.45)";

        State.cy.style()
            .selector("node[type='shabad']").style({
                "color": labelColor,
                "text-outline-color": outlineColor,
            })
            .selector("node.center-node").style({
                "color": isLight ? "#1c1610" : "#f5e6c8",
                "text-outline-color": outlineColor,
            })
            .selector("node[type='tagLabel']").style({
                "color": tagLabelColor,
                "text-outline-color": outlineColor,
            })
            .update();

        State.cy.resize();
    }
};

initTheme();

(function () {
    // Sidebar collapse/expand
    window.toggleSidebar = function () {
        const panel = document.getElementById("sidebarPanel");
        const openBtn = document.getElementById("sidebarOpen");
        const collapsed = panel.classList.toggle("collapsed");
        openBtn.classList.toggle("hidden", !collapsed);

        // Shift search bar + controls + breadcrumbs when sidebar collapses
        const offset = collapsed ? "16px" : "260px";
        const searchBar = document.querySelector(".explore-search-bar");
        const controls = document.querySelector(".graph-controls");
        const breadcrumbs = document.getElementById("breadcrumbs");
        if (searchBar) searchBar.style.left = offset;
        if (controls) controls.style.left = offset;
        if (breadcrumbs) breadcrumbs.style.left = offset;

        // Re-fit graph after sidebar toggle
        if (typeof State !== "undefined" && State.cy) {
            requestAnimationFrame(() => {
                State.cy.resize();
                if (State.centerNode) {
                    const visible = State.cy.nodes().not(".faded").not("[type='tagLabel']");
                    if (visible.length > 0) State.cy.fit(visible, 50);
                }
            });
        }
    };

    // Mobile: tap sidebar logo to toggle drawer
    const sidebarLogo = document.querySelector(".sidebar-logo");
    if (sidebarLogo) {
        sidebarLogo.addEventListener("click", (e) => {
            if (window.innerWidth <= 768) {
                e.stopPropagation();
                document.getElementById("sidebarPanel")?.classList.toggle("mobile-open");
            }
        });
    }

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

        // Check for shared library in URL: ?items=id1,id2,id3&name=LibraryName
        const sharedItems = params.get("items");
        const sharedName = params.get("name");
        if (sharedItems && typeof State !== "undefined") {
            const ids = sharedItems.split(",").map((s) => s.trim()).filter(Boolean);
            if (ids.length > 0) {
                // Load shared items into a new temp library (don't overwrite user's own)
                const lib = typeof getLibrary === "function" ? getLibrary() : { parkarans: {}, currentId: null };
                const sharedId = "shared_" + Date.now().toString(36);
                const items = ids.map((id) => {
                    const m = State.metadata[id] || {};
                    return {
                        id,
                        title: m.title || "",
                        gurmukhi: m.gurmukhi || "",
                        raag: m.raag || "",
                        ang: m.ang || 0,
                        tags: m.tags || [],
                    };
                });
                lib.parkarans[sharedId] = {
                    name: sharedName || `Shared (${ids.length} shabads)`,
                    items,
                    created: new Date().toISOString(),
                    updated: new Date().toISOString(),
                };
                lib.currentId = sharedId;
                if (typeof setLibrary === "function") setLibrary(lib);
                State.parkaran = [...items];
                if (typeof renderParkaran === "function") renderParkaran();
                if (typeof updateLibraryNameDisplay === "function") updateLibraryNameDisplay();

                // Re-center graph on first item
                queueMicrotask(() => {
                    if (ids[0] && typeof expandShabad === "function") expandShabad(ids[0]);
                });

                // Clean URL without reloading
                const cleanUrl = window.location.pathname;
                window.history.replaceState({}, "", cleanUrl);
            }
        }

        if (tab === "review" || tab === "explore") {
            queueMicrotask(() => {
                if (typeof switchToTab === "function") switchToTab(tab);
            });
        }
    }

    // Share current library as a URL
    window.shareLibraryURL = function () {
        if (typeof State === "undefined" || !State.parkaran.length) return;
        const ids = State.parkaran.map((p) => p.id).join(",");
        const lib = typeof getLibrary === "function" ? getLibrary() : {};
        const current = lib.currentId ? lib.parkarans?.[lib.currentId] : null;
        const name = encodeURIComponent(current?.name || "Shared Library");
        const url = `${window.location.origin}/?items=${ids}&name=${name}`;

        if (navigator.clipboard) {
            navigator.clipboard.writeText(url).then(() => {
                if (typeof showToast === "function") showToast("Link copied to clipboard");
            });
        } else {
            window.prompt("Copy this link to share:", url);
        }
    };

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
