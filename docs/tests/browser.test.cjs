const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.TF_PLAYWRIGHT || 'playwright');
const index = JSON.parse(fs.readFileSync(path.join(__dirname, '../data/index.json')));
const base = process.env.TF_TEST_URL || 'http://127.0.0.1:8769/';
require('../js/experience.js');
const examplesWithRounds = [];
for (const c of index.cases) {
  const model = globalThis.TF_EXPERIENCE.normalize(JSON.parse(fs.readFileSync(path.join(__dirname, '../cases', c.system, 'tasks', c.task_id + '.json'))));
  for (const actor of ['A', 'orchestrator']) {
    const group = model.navigation.find(g => g.actor === actor);
    if (group.rounds.length > 1 && !examplesWithRounds.some(e => e.actor === actor) && (actor === 'orchestrator' || c.b === 'b4')) examplesWithRounds.push({ c, actor, group });
  }
  if (examplesWithRounds.length === 2) break;
}
assert.equal(examplesWithRounds.length, 2);
(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const errors = []; let checked = 0;
  try {
    for (const width of [1440, 1024, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 1000 } });
      page.on('pageerror', error => errors.push(error.message));
      const examples = [index.cases.find(c => c.system === 'glm-4.7__openclaw' && c.m === 'M6'), index.cases.find(c => c.suite === 'chain' && c.system.endsWith('__opencode')), index.cases.find(c => c.b === 'b4' && c.system.endsWith('__pi'))];
      for (const c of examples) {
        await page.goto(base + 'gallery.html?v=tf-evidence-3#case=' + encodeURIComponent(c.id), { waitUntil: 'domcontentloaded' });
        await page.waitForSelector('.scene-sub');
        assert(!/audited|excluded|exclusion/i.test(await page.locator('#auditStats').innerText()), 'Directory shows available cases only');
        assert.equal(await page.locator('.scene-sub').count(), 4, 'Four-node delegation flow preserved');
        assert.deepEqual(await page.locator('[data-actor-tab]').evaluateAll(nodes => nodes.map(n => n.dataset.actorTab)), ['orchestrator', 'A', 'B', 'C', 'D']);
        await page.waitForSelector('.wire-path');
        assert.equal(await page.locator('.wire-path').count(), 4);
        assert(await page.locator('.wire-path').evaluateAll(nodes => nodes.every(n => n.getTotalLength() > 0 && !n.getAttribute('d').includes('NaN'))));
        await page.waitForFunction(() => [...document.querySelectorAll('.scene img')].every(n => n.complete));
        assert(await page.locator('.scene img').evaluateAll(nodes => nodes.every(n => n.complete && n.naturalWidth > 0)), 'Flow logos loaded');
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'No page overflow');
        await page.screenshot({ path: `/private/tmp/tf-${c.system.split('__')[1]}-${width}-flow.png` });
        await page.locator('.scene-sub.called').first().click();
        assert(!(await page.locator('#notes dt').allTextContents()).some(label => ['Source', 'Time'].includes(label)), 'Raw source IDs and timestamps stay hidden');
        assert.match(await page.locator('#eventFocus').innerText(), /Subagent [A-D]/i);
        assert.equal(await page.locator('.scene-sub.live').count(), 1);
        await page.locator('.scene-orch').click();
        assert.match(await page.locator('#eventFocus').innerText(), /Orchestrator/i);
        await page.locator('[data-flow-play]').click();
        await page.waitForTimeout(1750);
        assert(Number(await page.locator('#scrubber').inputValue()) > 0, 'Flow playback advances real events');
        await page.locator('[data-flow-play]').click();
        const stopped = await page.locator('#scrubber').inputValue();
        await page.waitForTimeout(1700);
        assert.equal(await page.locator('#scrubber').inputValue(), stopped, 'Playback pause works');
        await page.locator('.event-row.call').first().click();
        await page.locator('#eventFocus').scrollIntoViewIfNeeded();
        assert.equal(await page.locator('#eventFocus.call .argument-list').count(), 1);
        assert.equal(await page.locator('i[data-lucide]').count(), 0, 'All tool symbols render');
        await page.screenshot({ path: `/private/tmp/tf-${c.system.split('__')[1]}-${width}-call.png` });
        if (width < 861) await page.locator('[data-panel="right"]').click();
        await page.locator('.paired-event').first().click();
        assert.equal(await page.locator('#eventFocus.result').count(), 1);
        await page.locator('#eventFocus').scrollIntoViewIfNeeded();
        await page.screenshot({ path: `/private/tmp/tf-${c.system.split('__')[1]}-${width}-return.png` });
        await page.locator('[data-view="full"]').click();
        const fullCount = await page.locator('.event-row').count();
        await page.locator('[data-view="excerpts"]').click();
        assert((await page.locator('.event-row').count()) <= fullCount);
        assert(!/\(no assistant text\)|NO_REPLY/.test((await page.locator('#essentials,#subagentHighlights').allTextContents()).join('\n')));
        await page.locator('[data-span-filter="judge"]').click();
        assert.equal(await page.locator('#eventFocus .judgment').count(), 8);
        assert.equal(await page.locator('#eventFocus meter').first().evaluate(n => getComputedStyle(n).accentColor), 'rgb(182, 60, 70)');
        checked++;
      }
      for (const { c, actor, group } of examplesWithRounds) {
        await page.goto(base + 'gallery.html?v=tf-evidence-3#case=' + encodeURIComponent(c.id), { waitUntil: 'domcontentloaded' });
        await page.locator(`[data-actor-tab="${actor}"]`).click();
        assert.equal(await page.locator('[data-actor-tab]').count(), 5);
        assert.equal(await page.locator('#sessionSelect option').count(), group.rounds.length);
        await page.selectOption('#sessionSelect', String(group.rounds[1].start));
        assert.equal(await page.locator('[data-actor-tab].on').getAttribute('data-actor-tab'), actor);
        assert((await page.locator('#eventFocus .eyebrow').textContent()).includes(group.rounds[1].label));
        assert.equal(await page.locator('#sessionSelect').inputValue(), String(group.rounds[1].start));
        if (actor === 'A') {
          assert((await page.locator('#subagentHighlights').innerText()).includes('Subagent A · Round 2 returned'));
          assert.equal(await page.locator('.scene-sub.live').count(), 1);
        }
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        await page.screenshot({ path: `/private/tmp/tf-rounds-${actor}-${width}.png` });
        await page.locator('[data-span-filter="judge"]').click();
        assert(await page.locator('#sessionNav').isHidden());
        await page.locator(`[data-actor-tab="${actor}"]`).click();
        assert.equal(await page.locator('#sessionSelect').inputValue(), String(group.rounds[0].start));
        checked++;
      }
      await page.close();
    }
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
    page.on('pageerror', e => errors.push(e.message));
    for (const system of index.systems) {
      const c = index.cases.find(c => c.system === system.id);
      await page.goto(base + 'gallery.html?v=tf-evidence-3#case=' + encodeURIComponent(c.id), { waitUntil: 'domcontentloaded' });
      await page.waitForSelector('.scene-sub');
      assert.equal(await page.locator('.scene-sub').count(), 4);
      assert.equal(await page.locator('.orb-mask').first().evaluate(n => getComputedStyle(n).animationName), 'none');
      checked++;
    }
    await page.close();
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ browserCases: checked, errors }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
