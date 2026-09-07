/* Touch-first discovery. Cards and graph use the same ranked connections. */
let discoveryView = null;

function initDiscoveryView() {
    setDiscoveryView(localStorage.getItem('shabadverse_view_choice_v2') || 'graph', false);
    renderNeighborCards(null, null);
}

function setDiscoveryView(view, remember = true) {
    discoveryView = view === 'graph' ? 'graph' : 'list';
    document.getElementById('exploreTab').dataset.view = discoveryView;
    document.getElementById('neighborCards').classList.toggle('hidden', discoveryView !== 'list');
    document.getElementById('listViewButton').setAttribute('aria-pressed', String(discoveryView === 'list'));
    document.getElementById('graphViewButton').setAttribute('aria-pressed', String(discoveryView === 'graph'));
    if (remember) localStorage.setItem('shabadverse_view_choice_v2', discoveryView);
    if (typeof State !== 'undefined' && State.cy) requestAnimationFrame(() => State.cy.resize());
}

function toggleMobileLibrary() {
    const panel = document.getElementById('sidebarPanel');
    panel.classList.remove('collapsed');
    panel.classList.toggle('mobile-open');
}

function renderNeighborCards(sid, data) {
    const panel = document.getElementById('neighborCards');
    if (!panel) return;
    if (!sid || !data) {
        panel.innerHTML = '<div class="discovery-welcome"><h1>Find a shabad. Follow a connection.</h1><p>Search Gurbani, choose a concept from Tags, or begin with a random shabad. Preview the full text, then add it to your parkaran.</p><button type="button" class="btn-secondary" onclick="surpriseMe()">Begin with a shabad</button></div>';
        return;
    }
    const seed = State.metadata[sid] || {};
    function actions(id, expand) {
        const added = State.parkaran.some(p => String(p.id) === String(id));
        return `<div class="connection-actions"><button type="button" data-discovery="preview" data-id="${escAttr(id)}">Read &amp; evidence</button><button type="button" data-discovery="add" data-id="${escAttr(id)}" ${added ? 'disabled' : ''}>${added ? 'In my set' : '+ Add to set'}</button>${expand ? `<button type="button" data-discovery="expand" data-id="${escAttr(id)}">Explore</button>` : ''}</div>`;
    }
    panel.innerHTML = `<article class="connection-card seed-card"><span class="connection-label">Exploring</span><h1 lang="pa-Guru">${escapeHtml(seed.gurmukhi || seed.title)}</h1><p>${escapeHtml(seed.raag || '')} · Ang ${escapeHtml(String(seed.ang || ''))}</p>${sourceBadge(seed)}${actions(sid, false)}</article>
        ${data.fallback_reason ? `<p class="connection-notice" role="status">${escapeHtml(data.fallback_reason)}</p>` : ''}
        ${data.anchor_line ? `<aside class="connection-notice">Connecting from this line:<p lang="pa-Guru">${escapeHtml(data.anchor_line.gurmukhi)}</p><p>${escapeHtml(data.anchor_line.english)}</p></aside>` : ''}
        <p class="connection-notice">Connections are suggestions. Read each shabad in full before choosing a sequence.</p>
        ${Object.entries(data.by_tag || {}).map(([tag, items]) => `<section class="connection-group"><h2>${escapeHtml(tag)} <small>${tag === 'Translation similarity' ? 'inferred connection' : (seed.tags || []).includes(tag) ? 'shared concept' : 'neighbor concept'}</small></h2>${items.map(item => `<article class="connection-card"><h3 lang="pa-Guru">${escapeHtml(item.gurmukhi || item.title)}</h3><p>${escapeHtml(item.raag || '')} · Ang ${escapeHtml(String(item.ang || ''))}</p>${item.matched_line_gurmukhi ? `<blockquote lang="pa-Guru">${escapeHtml(item.matched_line_gurmukhi)}</blockquote><p>Matched line · translation similarity</p>` : ''}${sourceBadge(item)}${actions(item.id, true)}</article>`).join('')}</section>`).join('')}
        ${data.total_shown ? '' : '<p class="connection-notice">No connections at this setting. Lower the selectivity or choose another shabad.</p>'}`;
    panel.querySelectorAll('[data-discovery]').forEach(button => button.addEventListener('click', () => {
        const id = button.dataset.id;
        if (button.dataset.discovery === 'preview') loadPreview(id);
        if (button.dataset.discovery === 'expand') { expandShabad(id); panel.scrollTop = 0; }
        if (button.dataset.discovery === 'add') { addToParkaran(id); renderNeighborCards(sid, data); }
    }));
}

function conceptEvidenceHTML(concepts) {
    if (!concepts?.length) return '<p class="connection-notice">No concept assignment. Connections may use translation similarity.</p>';
    return `<details class="concept-evidence"><summary>Why these concepts? (${concepts.length})</summary><p>Lexical means an anchor word was found. Inferred means translation similarity. These are navigation aids, not authoritative interpretations.</p>${concepts.map(item => `<article><strong>${escapeHtml(item.concept)}</strong> <span>${item.lexical ? 'Lexical anchor' : 'Inferred'}${item.confidence === 'description-only' ? ' · lower confidence' : ''}</span><p lang="pa-Guru">${escapeHtml(item.line_gurmukhi)}</p><small>Verse ${Number(item.line_index) + 1}</small></article>`).join('')}</details>`;
}

function trimNeighborCache() {
    const keys = Object.keys(State.neighborCache);
    for (const key of keys.slice(0, Math.max(0, keys.length - 80))) delete State.neighborCache[key];
}

function evictOldGraphNodes() {
    const removable = State.cy.nodes("[type='shabad'].faded").filter(n => !n.hasClass('in-parkaran') && n.id() !== String(State.centerNode));
    const excess = Math.max(0, State.cy.nodes("[type='shabad']").length - 120 - State.parkaran.length);
    removable.slice(0, excess).remove();
}

function moveInParkaran(index, direction) {
    const target = index + direction;
    if (target < 0 || target >= State.parkaran.length) return;
    const [item] = State.parkaran.splice(index, 1);
    State.parkaran.splice(target, 0, item);
    saveParkaran(); renderParkaran();
    if (activeTab === 'review') initReviewTab();
}


function sourceBadge(record) {
    if (!record?.is_amrit_keertan) return '';
    const chapters = (record.ak_chapters || []).join(', ');
    return `<span class="source-badge" title="Indexed Amrit Keertan membership${chapters ? ' · chapters '+escapeHtml(chapters) : ''}">Amrit Keertan${chapters ? `<small> · ch. ${escapeHtml(chapters)}</small>` : ''}</span>`;
}
function renderConnectionStatus(data) {
    const counts = data.source_counts || {};
    const source = {'all':'All SGGS', 'prefer-ak':'Amrit Keertan preferred', 'ak-only':'Amrit Keertan only'}[data.source_mode] || 'All SGGS';
    const anchor = data.anchor_line?.gurmukhi;
    document.getElementById('connectionStatus').textContent = data.source_notice ||
        `${source} · ${counts.shown ?? data.total_shown} connections · ${counts.ak || 0} in Amrit Keertan${data.fallback_reason ? ' · '+data.fallback_reason : anchor ? ' · Line: '+anchor : ''}`;
}
