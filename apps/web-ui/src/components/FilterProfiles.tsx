import {useEffect, useId, useLayoutEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import type {Runner} from '../contracts';
import {currentReportYear, MIN_REPORT_YEAR, type MatrixPlan} from '../matrix-plan';
import {api} from '../services/api-client';
import {cachedFilterOptions,saveFilterOptions} from '../filter-options-cache';
import {defaultProfile, parentContext, previewFilterProfile, PROFILE_FIELDS,
  type FilterProfile, type FilterPolicy, type ProfileDefinition, type ProfileField, type ProfileOptions, type CombinationRule} from '../filter-profiles';

function isWorkerWaiting(reason:unknown):boolean {
  if(!(reason instanceof Error))return false;
  try {
    const detail=JSON.parse(reason.message) as {code?:string};
    return ['PREFLIGHT_WAITING','WORKER_BUSY','WORKER_OFFLINE','WORKER_RESERVATION_EXPIRED'].includes(detail.code||'');
  } catch { return false; }
}

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
  const popover=useRef<HTMLDivElement>(null),trigger=useRef<HTMLButtonElement>(null),searchInput=useRef<HTMLInputElement>(null);
  const dialogId=useId();
  const [portalHost,setPortalHost]=useState<HTMLElement>(()=>document.body);
  useLayoutEffect(()=>{setPortalHost(trigger.current?.closest('dialog')||document.body);},[]);
  const [position,setPosition]=useState({left:0,top:0,width:320,height:460});
  const selected=policy?.mode==='iterate'?(editingExcluded?policy.exclude:policy.include):values;
  const visible=[...new Set([...options,...selected])].filter(value=>value.toLowerCase().includes(search.toLowerCase()));
  function place(ensureSpace=false){
    const button=trigger.current;if(!button)return;
    let rect=button.getBoundingClientRect();
    if(ensureSpace&&window.innerHeight-rect.bottom<280){button.scrollIntoView({block:'center',behavior:'instant'});rect=button.getBoundingClientRect();}
    const width=Math.min(rect.width,window.innerWidth-24);
    const next={left:Math.max(12,Math.min(rect.left,window.innerWidth-width-12)),top:rect.bottom+6,width,
      height:Math.min(430,(policy?270:200)+(policy?.mode==='iterate'?40:0)+(onSearch?38:0)+(label==='Active / Archive Type'?38:0)+Math.min(Math.max(visible.length,1),5)*30,Math.max(160,window.innerHeight-rect.bottom-18))};
    setPosition(current=>Object.keys(next).every(key=>next[key as keyof typeof next]===current[key as keyof typeof current])?current:next);
  }
  function close(){popover.current?.hidePopover();trigger.current?.focus({preventScroll:true});}
  useEffect(()=>{
    if(!open)return;
    place();
    const update=()=>place();
    const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'&&popover.current?.matches(':popover-open')){event.preventDefault();event.stopPropagation();close();}};
    const outside=(event:PointerEvent)=>{if(popover.current?.matches(':popover-open')&&!popover.current.contains(event.target as Node)&&!trigger.current?.contains(event.target as Node))popover.current.hidePopover();};
    document.addEventListener('keydown',escape,true);document.addEventListener('pointerdown',outside,true);
    window.addEventListener('resize',update);window.addEventListener('scroll',update,true);
    return()=>{document.removeEventListener('keydown',escape,true);document.removeEventListener('pointerdown',outside,true);window.removeEventListener('resize',update);window.removeEventListener('scroll',update,true);};
  },[open,visible.length,policy?.mode]);
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
    <button type="button" ref={trigger} className="profile-picker-trigger" disabled={disabled} aria-label={policy?label:undefined} aria-haspopup="dialog" aria-expanded={open} aria-controls={dialogId}
      title={label} popoverTarget={dialogId} onClick={()=>place(true)}><span>{policy?summary:label}</span>{!policy&&<strong>{summary}</strong>}<i aria-hidden="true">⌄</i></button>
    <div className="profile-selected-values" title={displayed.join(', ')}>{displayed.map(value=>archiveLabels[value]||value).join(', ')}{policy?.mode==='iterate'&&policy.exclude.length?`${displayed.length?' · ':''}${policy.exclude.length} excluded`:''}</div>
    {createPortal(<div ref={popover} id={dialogId} popover="auto" role="dialog" className="profile-picker-dialog profile-value-popover" aria-label={label}
      style={{left:position.left,top:position.top,width:position.width,height:position.height}}
      onToggle={event=>{const expanded=event.currentTarget.matches(':popover-open');setOpen(expanded);
        if(expanded){setEditingExcluded(false);setSearch('');setError('');place(true);searchInput.current?.focus({preventScroll:true});}}}>
      <div className="profile-picker-header"><div><h3>{label}</h3><p>{summary} · {policy?.mode==='iterate'?'One case per valid value':one?'Choose one value':'Choose the values to use'}</p></div>
        <button type="button" className="profile-picker-close" aria-label="Close value picker" onClick={close}>×</button></div>
      <div className="profile-picker-top-actions"><button type="button" disabled={disabled||!selected.length} onClick={()=>selectValues([])}>Clear selection</button><button type="button" className="profile-picker-done" onClick={close}>Done</button></div>
      <div className="profile-picker-body">
        {policy&&<label className="profile-dialog-mode">Mode<select aria-label={`${label} mode`} value={policy.mode} disabled={disabled}
          onChange={event=>{setEditingExcluded(false);onPolicy?.({mode:event.target.value as FilterPolicy['mode']});}}><option value="fixed">Fixed values</option><option value="iterate">Iterate all</option></select></label>}
        {policy?.mode==='iterate'&&<div className="profile-iteration-tools"><p>{editingExcluded?'Checked values will be excluded.':'Select values to limit iteration, or leave empty to use all valid values.'}</p>
          <button type="button" aria-pressed={editingExcluded} onClick={()=>setEditingExcluded(value=>!value)}>{editingExcluded?'Back to values':`Exclusions (${policy.exclude.length})`}</button></div>}
        <input ref={searchInput} type="search" aria-label={`Search ${label}`} value={search} placeholder="Search values"
          disabled={disabled} onChange={event=>setSearch(event.target.value)} />
        {onSearch&&<button type="button" disabled={disabled||searching||!search.trim()} onClick={async()=>{
          setSearching(true);setError('');try{await onSearch(search.trim());}catch(reason){setError(reason instanceof Error?reason.message:'Search failed.');}finally{setSearching(false);}
        }}>{searching?'Searching…':'Search VAHAN'}</button>}
        {error&&<p role="alert">{error}</p>}
        <div className="profile-picker-options">{visible.length?label==='Active / Archive Type'
          ?<>{['Active Type','Archive Type'].map(group=><section className="profile-archive-group" key={group}><h4>{group}</h4>{visible.filter(value=>group==='Active Type'?value.startsWith('ACTIVE_'):!value.startsWith('ACTIVE_')).map(renderOption)}</section>)}</>
          :visible.map(renderOption):<p>Load options or choose a parent filter first.</p>}</div>
      </div>
      <div className="profile-picker-footer"><span>{visible.length} matching values</span></div>
    </div>,portalHost)}
  </div>;
}

export function FilterProfiles({profiles,runners,busy,knownPlan=null,onSaved,onSelect}: {
  profiles:FilterProfile[];runners:Runner[];busy:boolean;knownPlan?:MatrixPlan|null;
  onSaved:()=>Promise<void>;onSelect:(id:string,plan:MatrixPlan)=>void;
}) {
  const [id,setId]=useState(''),[name,setName]=useState(''),[revision,setRevision]=useState<number>();
  const [definition,setDefinition]=useState<ProfileDefinition>(()=>defaultProfile());
  const year=definition.report?.year??currentReportYear();
  const years=Array.from({length:currentReportYear()-MIN_REPORT_YEAR+1},(_,index)=>currentReportYear()-index);
  function changeYear(value:number){setDefinition(current=>({...current,report:{year:value,period:'CALENDAR YEAR',yAxis:'Maker',xAxis:'Month Wise'}}));setPreview(null);setMessage('');}
  const [options,setOptions]=useState<ProfileOptions>(()=>cachedFilterOptions(year,parentContext(definition),knownPlan));
  const [runnerId,setRunnerId]=useState('');
  const [working,setWorking]=useState(false),[loading,setLoading]=useState(false);
  const [error,setError]=useState(''),[message,setMessage]=useState('');
  const [preview,setPreview]=useState<MatrixPlan|null>(null);
  const [refresh,setRefresh]=useState(0);
  const [retrySequence,setRetrySequence]=useState(0);
  const [rulesOpen,setRulesOpen]=useState(false);
  const rulesDialog=useRef<HTMLDialogElement>(null);
  useEffect(()=>{
    if(rulesOpen&&!rulesDialog.current?.open)rulesDialog.current?.showModal();
    if(!rulesOpen&&rulesDialog.current?.open)rulesDialog.current.close();
  },[rulesOpen]);
  const mounted=useRef(true),optionsPending=useRef(false),wantedContext=useRef(''),loadedContext=useRef('');
  const retryTimer=useRef<number|undefined>(undefined),optionsAllowed=useRef(false);
  const optionsPreflight=useRef<{runner:string;at:number}|null>(null);
  const previewAbort=useRef<AbortController|null>(null);
  const parents=parentContext(definition);
  if(definition.fields.states.mode==='iterate')parents.states=definition.fields.states.include.filter(state=>!definition.fields.states.exclude.includes(state));
  const contextKey=JSON.stringify([runnerId,year,parents,refresh]);
  const runnerAvailable=Boolean(runners.find(runner=>runner.id===runnerId&&runner.status==='ONLINE'&&!runner.currentJobId));
  const optionsWaiting=Boolean(!busy&&runnerAvailable&&!error&&loadedContext.current!==contextKey);
  const disabled=working;
  optionsAllowed.current=Boolean(!busy&&!disabled&&runnerAvailable);

  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;previewAbort.current?.abort();};},[]);
  useEffect(()=>{
    const current=runners.find(item=>item.id===runnerId);
    if(!current||current.status!=='ONLINE'||current.currentJobId){const idle=runners.find(item=>item.source==='new'&&item.status==='ONLINE'&&!item.currentJobId);if(idle&&idle.id!==runnerId)setRunnerId(idle.id);}
  },[runners,runnerId]);
  useEffect(()=>{setOptions(cachedFilterOptions(year,parents,knownPlan));},[contextKey,knownPlan]);
  useEffect(()=>{
    wantedContext.current=contextKey;
    window.clearTimeout(retryTimer.current);
    if(!runnerAvailable||busy||disabled)return;
    const timer=window.setTimeout(async()=>{
      if(optionsPending.current)return;
      optionsPending.current=true;setLoading(true);setError('');
      try {
        while(mounted.current&&optionsAllowed.current&&loadedContext.current!==wantedContext.current){
          const key=wantedContext.current;const [runner,selectedYear,context]=JSON.parse(key);
          if(!optionsPreflight.current||optionsPreflight.current.runner!==runner||Date.now()-optionsPreflight.current.at>240000){
            const checked=await api.uiPreflight([runner]);
            if(!checked.allowed)throw new Error('UI_HEALTH_BLOCKED: open UI Health and copy the diagnostic error.');
            optionsPreflight.current={runner,at:Date.now()};
          }
          if(!optionsAllowed.current)break;
          const loaded=await api.filterOptions(runner,selectedYear,context);
          saveFilterOptions(selectedYear,context,loaded);
          if(mounted.current&&wantedContext.current===key){setOptions(loaded);loadedContext.current=key;}
        }
      }catch(reason){
        if(mounted.current&&isWorkerWaiting(reason)){
          setError('');setMessage('Waiting for an idle worker. Filter options will retry automatically.');
          retryTimer.current=window.setTimeout(()=>{if(mounted.current)setRetrySequence(value=>value+1);},5000);
        }else if(mounted.current)setError(reason instanceof Error?reason.message:'Could not load filter options.');
      }
      finally{optionsPending.current=false;if(mounted.current)setLoading(false);}
    },450);
    return()=>{window.clearTimeout(timer);window.clearTimeout(retryTimer.current);};
  },[contextKey,runnerId,runnerAvailable,disabled,busy,retrySequence]);

  function changeField(field:ProfileField,patch:Partial<FilterPolicy>){
    setPreview(null);setMessage('');
    setDefinition(current=>{
      const fields={...current.fields,[field]:{...current.fields[field],...patch}};
      if(patch.values||patch.mode||patch.include||patch.exclude){
        const children:Partial<Record<ProfileField,ProfileField[]>>={delhiNcr:['states','rtos'],states:['rtos'],categoryGroups:['subCategories','classes'],subCategories:['classes'],evTypes:['fuels']};
        for(const child of children[field]||[])fields[child]={...fields[child],values:[],include:[],exclude:[]};
      }
      return {...current,fields};
    });
  }
  function edit(profile?:FilterProfile){setId(profile?.id||'');setName(profile?.name||'');setRevision(profile?.revision);
    setDefinition(profile?{...structuredClone(profile.definition),report:profile.definition.report??{year:currentReportYear(),period:'CALENDAR YEAR',yAxis:'Maker',xAxis:'Month Wise'}}:defaultProfile());setPreview(null);setError('');setMessage('');}
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
        await api.uiPreflight([runnerId]);
        const plan=await previewFilterProfile(saved.id,runnerId,year,setMessage,controller.signal);
        if(mounted.current){setPreview(plan);setMessage(`${plan.scenarios.length.toLocaleString()} valid cases · ${plan.skippedBranches||0} branches excluded by dependencies or rules`);}
      }
    }catch(reason){if(mounted.current)setError(reason instanceof Error?reason.message:'Could not save filters.');}
    finally{if(mounted.current)setWorking(false);previewAbort.current=null;}
  }
  const searchMakers=async(search:string)=>{
    if(busy)throw new Error('Maker search is paused while a report run is active. It will be available when the run is idle.');
    if(!runnerId)throw new Error('Select a browser worker.');
    await api.uiPreflight([runnerId]);
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
          <button type="button" disabled={disabled||loading||!runnerAvailable} onClick={()=>setRefresh(value=>value+1)}>Refresh options</button></div>
        <div className="profile-report-context" aria-label="Report settings">
          <label>Year Type<input value="CALENDAR YEAR" readOnly /></label><label>From<select aria-label="Report from year" value={year} disabled={disabled} onChange={event=>changeYear(Number(event.target.value))}>{years.map(value=><option key={value}>{value}</option>)}</select></label><label>To<select aria-label="Report to year" value={year} disabled={disabled} onChange={event=>changeYear(Number(event.target.value))}>{years.map(value=><option key={value}>{value}</option>)}</select></label>
          <label>Y-Axis<input value="Maker" readOnly /></label><label>X-Axis<input value="Month Wise" readOnly /></label>
        </div>
        <div className="profile-options-status" data-error={Boolean(error)} role={error?'alert':'status'}>{error|| (busy?'Live option refresh waits until the report run is idle.':loading||optionsWaiting?'Loading live VAHAN options for the selected parent filters…':options.states?.length?(loadedContext.current===contextKey?'Live options loaded':'Saved options ready'):!runnerAvailable?'Waiting for an idle worker to load options.':'')}</div>
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
        <div className="profile-fields">{PROFILE_FIELDS.map(field=>{
          const policy=definition.fields[field.id];const scalar='scalar' in field&&field.scalar;
          return <div className="profile-field-row" key={field.id}><div><strong>{field.label}</strong>
            {'parents' in field&&<small>Depends on {field.parents.map(parent=>PROFILE_FIELDS.find(item=>item.id===parent)?.label).join(' + ')}</small>}</div>
            <div className="profile-field-values" data-mode="single"><ValuePicker label={field.label} options={options[field.id]||[]} values={policy.values} one={scalar} required={['states','rtos','delhiNcr','archivedFlags'].includes(field.id)}
              policy={policy} onPolicy={patch=>changeField(field.id,patch)} disabled={disabled||((loading||optionsWaiting)&&!(options[field.id]?.length))} onChange={values=>changeField(field.id,{values})} onSearch={field.id==='makers'?searchMakers:undefined} /></div></div>;
        })}</div>
        {message&&<p className="profile-message" role="status">{message}</p>}
        {preview&&<section className="profile-preview"><div><h3>{preview.scenarios.length.toLocaleString()} cases · {preview.states.length} States</h3><button type="button" disabled={disabled||busy} onClick={()=>onSelect(id,preview)}>Use in Settings</button></div>
          <p>Preview only. Starting a run rechecks the saved profile and live VAHAN options.</p>
          <ol>{preview.scenarios.slice(0,10).map((scenario,index)=><li key={scenario.caseKey}>{index+1}. {scenario.filters.states[0]} · {scenario.filters.rtos[0]}<small>{PROFILE_FIELDS.filter(field=>!['states','rtos','delhiNcr'].includes(field.id)).flatMap(field=>{
            const values=scenario.filters[field.id as keyof typeof scenario.filters];return Array.isArray(values)&&values.length?[`${field.label}: ${values.join(', ')}`]:[];
          }).join(' · ')}</small></li>)}</ol>
          {preview.scenarios.length>10&&<p>Showing the first 10 cases.</p>}</section>}
      </section>
    </div>
  </main>;
}
