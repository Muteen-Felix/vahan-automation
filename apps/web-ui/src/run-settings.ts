import {persistentState} from './services/persistent-state';
import {currentReportYear, isReportYear} from './matrix-plan';
import {TARGET_WORKER_COUNT} from './worker-settings';

export const RUN_SETTINGS_STORAGE_KEY = 'vahanRunSettingsV1';
export type RunSettings = {year: number; workerCount: number};
export function readRunSettings(year = currentReportYear(), workerCount = TARGET_WORKER_COUNT): RunSettings {
  let saved: Partial<RunSettings> = {};
  try {saved = JSON.parse(persistentState.getItem(RUN_SETTINGS_STORAGE_KEY) || '{}');} catch { /* Use saved run defaults. */ }
  return {year: isReportYear(saved?.year!) ? saved.year! : isReportYear(year) ? year : currentReportYear(),
    workerCount: Number.isInteger(saved?.workerCount) && saved.workerCount! >= 1 && saved.workerCount! <= TARGET_WORKER_COUNT
      ? saved.workerCount! : workerCount};
}
