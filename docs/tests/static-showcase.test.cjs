const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.TF_PLAYWRIGHT || 'playwright');
const index = JSON.parse(fs.readFileSync(path.join(__dirname, '../data/index.json')));
const base = process.env.TF_TEST_URL || 'http://127.0.0.1:8772/';
(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const context = await browser.newContext();
    if (base.includes('127.0.0.1')) await context.route(base + '**', async route => {
      const response = await route.fetch();
      await route.fulfill({ response, headers: { ...response.headers(), 'content-security-policy': 'sandbox allow-popups allow-forms allow-modals' } });
    });
    const page = await context.newPage();
    let checked = 0;
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.goto(base + 'gallery.html?v=tf-balanced-80', { waitUntil: 'domcontentloaded' });
      assert.equal(await page.evaluate(() => typeof window.TF), 'undefined', 'Test must enforce the platform script restriction');
      assert.equal(await page.locator('.static-directory a').count(), index.n_cases);
      assert.equal(await page.locator('.static-system').count(), index.n_systems);
      assert(await page.locator('.static-showcase').isVisible());
      assert(await page.locator('.panels').isHidden());
      await page.screenshot({ path: `/private/tmp/tf-static-directory-${width}.png`, animations: 'disabled' });
      const examples = ['openclaw', 'opencode', 'pi'].map(h => index.cases.find(c => c.system.endsWith('__' + h)));
      for (const c of examples) {
        await page.goto(base + `showcase/${c.system}/${c.task_id}.html`, { waitUntil: 'domcontentloaded' });
        assert.equal(await page.locator('.scene-sub').count(), 4);
        assert.equal(await page.locator('.scene-svg:visible .wire-path').count(), 4);
        await page.waitForFunction(() => [...document.querySelectorAll('.scene img')].every(n => n.complete));
        assert(await page.locator('.scene img').evaluateAll(nodes => nodes.every(n => n.naturalWidth > 0)));
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        await page.screenshot({ path: `/private/tmp/tf-static-${c.system.split('__')[1]}-${width}.png`, animations: 'disabled' });
        const call = page.locator('.static-highlights .static-event.call').first();
        await call.locator(':scope > summary').click();
        assert(await call.locator('.event-body').isVisible());
        const result = page.locator('.static-highlights .static-event.result').first();
        await result.locator(':scope > summary').click();
        assert(await result.locator('.event-body').isVisible());
        await page.locator('.static-full > summary').first().click();
        assert(await page.locator('.static-full .static-event').first().isVisible());
        const essential = page.locator('.static-essential:not(.judge)').first();
        const href = await essential.getAttribute('href');
        await essential.click();
        assert(page.url().includes(c.task_id + '.html#'));
        assert(await page.locator('#' + href.split('#')[1]).isVisible());
        assert.equal(await page.locator('.static-metric').count(), 8);
        checked++;
      }
    }
    console.log(JSON.stringify({ staticCases: checked, directoryCases: index.n_cases, scriptSandbox: true }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
