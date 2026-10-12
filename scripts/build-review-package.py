#!/usr/bin/env python3
"""Package a committed source tree and optionally its four offline Docker images."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATHS = ['README.md', 'compose.yaml', '.dockerignore', '.gitignore',
         'run-vahan-rpa.ps1', 'run-vahan-rpa.sh', 'backup-vahan-rpa.ps1',
         'apps', 'docker', 'docs', 'scripts', 'tools', 'test-scenarios-filter.json']


def digest(path: Path) -> str:
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', default='HEAD', help='Committed Git ref; local dirty files are excluded.')
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--with-images', action='store_true', help='Build and save all images for offline installation.')
    args = parser.parse_args()
    sha = subprocess.check_output(['git', 'rev-parse', f'{args.ref}^{{commit}}'], cwd=ROOT, text=True).strip()
    destination = Path(args.output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    source = destination / f'vahan-{sha[:12]}-source.zip'
    images = destination / f'vahan-{sha[:12]}-images.tar'
    manifest_path = destination / f'vahan-{sha[:12]}-manifest.json'
    if any(path.exists() for path in (source, images, manifest_path)):
        raise SystemExit('Destination artifacts already exist. Use a new output directory; nothing was overwritten.')
    subprocess.run(['git', 'archive', '--format=zip', '-o', str(source), sha, *PATHS], cwd=ROOT, check=True)
    namespace, tag = 'vahan-review', sha[:12]
    manifest = {'format': 1, 'sourceCommit': sha, 'imageNamespace': namespace, 'imageTag': tag,
                'files': {source.name: digest(source)}, 'imageIds': {},
                'scope': 'Committed source only; outputs, secrets, local CA, backups and Git metadata are excluded.'}
    if args.with_images:
        with tempfile.TemporaryDirectory(prefix='vahan-package-build-') as temporary:
            build_root = Path(temporary)
            with zipfile.ZipFile(source) as archive:
                archive.extractall(build_root)
            # CA files are operator-specific and are never redistributed in a package.
            # Build uses the committed cert directory, even when empty.
            subprocess.run([os.sys.executable, 'scripts/setup-docker.py'], cwd=build_root, check=True)
            env = {**os.environ, 'VAHAN_IMAGE_NAMESPACE': namespace, 'VAHAN_IMAGE_TAG': tag}
            subprocess.run(['docker', 'compose', '--env-file', '.docker.env', 'build',
                            '--sbom=true', '--provenance=mode=max'], cwd=build_root, env=env, check=True)
            refs = [f'{namespace}/{service}:{tag}' for service in ('postgres', 'api', 'web', 'runner')]
            for ref in refs:
                manifest['imageIds'][ref] = subprocess.check_output(
                    ['docker', 'image', 'inspect', '--format', '{{.Id}}', ref], text=True).strip()
            subprocess.run(['docker', 'image', 'save', '-o', str(images), *refs], check=True)
            manifest['files'][images.name] = digest(images)
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'sourceCommit': sha, 'manifest': str(manifest_path), 'files': manifest['files']}, indent=2))


if __name__ == '__main__':
    main()
