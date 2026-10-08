import assert from 'node:assert/strict';
import {chromium} from 'playwright';
import {readFileSync} from 'node:fs';
import {inspectControls,selectorOverrides} from './ui-health-contract.mjs';
const browser=await chromium.launch({headless:true});
try{
 const page=await browser.newPage();
 const old={field:'states',selector:'#stateName',tag:'select',multiple:true,name:'stateMultiple',label:'State'};
 await page.setContent('<label for="newState">State</label><select id="newState" name="stateMultiple" multiple><option>State A</option></select>');
 const [row]=await inspectControls(page,{controls:[old]});assert.equal(row.selector,'#newState');assert.equal(row.matchedBy,'name');assert.equal(row.count,1);
 await page.addScriptTag({content:readFileSync(new URL('./page-driver.js',import.meta.url),'utf8')});
 await page.evaluate(overrides=>{globalThis.vahanSelectorOverrides=overrides;},selectorOverrides([row],[old]));
 const options=await page.evaluate(()=>globalThis.vahanDriver.readOptions({states:{selector:'#stateName'}}));assert.deepEqual(options.states,['State A'],'crawler actually uses the approved selector alias');
 await page.setContent('<select id="a" name="stateMultiple" multiple></select><select id="b" name="stateMultiple" multiple></select>');
 const [ambiguous]=await inspectControls(page,{controls:[old]});assert.equal(ambiguous.found,false);
 await page.setContent('<input id="stateName" name="stateMultiple">');
 const [wrong]=await inspectControls(page,{controls:[old]});assert.equal(wrong.tag,'input','evidence retains wrong tag for the SQL validator to reject');
 await page.setContent('<label for="renamed">State</label><select id="renamed" multiple><option value="a">Same label</option></select>');
 const [labelMatch]=await inspectControls(page,{controls:[old]});assert.equal(labelMatch.matchedBy,'label');
 await page.locator('option').evaluate(option=>{option.value='b';});
 const [newValue]=await inspectControls(page,{controls:[old]});assert.notEqual(newValue.optionsHash,labelMatch.optionsHash,'changed option values must be recorded even when labels match');
 console.log('UI contract: unique semantic recovery, runtime selector alias, ambiguous candidates and wrong types passed.');
}finally{await browser.close();}
