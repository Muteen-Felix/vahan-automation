#!/usr/bin/env python3
"""Package a committed source tree and optionally its four offline Docker images.

Release path (D-09): the image tag and the OCI ``version`` label are the release version (for example ``1.0.0``) and the
OCI ``revision`` label is the full commit SHA. Package file names keep the 12-character SHA for traceability.

``--seal DIR`` rewrites ``SHA256SUMS`` once every file that belongs to the release directory (evidence, logs) is there.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
DIGEST_REF = re.compile(r'.+@sha256:[0-9a-f]{64}')
SEMVER = re.compile(r'\d+\.\d+\.\d+')
SUMS_NAME = 'SHA256SUMS'
PATHS = ['README.md', 'CHANGELOG.md', 'compose.yaml', '.dockerignore', '.gitignore',
         'run-vahan-rpa.ps1', 'run-vahan-rpa.sh', 'backup-vahan-rpa.ps1',
         'apps', 'docker', 'docs', 'scripts', 'tools', 'test-scenarios-filter.json']
# Every place that carries the product version; they must all agree before anything is built.
VERSION_FILES = {
    'apps/api-server/pyproject.toml': 'toml',
    'apps/web-ui/package.json': 'package',
    'apps/web-ui/package-lock.json': 'lock',
    'apps/browser-runner/package.json': 'package',
    'apps/browser-runner/package-lock.json': 'lock',
}
# Operator-specific or secret material must never be redistributed in a package.
FORBIDDEN_NAMES = {'.env', '.docker.env'}
FORBIDDEN_SUFFIXES = {'.crt', '.pem', '.key', '.p12', '.pfx'}
FORBIDDEN_DIRECTORIES = {'.secrets'}
LABEL_REVISION = 'org.opencontainers.image.revision'
LABEL_VERSION = 'org.opencontainers.image.version'


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def digest(path: Path) -> str:
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def save_offline_images(destination: Path, refs: list[str], pinned: str) -> None:
    """Export PostgreSQL by tag so loading restores its repository identity.

    Saving a digest reference exports unnamed content with the containerd image
    store. Keep the digest-pinned runtime/manifest reference, but save a tag that
    points to the already verified upstream image.
    """
    require(pinned in refs and DIGEST_REF.fullmatch(pinned) is not None,
            'Offline export requires the verified PostgreSQL digest reference.')
    archive_ref = pinned.split('@', 1)[0]
    require(':' in archive_ref.rsplit('/', 1)[-1],
            'The PostgreSQL reference must include a version tag before its digest.')
    subprocess.run(['docker', 'image', 'tag', pinned, archive_ref], check=True)
    save_refs = [archive_ref if ref == pinned else ref for ref in refs]
    subprocess.run(['docker', 'image', 'save', '-o', str(destination), *save_refs], check=True)


def committed_text(sha: str, path: str) -> str:
    return subprocess.check_output(['git', 'show', f'{sha}:{path}'], cwd=ROOT, text=True, encoding='utf-8')


def parse_versions(path: str, kind: str, text: str) -> list[str]:
    if kind == 'toml':
        return [tomllib.loads(text)['project']['version']]
    data = json.loads(text)
    if kind == 'package':
        return [data['version']]
    return [data['version'], data['packages']['']['version']]


def release_version(sha: str) -> str:
    """The single version found in every committed version file; any disagreement stops the build."""
    found: dict[str, list[str]] = {}
    for path, kind in VERSION_FILES.items():
        found[path] = parse_versions(path, kind, committed_text(sha, path))
    values = {value for versions in found.values() for value in versions}
    require(len(values) == 1, f'Version files disagree: {found}')
    version = values.pop()
    require(SEMVER.fullmatch(version) is not None, f'Release version must be MAJOR.MINOR.PATCH, got {version!r}.')
    return version


def forbidden_members(names: list[str]) -> list[str]:
    bad = []
    for name in names:
        parts = PurePosixPath(name).parts
        base = parts[-1] if parts else ''
        if (base in FORBIDDEN_NAMES or PurePosixPath(base).suffix.lower() in FORBIDDEN_SUFFIXES
                or any(part in FORBIDDEN_DIRECTORIES for part in parts)):
            bad.append(name)
    return bad


def check_source_members(names: list[str]) -> None:
    require('CHANGELOG.md' in names, 'The source package must contain CHANGELOG.md.')
    bad = forbidden_members(names)
    require(not bad, f'Secrets or operator CA material would be packaged: {bad[:5]}')


def write_sums(directory: Path, entries: dict[str, str]) -> None:
    lines = ''.join(f'{value}  {name}\n' for name, value in sorted(entries.items()))
    (directory / SUMS_NAME).write_text(lines, encoding='utf-8', newline='\n')


def read_sums(path: Path) -> dict[str, str]:
    listed: dict[str, str] = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        value, separator, name = line.partition('  ')
        require(separator == '  ' and re.fullmatch(r'[0-9a-f]{64}', value) is not None,
                f'Malformed {SUMS_NAME} line: {line!r}')
        listed[name.strip().lstrip('*')] = value
    return listed


def verify_sums(directory: Path, complete: bool = True) -> None:
    """Same rules as evidence-check.py: every listed file matches and, when `complete`, every file is listed."""
    listed = read_sums(directory / SUMS_NAME)
    bad = [name for name, value in listed.items() if not (directory / name).is_file() or digest(directory / name) != value]
    require(not bad, f'{SUMS_NAME} does not match files: {bad}')
    if not complete:
        return
    present = {path.relative_to(directory).as_posix() for path in directory.rglob('*') if path.is_file()} - {SUMS_NAME}
    require(present <= set(listed), f'{SUMS_NAME} does not list: {sorted(present - set(listed))[:5]}')


def seal(directory: Path) -> dict:
    """Rewrite SHA256SUMS over every file after checking that the shipped artifacts were not changed."""
    manifests = list(directory.glob('*-manifest.json'))
    require(len(manifests) == 1, 'Supply a directory containing exactly one package manifest.')
    sums = directory / SUMS_NAME
    require(sums.is_file(), f'{SUMS_NAME} written at build time is required to seal.')
    # The manifest cannot hold its own digest; the build-time SHA256SUMS is the independent record.
    recorded = read_sums(sums).get(manifests[0].name)
    require(recorded is not None, f'{SUMS_NAME} has no entry for {manifests[0].name}.')
    require(recorded == digest(manifests[0]), f'{manifests[0].name} changed after the build.')
    manifest = json.loads(manifests[0].read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        require(Path(name).name == name and (directory / name).is_file(), f'Missing packaged file: {name}')
        require(digest(directory / name) == expected, f'{name} no longer matches manifest.files; the artifact changed.')
    entries = {path.relative_to(directory).as_posix(): digest(path)
               for path in directory.rglob('*') if path.is_file() and path.name != SUMS_NAME}
    write_sums(directory, entries)
    verify_sums(directory)
    return {'sealed': str(directory), 'files': len(entries), 'sourceCommit': manifest.get('sourceCommit'),
            'version': manifest.get('version')}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', default='HEAD', help='Committed Git ref; local dirty files are excluded.')
    parser.add_argument('--output-dir')
    parser.add_argument('--with-images', action='store_true', help='Build and save all images for offline installation.')
    parser.add_argument('--seal', metavar='DIR', help='Rewrite SHA256SUMS for DIR after evidence was added; no build.')
    args = parser.parse_args()
    if args.seal:
        require(not args.output_dir and not args.with_images, '--seal cannot be combined with a build.')
        print(json.dumps(seal(Path(args.seal).resolve()), indent=2))
        return
    require(bool(args.output_dir), '--output-dir is required.')
    sha = subprocess.check_output(['git', 'rev-parse', f'{args.ref}^{{commit}}'], cwd=ROOT, text=True).strip()
    version = release_version(sha)
    destination = Path(args.output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    source = destination / f'vahan-{sha[:12]}-source.zip'
    images = destination / f'vahan-{sha[:12]}-images.tar'
    manifest_path = destination / f'vahan-{sha[:12]}-manifest.json'
    sums_path = destination / SUMS_NAME
    if any(path.exists() for path in (source, images, manifest_path, sums_path)):
        raise SystemExit('Destination artifacts already exist. Use a new output directory; nothing was overwritten.')
    subprocess.run(['git', 'archive', '--format=zip', '-o', str(source), sha, *PATHS], cwd=ROOT, check=True)
    with zipfile.ZipFile(source) as archive:
        check_source_members(archive.namelist())
    namespace, tag = 'vahan-review', version
    manifest = {'format': 1, 'version': version, 'sourceCommit': sha, 'imageNamespace': namespace, 'imageTag': tag,
                'imageRevision': sha, 'files': {source.name: digest(source)}, 'imageIds': {}, 'images': {},
                'scope': 'Committed source only; outputs, secrets, local CA, backups and Git metadata are excluded.'}
    if args.with_images:
        with tempfile.TemporaryDirectory(prefix='vahan-package-build-') as temporary:
            build_root = Path(temporary)
            with zipfile.ZipFile(source) as archive:
                archive.extractall(build_root)
            # CA files are operator-specific and are never redistributed in a package.
            # Build uses the committed cert directory, even when empty.
            subprocess.run([os.sys.executable, 'scripts/setup-docker.py'], cwd=build_root, check=True)
            env = {**os.environ, 'VAHAN_IMAGE_NAMESPACE': namespace, 'VAHAN_IMAGE_TAG': tag,
                   'VAHAN_VCS_REF': sha}
            compose = ['docker', 'compose', '--env-file', '.docker.env']
            # Only the three application images are built; PostgreSQL is the
            # official upstream image pinned by digest in compose.yaml (D-33).
            subprocess.run([*compose, 'build', '--sbom=true', '--provenance=mode=max'],
                           cwd=build_root, env=env, check=True)
            refs = subprocess.check_output([*compose, 'config', '--images'], cwd=build_root, env=env,
                                           text=True).split()
            refs = list(dict.fromkeys(refs))
            official = [ref for ref in refs if '/postgres:' in ref or ref.startswith('postgres:')]
            require(len(refs) == 4 and len(official) == 1,
                    f'Expected 3 application images plus one official PostgreSQL image, got {refs}.')
            pinned = official[0]
            require(DIGEST_REF.fullmatch(pinned) is not None, f'PostgreSQL image is not digest-pinned: {pinned}')
            subprocess.run(['docker', 'pull', pinned], check=True)
            expected_digest = pinned.rsplit('@', 1)[1]
            application_platform = None
            for ref in refs:
                info = json.loads(subprocess.check_output(['docker', 'image', 'inspect', ref], text=True))[0]
                platform = f"{info['Os']}/{info['Architecture']}"
                labels = info['Config'].get('Labels') or {}
                if ref == pinned:
                    require(any(item.endswith('@' + expected_digest) for item in info.get('RepoDigests', []))
                            or info['Id'] == expected_digest,
                            f'{ref} does not resolve to the pinned digest {expected_digest}.')
                else:
                    application_platform = application_platform or platform
                    require(platform == application_platform, 'Application images use different platforms.')
                manifest['imageIds'][ref] = info['Id']
                manifest['images'][ref] = {
                    'id': info['Id'], 'repoDigests': info.get('RepoDigests', []), 'platform': platform,
                    'upstream': ref == pinned,
                    'revisionLabel': labels.get(LABEL_REVISION) if ref != pinned else None,
                    'versionLabel': labels.get(LABEL_VERSION) if ref != pinned else None}
            # T29/D-09: a release package carries the declared revision and version; `unknown` or foreign values are refused.
            for ref, item in manifest['images'].items():
                if not item['upstream']:
                    require(item['revisionLabel'] == sha,
                            f"{ref} carries revision label {item['revisionLabel']!r}, expected {sha}.")
                    require(item['versionLabel'] == version,
                            f"{ref} carries version label {item['versionLabel']!r}, expected {version}.")
                    require(ref.rsplit(':', 1)[-1] == version, f'{ref} is not tagged with the release version {version}.')
            require(manifest['images'][pinned]['platform'] == application_platform,
                    'PostgreSQL platform differs from the application images.')
            save_offline_images(images, refs, pinned)
            manifest['files'][images.name] = digest(images)
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    # The manifest cannot list its own digest, so SHA256SUMS is the independent record of it (RG3).
    write_sums(destination, {**manifest['files'], manifest_path.name: digest(manifest_path)})
    verify_sums(destination, complete=False)
    print(json.dumps({'version': version, 'sourceCommit': sha, 'manifest': str(manifest_path),
                      'sha256sums': str(sums_path), 'files': manifest['files']}, indent=2))


if __name__ == '__main__':
    main()
