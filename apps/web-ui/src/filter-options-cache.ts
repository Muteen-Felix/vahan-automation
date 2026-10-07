import {persistentState} from './services/persistent-state';
import type {MatrixPlan} from './matrix-plan';
import {PROFILE_FIELDS,type ProfileOptions} from './filter-profiles';
const KEY='vahanFilterOptionsV1';
type Context={delhiNcr:string;states:string[];categoryGroups:string[];subCategories:string[];evTypes:string[]};
type Entry={key:string;year:number;region:string;context?:Context;options:ProfileOptions};
function contextKey(year:number,context:Context){return JSON.stringify([year,Object.fromEntries(Object.entries(context).map(([key,value])=>[key,Array.isArray(value)?[...value].sort():value]))]);}
function entries():Entry[]{
 try{return (JSON.parse(persistentState.getItem(KEY)||'[]') as Entry[]).filter(entry=>entry&&typeof entry.key==='string'&&entry.options&&PROFILE_FIELDS.every(field=>!entry.options[field.id]||Array.isArray(entry.options[field.id])&&entry.options[field.id]!.every(value=>typeof value==='string')));}catch{return [];}
}
export function saveFilterOptions(year:number,context:Context,options:ProfileOptions){
 const key=contextKey(year,context);persistentState.setItem(KEY,JSON.stringify([{key,year,region:context.delhiNcr,context,options},...entries().filter(entry=>entry.key!==key)].slice(0,20)));
}
export function cachedFilterOptions(year:number,context:Context,plan:MatrixPlan|null):ProfileOptions{
 const saved=entries(),exact=saved.find(entry=>entry.key===contextKey(year,context));
 const regional=saved.find(entry=>entry.year===year&&entry.region===context.delhiNcr&&entry.options.states?.length);
 const result:ProfileOptions={};
 const dependencies:Partial<Record<typeof PROFILE_FIELDS[number]['id'],(keyof Context)[]>>={states:['delhiNcr'],rtos:['delhiNcr','states'],subCategories:['categoryGroups'],classes:['categoryGroups','subCategories'],fuels:['evTypes']};
 for(const field of PROFILE_FIELDS){
  const match=saved.find(entry=>{
   if(entry.year!==year||entry.region!==context.delhiNcr||!entry.options[field.id])return false;
   let old:Context;try{old=entry.context||JSON.parse(entry.key)[1];}catch{return false;}
   return (dependencies[field.id]||[]).every(parent=>JSON.stringify(Array.isArray(old[parent])?[...old[parent]].sort():old[parent])===JSON.stringify(Array.isArray(context[parent])?[...context[parent]].sort():context[parent]));
  });
  if(match)result[field.id]=match.options[field.id];
 }
 result.states=exact?.options.states||regional?.options.states||result.states||[];
 const relevant=plan?.year===year?plan.scenarios.filter(case_=>String(case_.filters.delhiNcr||'ALL STATES')===context.delhiNcr):[];
 if(!result.states?.length)result.states=[...new Set(relevant.flatMap(case_=>case_.filters.states))];
 if(!result.rtos?.length&&context.states.length){
  result.rtos=[...new Set(relevant.filter(case_=>case_.filters.states.some(state=>context.states.includes(state))).flatMap(case_=>case_.filters.rtos))];
 }
 return result;
}
