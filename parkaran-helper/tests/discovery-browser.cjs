const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const base=process.env.BASE_URL || 'http://127.0.0.1:5053';
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});
 try {for(const [label,width,height] of [['phone',390,844],['tablet',820,1180],['desktop',1440,1000]]){
  const context=await browser.newContext({viewport:{width,height},hasTouch:label!=='desktop',isMobile:label==='phone'});
  await context.addInitScript(()=>{localStorage.setItem('shabadverse_view','list');localStorage.setItem('shabadverse_source_mode','ak-only');localStorage.setItem('shabadverse_ak_mode','1')});
  const page=await context.newPage();const errors=[],external=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',route=>{if(route.request().url().startsWith(base))return route.continue();external.push(route.request().url());return route.abort()});
  await page.goto(base);await page.evaluate(()=>window.shabadverseReady);await page.locator('#loadingOverlay').waitFor({state:'hidden'});
  assert.equal(await page.evaluate(()=>discoveryView),'graph','graph default migrates old automatic Cards setting');
  await page.locator('.workspace-header a[href="/about"]').click();
  await page.locator('[data-step="explore"]').click();await page.locator('#demo-explore').waitFor({state:'visible'});
  await page.locator('[data-step="build"]').click();await page.locator('#demo-build').waitFor({state:'visible'});
  await page.locator('[data-step="search"]').click();
  await page.screenshot({path:`/private/tmp/shabadverse-about-${label}.png`,fullPage:true});
  await page.goto(base);await page.evaluate(()=>window.shabadverseReady);await page.locator('#loadingOverlay').waitFor({state:'hidden'});
  for(const mode of ['first-letter-start','first-letter-anywhere']){
   const results=[];
   for(const q of ['h k s j k','ਹਕਸਜਕ']){
    await page.locator(`[data-mode="${mode}"]`).click();
    const pending=page.waitForResponse(r=>r.url().includes('/api/graph/search?'));
    await page.locator('#graphSearch').fill(q);const response=await pending;const data=await response.json();
    results.push(data.map(r=>[r.banidb_shabad_id,r.line_index]));
    await page.locator('[data-action="select-search"]').first().waitFor();
   }
   assert.deepEqual(results[0],results[1],'Roman and Gurmukhi search equivalence');assert.ok(results[0].length>0);
  }
  await page.locator('[data-action="select-search"]').first().click();await page.waitForFunction(()=>!State.expanding && State.centerNode);
  assert.equal(await page.locator('#sourceModeSelect, #topicSource, .source-badge').count(),0);
  assert.equal(await page.locator('body').textContent().then(t=>t.includes('Amrit Keertan')),false);
  const sid=await page.evaluate(()=>State.centerNode);
  await page.locator('button').filter({hasText:/^Topics$/}).click();
  await page.locator('.topic-chip[data-tag="Naam"]').click();await page.locator('#topicRandom').waitFor();
  assert.match(await page.locator('.topic-counts').textContent(),/lexical/);
  await page.locator('.topic-method summary').click();assert.match(await page.locator('.topic-method').textContent(),/without a percentage ceiling/);
  await page.locator('#topicNext').click();await page.waitForFunction(()=>Topic.offset===20 && document.querySelector('.topic-tools')?.textContent.includes('21'));
  await page.locator('#topicReview').click();await page.locator('#topicReviewSamples [data-read]').first().waitFor();
  assert.equal(await page.locator('#topicReviewSamples').textContent().then(t=>t.includes('Previously retained inference')),false);
  await page.locator('[data-judge]').first().selectOption('supported');
  await page.locator('#revealTopicReview').click();await page.locator('#revealTopicReview:disabled').waitFor();
  assert.equal(await page.locator('[data-judge]').first().inputValue(),'supported');
  await page.locator('#topicReviewSamples [data-read]').first().click();await page.locator('.preview-gurmukhi').first().waitFor();
  await page.locator('#shabadPreview .preview-close').click();
  await page.locator('#topicRandom').click();await page.locator('#topicModal').waitFor({state:'hidden'});await page.waitForFunction(()=>!State.expanding);
  assert.equal(await page.evaluate(()=>State.tagIndex.Naam.includes(State.centerNode)),true);
  const first=await page.evaluate(()=>State.centerNode);await page.locator('#topicAnother').click();await page.waitForFunction(id=>!State.expanding&&State.centerNode!==id,first);
  assert.equal(await page.evaluate(()=>Object.values(State.lastNeighbors.data.by_tag).flat().filter(n=>!State.parkaran.some(p=>p.id===n.id)).every(n=>State.cy.getElementById(`e_${State.centerNode}_${n.id}`).data('score')===n.score)),true,'edge data refresh');
  await page.screenshot({path:`/private/tmp/shabadverse-graph-${label}.png`});
  await page.locator('.appearance-button').click();await page.waitForTimeout(350);await page.screenshot({path:`/private/tmp/shabadverse-light-${label}.png`});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.locator('#listViewButton').click();await page.reload();await page.evaluate(()=>window.shabadverseReady);assert.equal(await page.evaluate(()=>discoveryView),'list','deliberate choice persists');
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);console.log(label,'new discovery PASS');await context.close();
 }}finally{await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
