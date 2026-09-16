// Run with Node and Playwright available (NODE_PATH may point to bundled packages).
const {chromium} = require('playwright');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage();
    await page.route('http://localhost/**', route => route.fulfill({body:'',contentType:'text/html'}));
    await page.goto('http://localhost/');
    await page.setContent('<tankdata-panel></tankdata-panel>');
    await page.addScriptTag({path: path.resolve('custom_components/ha_tankdata/frontend/tankdata-panel.js')});
    await page.evaluate(() => {
      const panel = document.querySelector('tankdata-panel');
      panel._hass = {states: {}, callWS: async request => {window.booking = request;}};
      panel.tanks = [{id:'test',name:'Testtank',capacity:13000,consumers:[{id:'consumer',name:'Brenner',config:{}}],settings:{geometry:{shape:'rectangle'},reserve_liters:0,measurement_tolerance_liters:10}}];
      panel.render();
      panel.selected = 'test';
      panel.refresh = async () => {};
      // Keep the real persistent header/dialog host while avoiding unrelated charts.
      panel.render = () => {};
    });
    for (const [kind,key] of [['tank'],['consumer'],['consumer','consumer'],['settings'],['remove','consumer'],['book','record_refill'],['book','apply_correction']]) {
      for (const method of ['button','escape']) {
        await page.evaluate(([kind,key]) => document.querySelector('tankdata-panel').openDialog(kind,key), [kind,key]);
        assert.equal(await page.locator('dialog[open]').count(), 1);
        if (method === 'button') await page.getByRole('button',{name:'Abbrechen',exact:true}).click();
        else await page.keyboard.press('Escape');
        assert.equal(await page.locator('dialog').count(), 0, `${kind}: ${method}`);
        assert.equal(await page.evaluate(() => document.querySelector('tankdata-panel').modal), null);
      }
    }
    await page.evaluate(() => document.querySelector('tankdata-panel').openDialog('book','apply_correction'));
    await page.locator('select[name=unit]').selectOption('%');
    await page.getByLabel('Neuer Bestand (%)', {exact:true}).fill('101');
    assert.equal(await page.locator('form').evaluate(form => form.checkValidity()), false);
    await page.getByLabel('Neuer Bestand (%)', {exact:true}).fill('10');
    await page.getByRole('button',{name:'Bestand korrigieren',exact:true}).click();
    assert.equal(await page.locator('dialog').count(), 0);
    const booking = await page.evaluate(() => window.booking);
    assert.equal(booking.parameters.unit, '%');
    assert.equal(booking.parameters.liters, 10);
    assert.equal(booking.parameters.kind, 'correction');
    console.log('Passed: 14 cancel cases, percent validation, request and successful close.');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
