const {chromium}=require('playwright');
const path=require('node:path');
const assert=require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const page=await browser.newPage({viewport:{width:1200,height:900}});
    await page.route('http://localhost/**',r=>r.fulfill({body:'',contentType:'text/html'}));
    await page.goto('http://localhost/');
    await page.setContent('<tankdata-panel></tankdata-panel>');
    await page.addScriptTag({path:path.resolve('custom_components/ha_tankdata/frontend/tankdata-panel.js')});
    await page.evaluate(async()=>{
      const p=document.querySelector('tankdata-panel');
      p.style.height='auto';p.style.overflow='visible';
      window.entries=Array.from({length:102},(_,i)=>({id:`event-${i}`,kind:'consumption',source_id:'burner',liters:.01,runtime_seconds:30,at:new Date(Date.UTC(2026,8,16,10,0,i*30+30)).toISOString(),start:new Date(Date.UTC(2026,8,16,10,0,i*30)).toISOString(),end:new Date(Date.UTC(2026,8,16,10,0,i*30+30)).toISOString()}));
      window.finished=false;
      p.tanks=[{id:'test',name:'Heizöltank',status:'loaded',stock:999,capacity:1000,percent:99.9,event_count:102,consumers:[{id:'burner',name:'Brenner',config:{mode:'power'}}]}];
      p.selected='test';p.analysisView=()=>'';
      p._hass={states:{},config:{time_zone:'Europe/Berlin'},callWS:async req=>{
        if(req.type==='ha_tankdata/get_tanks')return {tanks:p.tanks,version:'test'};
        if(req.run_id){const end=req.before??window.entries.length,start=Math.max(0,end-50);return {events:window.entries.slice(start,end).reverse(),before:start,count:window.entries.length};}
        return {events:[{id:'event-0',kind:'run',source_id:'burner',start:window.entries[0].start,end:window.entries.at(-1).end,liters:window.entries.length*.01,runtime_seconds:window.entries.length*30,count:window.entries.length,status:window.finished?'finished':'running'}],before:0,count:1};
      }};
      await p.loadHistory();p.render();
    });
    assert.equal(await page.getByText('Läuft',{exact:true}).count(),1);
    assert.equal(await page.locator('[data-run]').count(),0);
    assert.equal(await page.getByText(/Einzelbuchungen/).count(),0);
    assert.equal(await page.locator('details').count(),0);
    await page.evaluate(async()=>{const e=window.entries.at(-1);window.entries.push({...e,id:'new'});await document.querySelector('tankdata-panel').refresh();});
    assert.equal(await page.getByText('1,03 L',{exact:true}).count(),1);
    assert.equal(await page.getByText(/Einzelbuchungen/).count(),0);
    await page.evaluate(async()=>{window.finished=true;await document.querySelector('tankdata-panel').refresh();});
    assert.equal(await page.getByText('Beendet',{exact:true}).count(),1);
    for (const width of [1200,390]) {
      await page.setViewportSize({width,height:900});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
      await page.screenshot({path:path.resolve(`.local/history-${width}.png`),fullPage:true});
    }
    console.log('Passed: single run, no individual bookings or expansion, growth, stop, desktop/mobile.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
