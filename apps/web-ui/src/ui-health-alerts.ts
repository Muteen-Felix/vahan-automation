type Evidence = Record<string, unknown>;

export interface WebsiteCheckAlert {
  id: string;
  code: string;
  title: string;
  target: string;
  selector: string;
  expected: unknown;
  actual: unknown;
  checkedAt: string;
  workers: string[];
  checks: Evidence[];
}

function record(value: unknown): Evidence {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Evidence : {};
}
function value(value: unknown): string {return typeof value === 'string' ? value : '';}
function stable(value: unknown): string {
  if (Array.isArray(value)) return '[' + value.map(stable).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.entries(value).sort(([a],[b])=>a.localeCompare(b)).map(([key,item])=>JSON.stringify(key)+':'+stable(item)).join(',') + '}';
  return JSON.stringify(value) ?? 'null';
}

export function websiteCheckBlocked(status: Evidence): boolean {
  return Boolean(status.blocked || record(status.latestPreflight).status === 'BLOCKED');
}

// Only unresolved failures appear here. Successful automatic repairs remain in SQL history.
export function websiteCheckAlerts(status: Evidence): WebsiteCheckAlert[] {
  if (!websiteCheckBlocked(status)) return [];
  const groups = new Map<string, WebsiteCheckAlert>();
  const add = (input: unknown, fallbackTime = '', preflightId = '') => {
    const check = record(input);
    if (check.allowed === true) return;
    let reports = Array.isArray(check.reports) ? check.reports.map(record) : [];
    const pageError = reports.find(report => report.code === 'CHECK_ERROR');
    if (check.status === 'CHECK_ERROR' && pageError) reports = [pageError];
    for (const report of reports) {
      const code = value(report.code) || 'UI_HEALTH_BLOCKED';
      const title = value(report.title) || 'The website check could not pass.';
      const target = value(report.target);
      const selector = value(report.selector);
      const key = stable([code,title,target,selector,report.expected,report.actual]);
      let alert = groups.get(key);
      if (!alert) {
        alert = {id:key,code,title,target,selector,expected:report.expected,actual:report.actual,checkedAt:'',workers:[],checks:[]};
        groups.set(key,alert);
      }
      const worker = value(check.runnerId);
      const checkedAt = value(check.checkedAt) || fallbackTime;
      if (worker && !alert.workers.includes(worker)) alert.workers.push(worker);
      if (Number.isFinite(Date.parse(checkedAt)) && (!Number.isFinite(Date.parse(alert.checkedAt)) || Date.parse(checkedAt) > Date.parse(alert.checkedAt))) alert.checkedAt = checkedAt;
      const proof = {runnerId:worker,checkId:check.checkId,checkedAt,preflightId,attempts:check.attempts,status:check.status,versionId:check.versionId,revision:check.revision};
      const previous = alert.checks.find(item=>item.runnerId===worker && (check.checkId ? item.checkId===check.checkId : item.checkedAt===checkedAt));
      if (previous) Object.assign(previous,{...proof,preflightId:preflightId || previous.preflightId,attempts:check.attempts ?? previous.attempts});
      else alert.checks.push(proof);
    }
  };
  if (status.blocked) {
    Object.values(record(status.runnerErrors)).forEach(check=>add(check));
    add(status.lastCheck);
  }
  const preflight = record(status.latestPreflight);
  if (preflight.status === 'BLOCKED' && Array.isArray(preflight.reports)) {
    preflight.reports.forEach(check=>add(check,value(preflight.created_at),value(preflight.id)));
  }
  if (!groups.size) {
    add({reports:[{code:'UI_HEALTH_BLOCKED',title:value(status.lastError)||'The website check could not confirm that the run can continue.'}]});
  }
  return [...groups.values()].sort((a,b)=>a.target.localeCompare(b.target)||a.code.localeCompare(b.code));
}

export function websiteCheckReport(status: Evidence, alerts: WebsiteCheckAlert[]): string {
  const preflight=record(status.latestPreflight);
  return JSON.stringify({
    title:'VAHAN website check — run blocked',
    pageUrl:'https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en',
    revision:status.revision,versionId:status.versionId,
    preflight:{id:preflight.id,status:preflight.status,createdAt:preflight.created_at,runnerIds:preflight.runner_ids,versionId:preflight.version_id},
    alerts:alerts.map(({id,...alert})=>alert),
  },null,2);
}

export function websiteTargetLabel(target: string): string {
  const labels: Record<string,string> = {makers:'Maker',states:'State',rtos:'RTO',apply:'Apply',categoryGroups:'Category group',subCategories:'Sub-category',classes:'Vehicle class',fuels:'Fuel',yAxis:'Y-Axis',xAxis:'X-Axis'};
  return labels[target] || target || 'Public Report page';
}
