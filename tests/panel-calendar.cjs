// Browser interaction checks with calendar reports produced by the Python backend.
const {chromium} = require('playwright');
const {execFileSync} = require('node:child_process');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({channel:'msedge',headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1280,height:1000}});
    await page.route('http://localhost/**', route=>route.fulfill({body:'',contentType:'text/html'}));
    await page.goto('http://localhost/');
    await page.exposeFunction('statistics', parameters => JSON.parse(execFileSync(
      path.resolve('.venv/Scripts/python.exe'), ['-c',
        `import json,sys
from datetime import datetime,timezone
from custom_components.ha_tankdata.insights import calendar_summary
from custom_components.ha_tankdata.model import new_tank
d=new_tank(1000,1000)
d['events']=[{'id':'demo','kind':'consumption','liters':2,'source_id':'burner','at':'2026-09-16T08:30:00Z','start':'2026-09-16T06:30:00Z','end':'2026-09-16T08:30:00Z','runtime_seconds':7200}]
print(json.dumps(calendar_summary(d,{'burner':{}},datetime(2026,9,16,12,tzinfo=timezone.utc),tz='Europe/Berlin',**json.loads(sys.argv[1]))))`,
        JSON.stringify(parameters)], {encoding:'utf8'})));
    await page.setContent('<tankdata-panel></tankdata-panel>');
    await page.addScriptTag({path:path.resolve('custom_components/ha_tankdata/frontend/tankdata-panel.js')});
    await page.evaluate(async()=>{
      const panel=document.querySelector('tankdata-panel');
      panel.style.height='auto';panel.style.overflow='visible';
      const report=await window.statistics({period:'day'});
      panel.tanks=[{id:'test',name:'Heizöltank',status:'loaded',stock:998,percent:99.8,capacity:1000,
        consumers:[{id:'burner',name:'Brenner',config:{mode:'power'}}],settings:{geometry:{shape:'rectangle'}},
        fill_height:.9,proposals:[],statistics:report,forecast:{available:false,reason:'Zu wenige Messtage.'}}];
      panel.selected='test';
      panel._hass={states:{},callWS:async request=>{
        if(request.operation==='statistics') {window.lastRequest=request;return window.statistics(request.parameters);}
        if(request.type==='ha_tankdata/get_tanks') return {tanks:panel.tanks,version:'test'};
        return {events:[],before:0};
      }};
      panel.render();
    });
    const slots=page.locator('.calendar-slot');
    await slots.nth(23).waitFor();
    assert.equal(await slots.count(),24);
    for(const [period,count,granularity] of [['week',7,'day'],['month',30,'day'],['year',12,'month'],['all',1,'year']]) {
      await page.locator(`[data-period=${period}]`).click();
      await page.waitForFunction(p=>document.querySelector('tankdata-panel').report?.period===p,period);
      assert.equal(await slots.count(),count);
      assert.equal(await page.evaluate(()=>document.querySelector('tankdata-panel').report.granularity),granularity);
    }
    assert.equal(await page.locator('[name=report-anchor]').count(),0);
    await page.locator('[data-period=month]').click();
    await page.locator('input[type=month]').waitFor();
    await page.locator('[name=report-anchor]').fill('2024-02');
    await page.waitForFunction(()=>document.querySelector('tankdata-panel').report?.anchor==='2024-02-01');
    assert.equal(await slots.count(),29);
    await page.getByRole('button',{name:'Vorheriger Zeitraum',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('tankdata-panel').report?.anchor==='2024-01-01');
    assert.equal(await slots.count(),31);
    await page.locator('[data-period=week]').click();
    await page.locator('input[type=date]').waitFor();
    await page.locator('[name=report-anchor]').fill('2026-01-01');
    await page.waitForFunction(()=>document.querySelector('tankdata-panel').report?.start==='2025-12-29');
    await page.evaluate(()=>document.querySelector('tankdata-panel').refresh());
    assert.equal(await page.locator('[name=report-anchor]').inputValue(),'2026-01-01');
    await page.locator('[data-period=day]').click();
    await page.waitForFunction(()=>document.querySelector('tankdata-panel').report?.period==='day');
    assert.equal(await page.locator('[name=report-anchor]').inputValue(),'2026-09-16');
    await page.locator('[name=report-anchor]').fill('2026-03-29');
    await page.waitForFunction(()=>document.querySelector('tankdata-panel').report?.days.length===23);
    assert.equal(await slots.count(),23);
    await page.locator('[data-period=year]').click();
    await page.locator('select[name=report-anchor]').waitFor();
    await page.getByRole('button',{name:'Vorheriger Zeitraum',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('tankdata-panel').report?.anchor==='2025-01-01');
    await page.locator('select[name=report-anchor]').selectOption('2026');
    await page.waitForFunction(()=>document.querySelector('tankdata-panel').report?.anchor==='2026-01-01');
    for (const width of [1280,390,320]) {
      await page.setViewportSize({width,height:1000});
      await page.locator('[data-period=day]').click();
      await page.waitForFunction(()=>document.querySelector('tankdata-panel').report?.period==='day');
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
      for (const period of ['day','week','month','year','all']) {
        await page.locator(`[data-period=${period}]`).click();
        await page.waitForFunction(p=>document.querySelector('tankdata-panel').report?.period===p,period);
        assert.equal(await page.locator('.chart-scroll').evaluate(el=>el.scrollWidth<=el.clientWidth),true,`${width}/${period}: no chart overflow`);
        assert.equal(await page.locator('.calendar-chart').evaluate(el=>el.scrollWidth<=el.clientWidth),true,`${width}/${period}: all bars fit`);
        await slots.last().click();
        assert.notEqual(await page.locator('.chart-value').textContent(),'');
      }
      await page.locator('[data-period=month]').click();
      await page.waitForFunction(()=>document.querySelector('tankdata-panel').report?.period==='month');
      await page.locator('[name=report-anchor]').fill('2026-01');
      await page.waitForFunction(()=>document.querySelector('tankdata-panel').report?.days.length===31);
      assert.equal(await page.locator('.calendar-chart').evaluate(el=>el.scrollWidth<=el.clientWidth),true);
      await page.screenshot({path:path.resolve(`.local/calendar-${width}.png`),fullPage:true});
    }
    console.log('Passed: calendar tabs, leap February, navigation, week/year boundaries, refresh persistence, DST, year picker, desktop/mobile layout.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
