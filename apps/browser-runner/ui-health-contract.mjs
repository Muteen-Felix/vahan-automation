import {createHash} from 'node:crypto';
// Inspection uses an independent browser context; no report filters or CAPTCHA are submitted.
export async function inspectControls(page,contract){
 const rows=await page.evaluate(specs=>{
  const norm=value=>String(value||'').replace(/\s+/g,' ').trim().toLowerCase();
  const labelOf=element=>[...element.labels||[]].map(label=>label.textContent).join(' ').trim()||element.getAttribute('aria-label')||(['BUTTON','A'].includes(element.tagName)?element.textContent.trim():'');
  return specs.map(spec=>{
   let matches=[];try{matches=[...document.querySelectorAll(spec.selector)];}catch{}
   let matchedBy='selector';
   if(matches.length!==1){
    const candidates=[...document.querySelectorAll('select,input,button,a')].filter(element=>spec.tag==='action'?['BUTTON','A','INPUT'].includes(element.tagName):element.tagName.toLowerCase()===spec.tag);
    const byName=spec.name?candidates.filter(element=>element.getAttribute('name')===spec.name):[];
    const byLabel=spec.label?candidates.filter(element=>norm(labelOf(element))===norm(spec.label)):[];
    if(byName.length===1){matches=byName;matchedBy='name';}
    else if(byLabel.length===1){matches=byLabel;matchedBy='label';}
   }
   if(matches.length!==1)return {field:spec.field,found:false,count:matches.length,selector:spec.selector};
   const element=matches[0];let selector=spec.selector;
   if(matchedBy!=='selector'){
    if(element.id)selector='#'+CSS.escape(element.id);
    else if(element.getAttribute('name'))selector='[name='+JSON.stringify(element.getAttribute('name'))+']';
    else return {field:spec.field,found:false,count:0,selector:spec.selector};
    if(document.querySelectorAll(selector).length!==1)return {field:spec.field,found:false,count:document.querySelectorAll(selector).length,selector};
   }
   return {field:spec.field,found:true,count:1,matchedBy,selector,id:element.id,name:element.getAttribute('name')||'',label:labelOf(element),tag:element.tagName.toLowerCase(),multiple:element.tagName==='SELECT'?element.multiple:undefined,inputType:element.tagName==='INPUT'?element.type:undefined,className:String(element.className||'').split(/\s+/).filter(Boolean).sort().join(' '),role:element.getAttribute('role')||'',optionLabels:element.tagName==='SELECT'?[...element.options].map(option=>({label:(option.label||option.textContent||'').trim(),value:option.value,disabled:option.disabled})):[]};
  });
 },contract.controls);
 return rows.map(({optionLabels,...row})=>({...row,optionsHash:createHash('sha256').update(JSON.stringify(optionLabels||[])).digest('hex'),optionCount:optionLabels?.length||0}));
}
export function selectorOverrides(controls,seeds){
 const original=Object.fromEntries(seeds.map(control=>[control.field,control.selector]));
 return Object.fromEntries(controls.filter(control=>original[control.field]&&original[control.field]!==control.selector).map(control=>[original[control.field],control.selector]));
}
