import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {chromium} from 'playwright';
const driver=readFileSync(new URL('./page-driver.js',import.meta.url),'utf8');
const browser=await chromium.launch({headless:true});
try{
  const page=await browser.newPage();let pageCalls=[];
  await page.route('http://profiles.test/**',async route=>{
    const url=new URL(route.request().url());
    if(url.pathname.includes('vehicle-makers')){
      const pageNumber=Number(url.searchParams.get('page'));pageCalls.push(pageNumber);
      const makers=pageNumber===0?Array.from({length:20},(_,index)=>`Maker ${index}`):pageNumber===1?['Maker 20','OTHERS']:[];
      await route.fulfill({json:makers});return;
    }
    await route.fulfill({contentType:'text/html',body:`
      <select id="reportType"><option>CALENDAR YEAR</option></select><input id="fromYear"><input id="toYear">
      <select id="delhiNcr"><option>ALL STATES</option></select><select id="stateName" multiple><option>State A</option></select><select id="rtoCode" multiple></select>
      <select id="yAxis"><option>Maker</option></select><select id="xAxis"><option>Month Wise</option></select>
      <select id="vehicleCategoryGroup" multiple><option>Group A</option><option>Group B</option></select>
      <select id="vehicleSubCategory" multiple><option>Sub A</option><option>Sub B</option></select>
      <select id="vehicleClass" multiple><option>Class A</option></select>
      <script>document.querySelector('#vehicleSubCategory').onchange=()=>{
        const selected=[...document.querySelector('#vehicleSubCategory').selectedOptions].map(option=>option.textContent);
        document.querySelector('#vehicleClass').innerHTML=selected.includes('Sub B')?'<option>Class B</option>':'<option>Class A</option>';
      };</script>`});
  });
  await page.goto('http://profiles.test/analytics/vahanpublicreport');await page.evaluate(driver);
  const options=await page.evaluate(()=>vahanDriver.filterContext({period:'CALENDAR YEAR',fromYear:'2024',toYear:'2024',
    delhiNcr:'ALL STATES',states:[],rtos:[],yAxis:'Maker',xAxis:'Month Wise',categoryGroups:['Group B'],subCategories:['Sub B']}));
  assert.deepEqual(options.classes,['Class B']);
  const makers=await page.evaluate(()=>vahanDriver.allMakers());
  assert.equal(makers.length,22);assert.ok(makers.includes('OTHERS'));assert.deepEqual(pageCalls,[0,1,2]);
  await page.unroute('http://profiles.test/**');
  await page.route('http://profiles.test/**',route=>route.fulfill({json:['Repeated maker']}));
  await assert.rejects(page.evaluate(()=>vahanDriver.allMakers()),/pagination did not advance/);
  console.log('Profile options: native dependent Class, complete Maker pagination beyond 20, OTHERS and stalled pagination passed.');
}finally{await browser.close();}
