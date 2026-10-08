import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {dirname, resolve} from 'node:path';

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const baseUrl = 'http://127.0.0.1:5184';
const npmPackageVite = resolve(webRoot, 'node_modules/vite/bin/vite.js');
const testFiles = [
  'scripts/test-batch-timing.mjs',
  'scripts/test-schedule-timing.mjs',
  'scripts/test-session-ui.mjs',
  'scripts/test-annual-reports.mjs',
  'scripts/test-filter-profiles-ui.mjs',
  'scripts/test-health-page-ui.mjs',
  'scripts/test-navigation-ui.mjs',
  'scripts/test-run-schedules-ui.mjs',
  'scripts/test-update-history-ui.mjs',
];

function runNode(args, env = process.env) {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(process.execPath, args, {cwd: webRoot, env, stdio: 'inherit'});
    child.once('error', reject);
    child.once('close', code => {
      if (code === 0) resolvePromise();
      else reject(new Error(`Command failed with exit code ${code}: ${args.join(' ')}`));
    });
  });
}

async function waitForServer(server) {
  const deadline = Date.now() + 60_000;
  let lastError;
  while (Date.now() < deadline) {
    if (server.exitCode !== null) throw new Error(`Vite exited with code ${server.exitCode}`);
    try {
      const response = await fetch(baseUrl);
      if (response.ok) return;
    } catch (error) {
      lastError = error;
    }
    await new Promise(resolvePromise => setTimeout(resolvePromise, 250));
  }
  throw new Error(`Vite did not become ready at ${baseUrl}: ${lastError ?? 'timeout'}`);
}

const server = spawn(process.execPath, [npmPackageVite, '--host', '127.0.0.1', '--port', '5184', '--strictPort'], {
  cwd: webRoot,
  env: process.env,
  stdio: 'inherit',
});

try {
  await waitForServer(server);
  const env = {
    ...process.env,
    WORKER_UI_URL: `${baseUrl}/#filters`,
    ANNUAL_UI_URL: `${baseUrl}/#reports`,
    HISTORY_UI_URL: `${baseUrl}/#reports`,
    HEALTH_UI_URL: `${baseUrl}/#settings-ui-health`,
    SCHEDULE_UI_URL: `${baseUrl}/#settings`,
    NAV_UI_URL: `${baseUrl}/`,
  };
  for (const file of testFiles) await runNode([file], env);
  console.log('Web UI platform tests passed.');
} finally {
  server.kill();
}
