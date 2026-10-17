#!/usr/bin/env python3
"""Compare API/runner production locks with immutable, already-loaded release images.

Requires Python packaging. Does not build, pull, start services, or modify a manifest.
The web image contains compiled assets, so its build dependencies are outside this check.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


API_PROBE = '''import hashlib, importlib.metadata as m, json, platform, sys
print(json.dumps({"packages": {d.metadata["Name"]: d.version for d in m.distributions()},
 "lockSha256": hashlib.sha256(open("/app/requirements.lock", "rb").read()).hexdigest(),
 "environment": {"sys_platform": sys.platform, "platform_system": platform.system(),
 "platform_machine": platform.machine(), "platform_python_implementation": platform.python_implementation(),
 "python_version": platform.python_version_tuple()[0]+"."+platform.python_version_tuple()[1],
 "python_full_version": platform.python_version(), "implementation_name": sys.implementation.name,
 "implementation_version": platform.python_version(), "os_name": "posix", "extra": ""}}))'''

RUNNER_PROBE = '''const fs=require('fs'), path=require('path'), crypto=require('crypto');
const packages={};
function walk(dir) {
 if (!fs.existsSync(dir)) return;
 for (const entry of fs.readdirSync(dir)) {
  if (entry.startsWith('.')) continue;
  const p=path.join(dir,entry);
  if (entry.startsWith('@')) { walk(p); continue; }
  const file=path.join(p,'package.json');
  if (fs.existsSync(file)) packages[p.replace('/app/','')]=JSON.parse(fs.readFileSync(file)).version;
  walk(path.join(p,'node_modules'));
 }
}
walk('/app/node_modules');
console.log(JSON.stringify({packages, platform:process.platform, arch:process.arch,
 lockSha256:crypto.createHash('sha256').update(fs.readFileSync('/app/package-lock.json')).digest('hex')}));'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def python_lock(text, environment):
    expected = {}
    # pip-compile emits one requirement at the start of each logical line.
    for line in text.splitlines():
        if not line or line[0].isspace() or line.startswith('#'):
            continue
        req = Requirement(line.rstrip().removesuffix('\\').strip())
        pins = list(req.specifier)
        if len(pins) != 1 or pins[0].operator != '==' or '*' in pins[0].version:
            raise ValueError('Every production requirement must have an exact version')
        if req.marker is None or req.marker.evaluate(environment):
            expected[canonicalize_name(req.name)] = pins[0].version
    if not expected:
        raise ValueError('Empty production lock')
    return expected


def package_diff(expected, actual, allowed_extra=()):
    return ([{'package': name, 'expected': version, 'actual': actual.get(name)}
             for name, version in sorted(expected.items()) if actual.get(name) != version]
            + [{'package': name, 'expected': None, 'actual': actual[name]}
               for name in sorted(actual.keys() - expected.keys() - set(allowed_extra))])


def node_lock(lock, platform, arch):
    def accepts(values, value):
        if not values:
            return True
        positives = [v for v in values if not v.startswith('!')]
        return '!' + value not in values and (not positives or value in positives or 'any' in positives)
    expected = {}
    for name, body in lock['packages'].items():
        if not name or body.get('dev'):
            continue
        if not accepts(body.get('os'), platform) or not accepts(body.get('cpu'), arch):
            if not body.get('optional'):
                raise ValueError('Required npm package incompatible with image platform: ' + name)
            continue
        expected[name] = body['version']
    if not expected:
        raise ValueError('Empty production npm lock')
    return expected


def command(args):
    result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', timeout=120)
    if result.returncode:
        # Commands never carry configuration or credentials. Do not echo container output on failure.
        raise RuntimeError('Command failed: ' + ' '.join(args[:3]) + ' (exit ' + str(result.returncode) + ')')
    return result.stdout


def collect(manifest, source):
    report = {'recordedAt': datetime.now(timezone.utc).isoformat(), 'sha': manifest['sourceCommit'],
              'scope': 'API Python and runner npm production packages; web build dependencies excluded', 'images': {}}
    for service, executable, probe, lock_path in (
        ('api', 'python', API_PROBE, 'apps/api-server/requirements.lock'),
        ('runner', 'node', RUNNER_PROBE, 'apps/browser-runner/package-lock.json'),
    ):
        refs = [ref for ref in manifest['imageIds'] if ref.split(':')[0].endswith('/' + service)]
        if len(refs) != 1:
            raise ValueError('Manifest must identify exactly one ' + service + ' image')
        ref = refs[0]
        image_id = manifest['imageIds'][ref]
        info = json.loads(command(['docker', 'image', 'inspect', image_id]))[0]
        if info['Id'] != image_id or info['Config'].get('Labels', {}).get('org.opencontainers.image.revision') != manifest['sourceCommit']:
            raise ValueError('Image identity/revision mismatch: ' + service)
        raw = command(['docker', 'run', '--rm', '--pull=never', '--network=none', '--read-only',
                       '--cap-drop=ALL', '--security-opt=no-new-privileges', '--entrypoint', executable,
                       image_id, '-c' if service == 'api' else '-e', probe])
        inventory = json.loads(raw)
        lock = source / lock_path
        if service == 'api':
            expected = python_lock(lock.read_text(encoding='utf-8'), inventory['environment'])
            actual = {canonicalize_name(k): v for k, v in inventory['packages'].items()}
        else:
            expected = node_lock(json.loads(lock.read_text(encoding='utf-8')), inventory['platform'], inventory['arch'])
            actual = inventory['packages']
        differences = package_diff(expected, actual)
        lock_matches = digest(lock) == inventory['lockSha256']
        report['images'][service] = {'imageId': image_id, 'lock': lock_path, 'lockSha256': digest(lock),
            'embeddedLockSha256': inventory['lockSha256'], 'embeddedLockMatches': lock_matches,
            'expectedCount': len(expected), 'actualCount': len(actual), 'differences': differences,
            'inventory': inventory, 'status': 'PASS' if lock_matches and not differences else 'FAIL'}
    report['status'] = 'PASS' if all(i['status'] == 'PASS' for i in report['images'].values()) else 'FAIL'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, required=True, help='Source extracted from the exact reviewed package')
    parser.add_argument('--expected-sha', required=True)
    parser.add_argument('--expected-manifest-digest', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = {'recordedAt': datetime.now(timezone.utc).isoformat(), 'sha': args.expected_sha,
              'manifestDigest': args.expected_manifest_digest, 'status': 'NOT_RUN'}
    try:
        manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
        if not re.fullmatch('[a-f0-9]{40}', args.expected_sha) or manifest['sourceCommit'] != args.expected_sha:
            raise ValueError('Source SHA mismatch')
        if digest(args.manifest) != args.expected_manifest_digest:
            raise ValueError('Manifest digest mismatch')
        report = collect(manifest, args.source_root)
        report['manifestDigest'] = args.expected_manifest_digest
        code = 0 if report['status'] == 'PASS' else 1
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        report['blocker'] = str(error)
        code = 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(report['status'] + ': ' + str(args.out))
    return code


if __name__ == '__main__':
    sys.exit(main())
