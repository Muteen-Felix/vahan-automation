import {useEffect, useId, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import type {Runner} from '../contracts';
import {currentReportYear, MIN_REPORT_YEAR, type MatrixPlan} from '../matrix-plan';
import {api} from '../services/api-client';
import {defaultProfile, parentContext, previewFilterProfile, PROFILE_FIELDS,
  type FilterProfile, type FilterPolicy, type ProfileDefinition, type ProfileField, type ProfileOptions, type CombinationRule} from '../filter-profiles';

function ValuePicker({label,values,options,disabled,one,required,onChange,onSearch,policy,onPolicy}: {
  label:string;values:string[];options:string[];disabled:boolean;one?:boolean;required?:boolean;
  onChange:(values:string[])=>void;onSearch?:(search:string)=>Promise<void>;
  policy?:FilterPolicy;onPolicy?:(patch:Partial<FilterPolicy>)=>void;
}) {
  const [search,setSearch]=useState('');
  const [searching,setSearching]=useState(false);
  const [error,setError]=useState('');
  const [open,setOpen]=useState(false);
  const [editingExcluded,setEditingExcluded]=useState(false);
  const dialog=useRef<HTMLDialogElement>(null);
  const dialogId=useId();
  useEffect(()=>{
    const element=dialog.current;
    if(open&&!element?.open)element?.showModal();
    if(!open&&element?.open)element.close();
  },[open]);
  const selected=policy?.mode==='iterate'?(editingExcluded?policy.exclude:policy.include):values;
  const visible=[...new Set([...options,...selected])].filter(value=>value.toLowerCase().includes(search.toLowerCase()));
  const summary=policy?.mode==='iterate'?(policy.include.length?`${policy.include.length} selected`:'All valid values')
    :values.length?`${values.length} selected`:required?'Select values':'No restriction';
  const displayed=policy?.mode==='iterate'?policy.include:values;
  const selectValues=(next:string[])=>{
    if(policy?.mode==='iterate')onPolicy?.(editingExcluded?{exclude:next}:{include:next});
    else onChange(next);
  };
  const archiveLabels:Record<string,string>={ACTIVE_COMPLIANT:'Active Compliant',ACTIVE_NON_COMPLIANT:'Active Non-Compliant',PERMANENT_ARCHIVE:'Permanent Archive',TEMPORARY_ARCHIVE:'Temporary Archive'};
  const renderOption=(value:string)=><label key={value}><input type="checkbox" checked={selected.includes(value)} disabled={disabled} onChange={event=>selectValues(event.target.checked
    ?one&&policy?.mode!=='iterate'?[value]:[...selected,value]:selected.filter(item=>item!==value))} /><span>{archiveLabels[value]||value}</span></label>;
  return <div className="profile-value-picker">
    <button type="button" className="profile-picker-trigger" disabled={disabled} aria-label={policy?label:undefined} aria-haspopup="dialog" aria-expanded={open} aria-controls={dialogId}
      title={label} onClick={()=>{setEditingExcluded(false);setOpen(true);}}><span>{policy?summary:label}</span>{!policy&&<strong>{summary}</strong>}<i aria-hidden="true">⌄</i></button>
    <div className="profile-selected-values" title={displayed.join(', ')}>{displayed.map(value=>archiveLabels[value]||value).join(', ')}{policy?.mode==='iterate'&&policy.exclude.length?`${displayed.length?' · ':''}${policy.exclude.length} excluded`:''}</div>
    {createPortal(<dialog ref={dialog} id={dialogId} className="profile-picker-dialog" aria-label={label}
      onCancel={event=>{if(event.target===event.currentTarget){event.preventDefault();setOpen(false);}}} onClose={event=>{if(event.target===event.currentTarget)setOpen(false);}}
      onClick={event=>{if(event.target===event.currentTarget){const box=event.currentTarget.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)setOpen(false);}}}>
      <div className="profile-picker-header"><div><h3>{label}</h3><p>{summary} · {policy?.mode==='iterate'?'One case per valid value':one?'Choose one value':'Choose the values to use'}</p></div>
        <button type="button" className="profile-picker-close" aria-label="Close value picker" onClick={()=>setOpen(false)}>×</button></div>
      <div className="profile-picker-body">
        {policy&&<label className="profile-dialog-mode">Mode<select aria-label={`${label} mode`} value={policy.mode} disabled={disabled}
          onChange={event=>{setEditingExcluded(false);onPolicy?.({mode:event.target.value as FilterPolicy['mode']});}}><option value="fixed">Fixed values</option><option value="iterate">Iterate all</option></select></label>}
        {policy?.mode==='iterate'&&<div className="profile-iteration-tools"><p>{editingExcluded?'Checked values will be excluded.':'Select values to limit iteration, or leave empty to use all valid values.'}</p>
          <button type="button" aria-pressed={editingExcluded} onClick={()=>setEditingExcluded(value=>!value)}>{editingExcluded?'Back to values':`Exclusions (${policy.exclude.length})`}</button></div>}
        <input type="search" aria-label={`Search ${label}`} value={search} placeholder="Search values"
          disabled={disabled} onChange={event=>setSearch(event.target.value)} />
        {onSearch&&<button type="button" disabled={disabled||searching||!search.trim()} onClick={async()=>{
          setSearching(true);setError('');try{await onSearch(search.trim());}catch(reason){setError(reason instanceof Error?reason.message:'Search failed.');}finally{setSearching(false);}
        }}>{searching?'Searching…':'Search VAHAN'}</button>}
        {error&&<p role="alert">{error}</p>}
        <div className="profile-picker-options">{visible.length?label==='Active / Archive Type'
          ?<>{['Active Type','Archive Type'].map(group=><section className="profile-archive-group" key={group}><h4>{group}</h4>{visible.filter(value=>group==='Active Type'?value.startsWith('ACTIVE_'):!value.startsWith('ACTIVE_')).map(renderOption)}</section>)}</>
          :visible.map(renderOption):<p>Load options or choose a parent filter first.</p>}</div>
      </div>
      <div className="profile-picker-footer"><span>{visible.length} matching values</span><button type="button" disabled={disabled||!selected.length} onClick={()=>selectValues([])}>Clear selection</button>
        <button type="button" className="profile-picker-done" onClick={()=>setOpen(false)}>Done</button></div>
    </dialog>,document.body)}
  </div>;
}

export function FilterProfiles({profiles,runners,year:legacyYear,busy,onSaved,onSelect}: {
  profiles:FilterProfile[];runners:Runner[];year:number;busy:boolean;
  onSaved:()=>Promise<void>;onSelect:(id:string,plan:MatrixPlan)=>void;
}) {
  const [id,setId]=useState(''),[name,setName]=useState(''),[revision,setRevision]=useState<number>();
  const [definition,setDefinition]=useState<ProfileDefinition>(()=>defaultProfile(legacyYear));
  const year=definition.report?.year??legacyYear;
  const years=Array.from({length:currentReportYear()-MIN_REPORT_YEAR+1},(_,index)=>currentReportYear()-index);
  function changeYear(value:number){setDefinition(current=>({...current,report:{year:value,period:'CALENDAR YEAR',yAxis:'Maker',xAxis:'Month Wise'}}));setPreview(null);setMessage('');}
  const [options,setOptions]=useState<ProfileOptions>({});
  const [runnerId,setRunnerId]=useState('');
  const [working,setWorking]=useState(false),[loading,setLoading]=useState(false);
  const [error,setError]=useState(''),[message,setMessage]=useState('');
  const [preview,setPreview]=useState<MatrixPlan|null>(null);
  const [refresh,setRefresh]=useState(0);
  const [optionsState,setOptionsState]=useState('');
  const [rulesOpen,setRulesOpen]=useState(false);
  const rulesDialog=useRef<HTMLDialogElement>(null);
  useEffect(()=>{
    if(rulesOpen&&!rulesDialog.current?.open)rulesDialog.current?.showModal();
    if(!rulesOpen&&rulesDialog.current?.open)rulesDialog.current.close();
  },[rulesOpen]);
  const mounted=useRef(true),optionsPending=useRef(false),wantedContext=useRef(''),loadedContext=useRef('');
  const previewAbort=useRef<AbortController|null>(null);
  const parents=parentContext(definition);
  if(definition.fields.states.mode==='iterate'&&optionsState)parents.states=[optionsState];
  const contextKey=JSON.stringify([runnerId,year,parents,refresh]);
  const disabled=working;

  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;previewAbort.current?.abort();};},[]);
  useEffect(()=>{if(!runnerId){const runner=runners.find(item=>item.source==='new'&&item.status==='ONLINE'&&!item.currentJobId);if(runner)setRunnerId(runner.id);}},[runners,runnerId]);
  useEffect(()=>{
    wantedContext.current=contextKey;
    if(!runnerId||disabled||busy)return;
    const timer=window.setTimeout(async()=>{
      if(optionsPending.current)return;
      optionsPending.current=true;setLoading(true);setError('');
      try {
        while(mounted.current&&loadedContext.current!==wantedContext.current){
          const key=wantedContext.current;const [runner,selectedYear,context]=JSON.parse(key);
          const loaded=await api.filterOptions(runner,selectedYear,context);
          if(mounted.current&&wantedContext.current===key){setOptions(loaded);loadedContext.current=key;}
        }
      }catch(reason){if(mounted.current)setError(reason instanceof Error?reason.message:'Could not load filter options.');}
      finally{optionsPending.current=false;if(mounted.current)setLoading(false);}
    },450);
    return()=>window.clearTimeout(timer);
  },[contextKey,runnerId,disabled,busy]);

  function changeField(field:ProfileField,patch:Partial<FilterPolicy>){
    setPreview(null);setMessage('');
    if(field==='delhiNcr')setOptionsState('');
    setDefinition(current=>{
      const fields={...current.fields,[field]:{...current.fields[field],...patch}};
      if(patch.values||patch.mode){
        const children:Partial<Record<ProfileField,ProfileField[]>>={delhiNcr:['states','rtos'],states:['rtos'],categoryGroups:['subCategories','classes'],subCategories:['classes'],evTypes:['fuels']};
        for(const child of children[field]||[])fields[child]={...fields[child],values:[],include:[],exclude:[]};
      }
      return {...current,fields};
    });
  }
  function edit(profile?:FilterProfile){setId(profile?.id||'');setName(profile?.name||'');setRevision(profile?.revision);
    setDefinition(profile?{...structuredClone(profile.definition),report:profile.definition.report??{year:legacyYear,period:'CALENDAR YEAR',yAxis:'Maker',xAxis:'Month Wise'}}:defaultProfile(legacyYear));setOptionsState('');setPreview(null);setError('');setMessage('');}
  function validate(){
    if(!name.trim())throw new Error('Enter a profile name.');
    for(const field of ['states','rtos','delhiNcr','archivedFlags'] as ProfileField[])if(definition.fields[field].mode==='fixed'&&!definition.fields[field].values.length)
      throw new Error(`Select ${field}, or use Iterate all.`);
    if(definition.rules.some(rule=>!rule.whenValues.length||!rule.targetValues.length))throw new Error('Complete the values in every combination rule.');
  }
  async function save(showPreview=false){
    setError('');setMessage('');setWorking(true);setPreview(null);
    try{
      validate();const payload={...definition,report:definition.report??{year,period:'CALENDAR YEAR' as const,yAxis:'Maker' as const,xAxis:'Month Wise' as const}};const saved=await api.saveFilterProfile(name.trim(),payload,id||undefined,revision);
      setId(saved.id);setRevision(saved.revision);await onSaved();setMessage('Saved to SQL.');
      if(showPreview){if(!runnerId)throw new Error('Select an idle browser worker.');
        const controller=new AbortController();previewAbort.current=controller;
        const plan=await previewFilterProfile(saved.id,runnerId,year,setMessage,controller.signal);
        if(mounted.current){setPreview(plan);setMessage(`${plan.scenarios.length.toLocaleString()} valid cases · ${plan.skippedBranches||0} branches excluded by dependencies or rules`);}
      }
    }catch(reason){if(mounted.current)setError(reason instanceof Error?reason.message:'Could not save filters.');}
    finally{if(mounted.current)setWorking(false);previewAbort.current=null;}
  }
  const searchMakers=async(search:string)=>{
    if(!runnerId)throw new Error('Select a browser worker.');
    const values=await api.filterMakers(runnerId,year,search);setOptions(current=>({...current,makers:values}));
  };
  const setRule=(index:number,patch:Partial<CombinationRule>)=>{setPreview(null);setDefinition(current=>({...current,rules:current.rules.map((rule,position)=>position===index?{...rule,...patch}:rule)}));};

  return <main className="page-content filter-profiles-page">
    <div className="filter-profiles-title"><div><h2>Filters</h2><p>Save the reporting year and filter selections together.</p></div>
      <button type="button" disabled={disabled} onClick={()=>edit()}>New profile</button></div>
    <div className="filter-profiles-workspace">
      <aside className="profile-list"><h3>Saved in SQL</h3>{profiles.length?profiles.map(profile=><button type="button" key={profile.id}
        disabled={disabled} aria-pressed={id===profile.id} onClick={()=>edit(profile)}><strong>{profile.name}</strong><small>Revision {profile.revision}</small></button>):<p>No saved profiles yet.</p>}</aside>
      <section className="profile-editor" aria-label="Filter profile editor">
        <div className="profile-editor-toolbar"><label>Profile name<input value={name} maxLength={120} disabled={disabled} onChange={event=>{setName(event.target.value);setPreview(null);}} /></label>
          <label>Options worker<select value={runnerId} disabled={disabled||loading} onChange={event=>setRunnerId(event.target.value)}><option value="">Select an idle worker</option>
            {runners.filter(runner=>runner.source==='new').map(runner=><option key={runner.id} value={runner.id} disabled={runner.status!=='ONLINE'&&runner.id!==runnerId}>{runner.name} · {runner.status}</option>)}</select></label>
          <button type="button" disabled={disabled||busy||loading||!runnerId} onClick={()=>setRefresh(value=>value+1)}>Refresh options</button></div>
        <div className="profile-report-context" aria-label="Report settings">
          <label>Year Type<input value="CALENDAR YEAR" readOnly /></label><label>From<select aria-label="Report from year" value={year} disabled={disabled} onChange={event=>changeYear(Number(event.target.value))}>{years.map(value=><option key={value}>{value}</option>)}</select></label><label>To<select aria-label="Report to year" value={year} disabled={disabled} onChange={event=>changeYear(Number(event.target.value))}>{years.map(value=><option key={value}>{value}</option>)}</select></label>
          <label>Y-Axis<input value="Maker" readOnly /></label><label>X-Axis<input value="Month Wise" readOnly /></label>
        </div>
        <p className="profile-help">Maker reports use one calendar year: changing From or To updates both. SQL import currently supports Calendar Year / Maker / Month Wise.</p>
        {definition.fields.states.mode==='iterate'&&<label className="profile-rto-options-state">RTO options for State<select value={optionsState} disabled={disabled||loading}
          onChange={event=>setOptionsState(event.target.value)}><option value="">Choose a State to browse RTO limits</option>{(options.states||[]).map(state=><option key={state}>{state}</option>)}</select><small>This only changes the options shown below; State iteration stays enabled.</small></label>}
        <p className="profile-help">Fixed keeps selected values together. Iterate creates a case per value, using Include/Exclude limits. State and RTO always run one office per case. Changing a parent clears dependent selections.</p>
        {busy&&<p className="profile-help">You can save profile edits now. Stop the active crawl before loading live options or previewing combinations.</p>}
        <div className="profile-options-status" data-error={Boolean(error)} role={error?'alert':'status'}>{error|| (loading?'Loading live VAHAN options for the selected parent filters…':options.states?.length?'Live options loaded':'')}</div>
        <div className="profile-fields">{PROFILE_FIELDS.map(field=>{
          const policy=definition.fields[field.id];const scalar='scalar' in field&&field.scalar;
          return <div className="profile-field-row" key={field.id}><div><strong>{field.label}</strong>
            {'parents' in field&&<small>Depends on {field.parents.map(parent=>PROFILE_FIELDS.find(item=>item.id===parent)?.label).join(' + ')}</small>}</div>
            <div className="profile-field-values" data-mode="single"><ValuePicker label={field.label} options={options[field.id]||[]} values={policy.values} one={scalar} required={['states','rtos','delhiNcr','archivedFlags'].includes(field.id)}
              policy={policy} onPolicy={patch=>changeField(field.id,patch)} disabled={disabled||loading} onChange={values=>changeField(field.id,{values})} onSearch={field.id==='makers'?searchMakers:undefined} /></div></div>;
        })}</div>
        <div className="profile-rules"><span>Combination rules · {definition.rules.length}</span><button type="button" onClick={()=>setRulesOpen(true)}>Edit rules</button></div>
        {createPortal(<dialog ref={rulesDialog} className="profile-picker-dialog profile-rules-dialog" aria-label="Combination rules"
          onCancel={event=>{if(event.target===event.currentTarget){event.preventDefault();setRulesOpen(false);}}} onClose={event=>{if(event.target===event.currentTarget)setRulesOpen(false);}}>
          <div className="profile-picker-header"><div><h3>Combination rules</h3><p>Require or exclude values when another selected value matches.</p></div><button type="button" className="profile-picker-close" aria-label="Close rules" onClick={()=>setRulesOpen(false)}>×</button></div>
          <div className="profile-rules-body">
          {definition.rules.map((rule,index)=><div className="profile-rule" key={index}>
            <label>If<select value={rule.whenField} disabled={disabled} onChange={event=>setRule(index,{whenField:event.target.value as ProfileField,whenValues:[]})}>{PROFILE_FIELDS.map(field=><option key={field.id} value={field.id}>{field.label}</option>)}</select></label>
            <ValuePicker label="If values" values={rule.whenValues} options={options[rule.whenField]||[]} disabled={disabled} onChange={whenValues=>setRule(index,{whenValues})} />
            <label>Then<select value={rule.action} disabled={disabled} onChange={event=>setRule(index,{action:event.target.value as CombinationRule['action']})}><option value="require">Require one of</option><option value="exclude">Exclude</option></select></label>
            <label>Field<select value={rule.targetField} disabled={disabled} onChange={event=>setRule(index,{targetField:event.target.value as ProfileField,targetValues:[]})}>{PROFILE_FIELDS.filter(field=>field.id!==rule.whenField).map(field=><option key={field.id} value={field.id}>{field.label}</option>)}</select></label>
            <ValuePicker label="Target values" values={rule.targetValues} options={options[rule.targetField]||[]} disabled={disabled} onChange={targetValues=>setRule(index,{targetValues})} />
            <button type="button" disabled={disabled} onClick={()=>{setPreview(null);setDefinition(current=>({...current,rules:current.rules.filter((_,position)=>position!==index)}));}}>Remove</button>
          </div>)}
          {!definition.rules.length&&<p>No combination rules. Add a rule to restrict specific combinations.</p>}
          </div><div className="profile-picker-footer"><span>{definition.rules.length} rules</span>
          <button type="button" disabled={disabled||definition.rules.length>=30} onClick={()=>setDefinition(current=>({...current,rules:[...current.rules,{whenField:'fuels',whenValues:[],targetField:'evTypes',targetValues:[],action:'exclude'}]}))}>Add rule</button>
          <button type="button" className="profile-picker-done" onClick={()=>setRulesOpen(false)}>Done</button></div>
        </dialog>,document.body)}
        <div className="profile-save-bar"><label>Maximum cases<input type="number" min={1} max={3000} value={definition.maxCases} disabled={disabled}
          onChange={event=>{setPreview(null);setDefinition(current=>({...current,maxCases:Number(event.target.value)}));}} /></label>
          <button type="button" disabled={disabled} onClick={()=>void save()}>Save to SQL</button>
          <button type="button" disabled={disabled||busy||loading||!runnerId} onClick={()=>void save(true)}>Save &amp; preview</button>
          {working&&previewAbort.current&&<button type="button" onClick={()=>previewAbort.current?.abort()}>Cancel preview</button>}
          {id&&<button type="button" className="profile-delete" disabled={disabled} onClick={async()=>{
            if(!window.confirm(`Delete the saved profile “${name}”? Existing run results remain in SQL.`))return;
            setWorking(true);setError('');try{await api.deleteFilterProfile(id,revision!);edit();await onSaved();}catch(reason){setError(reason instanceof Error?reason.message:'Delete failed.');}finally{setWorking(false);}
          }}>Delete</button>}
        </div>
        {message&&<p className="profile-message" role="status">{message}</p>}
        {preview&&<section className="profile-preview"><div><h3>{preview.scenarios.length.toLocaleString()} cases · {preview.states.length} States</h3><button type="button" disabled={disabled||busy} onClick={()=>onSelect(id,preview)}>Use on home page</button></div>
          <p>Preview only. Starting a run rechecks the saved profile and live VAHAN options.</p>
          <ol>{preview.scenarios.slice(0,10).map((scenario,index)=><li key={scenario.caseKey}>{index+1}. {scenario.filters.states[0]} · {scenario.filters.rtos[0]}<small>{PROFILE_FIELDS.filter(field=>!['states','rtos','delhiNcr'].includes(field.id)).flatMap(field=>{
            const values=scenario.filters[field.id as keyof typeof scenario.filters];return Array.isArray(values)&&values.length?[`${field.label}: ${values.join(', ')}`]:[];
          }).join(' · ')}</small></li>)}</ol>
          {preview.scenarios.length>10&&<p>Showing the first 10 cases.</p>}</section>}
      </section>
    </div>
  </main>;
}
