/* Run against a local candidate: BASE_URL=http://127.0.0.1:5052 node tests/browser.cjs */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const base = process.env.BASE_URL || 'http://127.0.0.1:5052';
(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.CHROMIUM_PATH ? {executablePath:process.env.CHROMIUM_PATH} : {})});
  try {
    for (const [label,width,height] of [['phone',390,844],['tablet',820,1180],['desktop',1440,1000]]) {
      const context = await browser.newContext({viewport:{width,height},hasTouch:label!=='desktop',isMobile:label==='phone'});
      const page = await context.newPage(); const errors=[]; const external=[];
      page.on('pageerror',e=>errors.push(e.message));
      await page.route('**/*', route => {
        if (route.request().url().startsWith(base)) return route.continue();
        external.push(route.request().url()); return route.abort();
      });
      await page.goto(base); await page.evaluate(()=>window.shabadverseReady);
      await page.waitForTimeout(800);
      assert.deepEqual(errors,[],'startup errors');
      assert.deepEqual(external,[],'external dependency');
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'horizontal overflow');
      await page.locator('#listViewButton').click();
      await page.locator('#graphSearch').fill('ਸਬ');
      await page.locator('[data-action="select-search"]').first().click();
      await page.locator('.seed-card').waitFor();
      await page.locator('#matchModeSelect').selectOption('line');
      await page.waitForFunction(()=>State.lastNeighbors?.data?.requested_match === 'line');
      assert.equal(await page.evaluate(()=>Boolean(State.lastNeighbors.data.anchor_line || State.lastNeighbors.data.fallback_reason)),true,'line anchor or explicit fallback');
      await page.locator('#matchModeSelect').selectOption('shabad');
      await page.waitForFunction(()=>State.lastNeighbors?.data?.match === 'shabad');
      await page.locator('.seed-card [data-discovery="add"]').click();
      await page.locator('.connection-group [data-discovery="add"]').first().click();
      assert.equal(await page.evaluate(()=>State.parkaran.length),2);
      await page.locator('.seed-card [data-discovery="preview"]').click();
      await page.locator('.preview-gurmukhi').first().waitFor();
      await page.locator('#shabadPreview .preview-close').click();
      if (label==='phone') await page.locator('.mobile-tabs button').filter({hasText:'My set'}).click();
      const before=await page.evaluate(()=>State.parkaran.map(p=>p.id));
      await page.locator('[aria-label="Move shabad later"]').first().click();
      assert.deepEqual(await page.evaluate(()=>State.parkaran.map(p=>p.id)),[before[1],before[0]]);
      if (label==='phone') await page.locator('.mobile-tabs button').filter({hasText:'Review'}).click();
      else await page.locator('#tabReview').click();
      await page.locator('.rv-gurbani-line').first().waitFor();
      const saved=await page.evaluate(()=>State.parkaran.map(p=>p.id));
      await page.reload();await page.evaluate(()=>window.shabadverseReady);
      assert.deepEqual(await page.evaluate(()=>State.parkaran.map(p=>p.id)),saved,'saved order');
      await page.locator('#listViewButton').click();
      await page.evaluate(()=>expandShabad(State.parkaran[0].id));
      await page.locator("#loadingOverlay").waitFor({state:"hidden"});
      await page.screenshot({path:`/private/tmp/shabadverse-${label}.png`});
      if (label === 'desktop') {
        await page.locator('#graphViewButton').click();
        await page.evaluate(async()=>{ for(const id of Object.keys(State.metadata).slice(0,25)) await expandShabad(id); });
        assert.equal(await page.evaluate(()=>State.cy.nodes("[type='shabad']").length<=120+State.parkaran.length),true,'graph history bounded');
        await page.goto(base+'/?tab=review&items='+saved.slice().reverse().join(','));
        await page.evaluate(()=>window.shabadverseReady);
        await page.waitForFunction(()=>activeTab === 'review');
        assert.deepEqual(await page.evaluate(()=>State.parkaran.map(p=>p.id)),saved.slice().reverse(),'shared order');
      }
      assert.deepEqual(errors,[],'interaction errors');
      console.log(label,'PASS',JSON.stringify({cards:await page.locator('.connection-card').count(),external:external.length}));
      await context.close();
    }
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exit(1)});
