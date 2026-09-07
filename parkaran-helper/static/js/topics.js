/* One topic panel for browsing, source-scoped random starts and expert review. */
const Topic = {all: null, tag: null, source: 'all', offset: 0, generation: 0, recent: {}};

async function openTagBrowser(tag = null) {
    hideTooltip();
    const modal = document.getElementById('topicModal');
    modal.classList.remove('hidden');
    try {
        if (!Topic.all) Topic.all = await API.get('/api/topics');
        renderTopicIndex();
        if (tag) await selectTag(tag);
    } catch (error) {
        document.getElementById('topicIndex').textContent = 'Topics unavailable. Close and try again.';
    }
}
function closeTagBrowser() {
    Topic.generation++;
    document.getElementById('topicModal').classList.add('hidden');
}
function openTagShabadsModal(tag) { return openTagBrowser(tag); }
function closeTagShabadsModal() { closeTagBrowser(); }

function renderTopicIndex() {
    const query = document.getElementById('topicSearch').value.trim().toLocaleLowerCase();
    const topics = (Topic.all || []).filter(t => [t.tag,t.gurbani_term,t.description].join(' ').toLocaleLowerCase().includes(query));
    const index = document.getElementById('topicIndex');
    index.innerHTML = topics.map(t => `<button type="button" class="topic-chip" data-tag="${escAttr(t.tag)}" aria-pressed="${Topic.tag === t.tag}">${escapeHtml(t.tag)} <small>${t.count.toLocaleString()}</small></button>`).join('') || '<p>No matching topics.</p>';
    index.querySelectorAll('[data-tag]').forEach(button => button.onclick = () => selectTag(button.dataset.tag));
}
async function selectTag(tag, offset = 0) {
    Topic.tag = tag; Topic.offset = offset;
    const generation = ++Topic.generation;
    const source = document.getElementById('topicSource').value;
    Topic.source = source;
    renderTopicIndex();
    const detail = document.getElementById('topicDetail');
    detail.innerHTML = '<p role="status">Loading topic…</p>';
    try {
        const data = await API.get(`/api/topics/${encodeURIComponent(tag)}?offset=${offset}&source=${source}`);
        if (generation !== Topic.generation) return;
        const t = data.topic;
        detail.innerHTML = `<header class="topic-heading"><div><span class="eyebrow">Explore a topic</span><h2>${escapeHtml(tag)}</h2></div><button type="button" id="topicRandom" ${data.total ? '' : 'disabled'}>Random starting shabad</button></header>
            <p>${escapeHtml(t.description)}</p><p class="topic-counts"><strong>${t.count.toLocaleString()}</strong> shabads · ${t.lexical.toLocaleString()} lexical · ${t.inferred.toLocaleString()} inferred · ${t.ak_count.toLocaleString()} in Amrit Keertan</p>
            ${t.confidence === 'description-only' ? '<p class="connection-notice">This topic currently uses description-only matching. All its assignments are inferred.</p>' : ''}
            <details class="topic-method"><summary>How this count was produced</summary><p>Every lexical match is retained. Inferred assignments use a separate similarity threshold for this concept, without a percentage ceiling or a multiple of lexical frequency. The current threshold is automatically calibrated and remains provisional. A lexical occurrence also needs interpretation in context.</p><p>Previous dataset: ${Number(t.previous_count || 0).toLocaleString()} assignments. Newly admitted inferences: ${Number(t.new_inferred || 0).toLocaleString()}. Graph display limits do not change topic membership.</p></details>
            <div class="topic-tools"><button type="button" id="topicReview">Review assignment examples</button><span>${data.total ? `${offset+1}–${Math.min(offset+20,data.total)} of ${data.total.toLocaleString()}` : 'No shabads in this source selection'}</span></div>
            <div id="topicReviewSamples"></div><div class="topic-results">${data.shabads.map(s => `<article class="topic-row"><button type="button" class="topic-open" data-open="${s.id}"><span lang="pa-Guru">${escapeHtml(s.gurmukhi || s.title)}</span><small>${escapeHtml([s.raag,s.writer,'Ang '+s.ang].filter(Boolean).join(' · '))}</small></button>${sourceBadge(s)}<button type="button" data-read="${s.id}">Read</button></article>`).join('')}</div>
            <nav class="topic-pagination"><button type="button" id="topicPrevious" ${offset ? '' : 'disabled'}>Previous</button><button type="button" id="topicNext" ${data.next_offset === null ? 'disabled' : ''}>Next</button></nav>`;
        document.getElementById('topicRandom').onclick = () => randomTopic(tag, source);
        document.getElementById('topicPrevious').onclick = () => selectTag(tag, Math.max(0,offset-20));
        document.getElementById('topicNext').onclick = () => selectTag(tag, data.next_offset);
        document.getElementById('topicReview').onclick = () => reviewTopic(tag, generation);
        detail.querySelectorAll('[data-open]').forEach(b => b.onclick = () => startFromTopic(tag,b.dataset.open));
        detail.querySelectorAll('[data-read]').forEach(b => b.onclick = () => loadPreview(b.dataset.read));
    } catch (error) {
        if (generation === Topic.generation) detail.innerHTML = '<p>Could not load this topic. Choose it again to retry.</p>';
    }
}
async function randomTopic(tag, source) {
    const key = tag+'|'+source;
    const recent = Topic.recent[key] || [];
    const button = document.getElementById('topicRandom');
    if (button) button.disabled = true;
    const generation = ++Topic.generation;
    try {
        const data = await API.get(`/api/topics/${encodeURIComponent(tag)}/random?source=${source}&exclude=${recent.join(',')}`);
        if (generation !== Topic.generation) return;
        Topic.recent[key] = [...recent.slice(-29),data.shabad.id];
        State.metadata[data.shabad.id] = {...State.metadata[data.shabad.id],...data.shabad};
        startFromTopic(tag,data.shabad.id,source);
    } catch (error) { showToast('No starting shabad available in this topic and source selection.'); }
    finally { if (button) button.disabled = false; }
}
function startFromTopic(tag, sid, source = Topic.source) {
    closeTagBrowser();
    switchToTab('explore');
    delete State.selectedTuk[sid];
    State.startingTopic = {tag,source};
    document.getElementById('topicOrigin').classList.remove('hidden');
    document.getElementById('topicOriginLabel').textContent = `Started from ${tag}`;
    document.getElementById('topicAnother').onclick = () => randomTopic(tag,source);
    expandShabad(sid);
}
function surpriseMe() {
    const ids = Object.keys(State.metadata);
    const other = ids.filter(id => id !== State.centerNode);
    if (!other.length) return;
    State.startingTopic = null;
    document.getElementById('topicOrigin').classList.add('hidden');
    const sid = other[Math.floor(Math.random()*other.length)];
    delete State.selectedTuk[sid];
    expandShabad(sid);
}
async function reviewTopic(tag, generation, reveal = false) {
    const box = document.getElementById('topicReviewSamples');
    box.innerHTML = '<p>Loading evidence…</p>';
    try {
        const data = await API.get(`/api/topics/${encodeURIComponent(tag)}/review?reveal=${reveal ? 1 : 0}`);
        if (generation !== Topic.generation) return;
        const key = `shabadverse_review:${data.dataset_id}:${tag}`;
        let judgments = {};
        if (reveal) localStorage.setItem(key+':revealed','1');
        const hasRevealed = localStorage.getItem(key+':revealed') === '1';
        try { judgments = JSON.parse(localStorage.getItem(key) || '{}'); } catch (_) {}
        const labels = {lexical:'Lexical example',previously_retained:'Previously retained inference',newly_admitted:'Newly admitted inference'};
        box.innerHTML = `<p>${escapeHtml(data.note)}</p><p>Judgments stay in this browser. Export them to preserve a review record.</p>${data.samples.map((s,i)=>`<article><p>Example ${i+1}${reveal ? ' · '+escapeHtml(labels[s.category] || s.category) : ''}</p><p lang="pa-Guru">${escapeHtml(s.line_gurmukhi)}</p><small>Shabad ${s.id} · verse ${s.line_index+1}</small> <button type="button" data-read="${s.id}">Read full shabad</button><label>Your judgment <select data-judge="${s.id}"><option value="">Unreviewed</option><option value="supported">Supported in context</option><option value="unsupported">Not supported in context</option><option value="uncertain">Uncertain</option></select></label></article>`).join('')}<button type="button" id="revealTopicReview" ${reveal ? 'disabled' : ''}>Reveal previous status</button> <button type="button" id="exportTopicReview">Export judgments</button>`;
        box.querySelectorAll('[data-read]').forEach(b=>b.onclick=()=>loadPreview(b.dataset.read));
        box.querySelectorAll('[data-judge]').forEach(select=>{
            select.value=judgments[select.dataset.judge]?.judgment || '';
            select.onchange=()=>{
                judgments[select.dataset.judge]={judgment:select.value,after_reveal:hasRevealed,recorded_at:new Date().toISOString()};
                try { localStorage.setItem(key,JSON.stringify(judgments)); } catch (_) { showToast('Could not save this judgment. Export before closing.'); }
            };
        });
        document.getElementById('revealTopicReview').onclick=()=>reviewTopic(tag,generation,true);
        document.getElementById('exportTopicReview').onclick=()=>{
            const record={dataset_id:data.dataset_id,baseline_sha256:data.baseline_sha256,topic:tag,judgments,samples:data.samples};
            const url=URL.createObjectURL(new Blob([JSON.stringify(record,null,2)],{type:'application/json'}));
            const a=document.createElement('a');a.href=url;a.download=`shabadverse-review-${tag}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
        };
    } catch(error) { if(generation === Topic.generation) box.textContent='Evidence unavailable. Try again.'; }
}
