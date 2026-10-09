import {currentReportYear, type MatrixPlan} from './matrix-plan';
import {API_URL, csrfHeaders, ApiError} from './services/api-client';

export const FILTER_PROFILE_STORAGE_KEY = 'vahanSelectedFilterProfileV1';
export const PROFILE_FIELDS = [
  {id:'archivedFlags',label:'Active / Archive Type'},
  {id:'states',label:'State'}, {id:'rtos',label:'RTO'}, {id:'emissions',label:'Emission'}, {id:'makers',label:'Maker'},
  {id:'categoryGroups',label:'Category Group'}, {id:'subCategories',label:'Sub-Category',parents:['categoryGroups']},
  {id:'classes',label:'Class',parents:['categoryGroups','subCategories']},
  {id:'fuels',label:'Fuel',parents:['evTypes']}, {id:'evTypes',label:'EV Type'},
  {id:'statuses',label:'Status'}, {id:'ownerTypes',label:'Owner Type'},
  {id:'vehicleType',label:'Type',scalar:true}, {id:'delhiNcr',label:'Delhi NCR ?',scalar:true},
  {id:'fitness',label:'Fitness Valid as On Date?',scalar:true},
] as const;
export type ProfileField = typeof PROFILE_FIELDS[number]['id'];
export type FilterPolicy = {mode:'fixed'|'iterate';values:string[];include:string[];exclude:string[]};
export type CombinationRule = {whenField:ProfileField;whenValues:string[];targetField:ProfileField;targetValues:string[];action:'require'|'exclude'};
export type ProfileDefinition = {report?:{year:number;period:'CALENDAR YEAR';yAxis:'Maker';xAxis:'Month Wise'};version:1;fields:Record<ProfileField,FilterPolicy>;rules:CombinationRule[];maxCases:number};
export type FilterProfile = {id:string;name:string;revision:number;definition:ProfileDefinition;updatedAt:string};
export type ProfileOptions = Partial<Record<ProfileField,string[]>>;

export function defaultProfile(year=currentReportYear()):ProfileDefinition {
  const fields=Object.fromEntries(PROFILE_FIELDS.map(field=>[field.id,{mode:'fixed',values:[],include:[],exclude:[]} as FilterPolicy])) as ProfileDefinition['fields'];
  fields.states.mode=fields.rtos.mode='iterate';
  fields.delhiNcr.values=['ALL STATES'];
  fields.archivedFlags.values=['ACTIVE_COMPLIANT','ACTIVE_NON_COMPLIANT','PERMANENT_ARCHIVE','TEMPORARY_ARCHIVE'];
  fields.categoryGroups.values=['Two Wheeler'];
  fields.subCategories.values=['TWO WHEELER (Invalid Carriage)','TWO WHEELER(NT)','TWO WHEELER(T)'];
  fields.fuels.values=['ELECTRIC(BOV)','PURE EV'];
  return {version:1,report:{year,period:'CALENDAR YEAR',yAxis:'Maker',xAxis:'Month Wise'},fields,rules:[],maxCases:3000};
}

export function parentContext(definition:ProfileDefinition) {
  const fixed=(field:ProfileField)=>definition.fields[field].mode==='fixed'?definition.fields[field].values:[];
  return {delhiNcr:fixed('delhiNcr')[0]||'ALL STATES',states:fixed('states'),
    categoryGroups:fixed('categoryGroups'),subCategories:fixed('subCategories'),evTypes:fixed('evTypes')};
}

export async function previewFilterProfile(id:string,runnerId:string,year:number,onProgress:(message:string)=>void,signal?:AbortSignal):Promise<MatrixPlan> {
  const response=await fetch(`${API_URL}/api/filter-profiles/${id}/preview`,{method:'POST',signal,credentials:'include',
    headers:{'Content-Type':'application/json',...csrfHeaders()},body:JSON.stringify({runnerId,year})});
  if(!response.ok){const body=await response.json().catch(()=>({}));throw new ApiError(response.status,body.detail||'Could not preview filters.');}
  if(!response.body)throw new Error('The filter preview stream is unavailable.');
  const reader=response.body.getReader(),decoder=new TextDecoder();let pending='';let plan:MatrixPlan|null=null;
  try {
    for(;;){const {value,done}=await reader.read();pending+=decoder.decode(value,{stream:!done});
      const lines=pending.split('\n');pending=lines.pop()!;
      for(const line of lines){if(!line.trim())continue;const event=JSON.parse(line);
        if(event.type==='progress')onProgress(event.message);
        if(event.type==='error')throw new Error(event.message);
        if(event.type==='ready')plan=event.plan;
      }
      if(done)break;
    }
  } finally {await reader.cancel().catch(()=>{});reader.releaseLock();}
  if(!plan?.scenarios?.length||plan.year!==year||plan.profileId!==id)throw new Error('The filter preview was incomplete. Retry before running.');
  return plan;
}
