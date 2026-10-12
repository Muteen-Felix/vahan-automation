// Read real run snapshots on stdin; use the same ETA functions as the UI.
import {readFileSync} from 'node:fs';
import {createInterface} from 'node:readline';
import ts from 'typescript';

function moduleUrl(file, dependencies = {}) {
  let source = readFileSync(new URL(file, import.meta.url), 'utf8');
  for (const [name, url] of Object.entries(dependencies)) source = source.replace(`'${name}'`, `'${url}'`);
  return `data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,
    {compilerOptions: {module: ts.ModuleKind.ESNext}}).outputText).toString('base64')}`;
}
const {observeScheduleTiming, estimateScheduleTiming} = await import(moduleUrl('../src/schedule-timing.ts', {
  './batch-timing': moduleUrl('../src/batch-timing.ts'),
}));
let observation = null;
for await (const line of createInterface({input: process.stdin})) {
  const {schedule, now} = JSON.parse(line);
  observation = observeScheduleTiming(observation, schedule, now);
  process.stdout.write(JSON.stringify(estimateScheduleTiming(schedule, observation, now)) + '\n');
}
