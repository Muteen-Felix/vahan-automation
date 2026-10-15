#!/usr/bin/env python3
"""Decide whether recorded D3 evidence is still valid for a later commit (PLAN T28, section 2.2, appendix B.2).

Ledger mode  : evidence-check.py --from S --to F [--snapshot-from A --snapshot-to B]
               [--fingerprint-from A --fingerprint-to B] [--ledger-dir docs/release/evidence]
Manifest mode: evidence-check.py --manifest <release-dir> [--repo <git dir>]

Ledgers carry a header of "- row: R5", "- sha: <40 hex>", "- snapshot: <file>", "- fingerprint: <file>".
Exit 0 = every ledger Valid / every manifest check passed, 1 = Reopened or failed check, 2 = usage/input error.
Standard library and git only. Evidence is Valid only when nothing it depends on changed; unknown => Reopened.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAP = ROOT / "docs/release/path-map.json"
SHA = re.compile(r"^[0-9a-f]{40}$")
UNSET, SET = "<unset>", "<set>"


class InputError(Exception):
    pass


# ---------------------------------------------------------------- helpers
def git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")
    if check and result.returncode:
        raise InputError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def glob_regex(pattern: str) -> re.Pattern:
    out, index = "", 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            out, index = out + "(?:.*/)?", index + 3
        elif pattern.startswith("**", index):
            out, index = out + ".*", index + 2
        elif pattern[index] == "*":
            out, index = out + "[^/]*", index + 1
        elif pattern[index] == "?":
            out, index = out + "[^/]", index + 1
        else:
            out, index = out + re.escape(pattern[index]), index + 1
    return re.compile("^" + out + "$")


def matches(path: str, patterns) -> bool:
    return any(glob_regex(pattern).match(path) for pattern in patterns)


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise InputError(f"Cannot read JSON {path}: {error}") from error


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------- changed paths
VERSION_VALUE = re.compile(r'(^\s*"?version"?\s*[:=]\s*)"[^"]*"', re.MULTILINE)


def version_only(repo: Path, source: str, target: str, path: str) -> bool:
    old = git(repo, "show", f"{source}:{path}", check=False)
    new = git(repo, "show", f"{target}:{path}", check=False)
    mask = lambda text: VERSION_VALUE.sub(r'"*"', text)
    return bool(old and new) and mask(old) == mask(new)


def classify_changes(repo: Path, path_map: dict, source: str, target: str):
    """Return (global_reasons, per_row_reasons, ignored_count, build_workflow_changed)."""
    changed = [p for p in git(repo, "diff", "--name-only", "-z", source, target).split("\0") if p]
    global_reasons, rows, ignored, workflow = [], {}, 0, False
    for path in changed:
        if matches(path, path_map.get("build_workflow", [])):
            workflow = True
        if matches(path, path_map["global_impact"]):
            if path_map.get("ignore_version_only_changes") and path in path_map.get("version_only_files", []) \
                    and version_only(repo, source, target, path):
                ignored += 1
                continue
            global_reasons.append(f"global-impact path changed: {path}")
            continue
        if matches(path, path_map["non_runtime"]):
            ignored += 1
            continue
        hit = False
        for name, spec in path_map["rows"].items():
            if matches(path, spec["paths"]):
                rows.setdefault(name, []).append(f"runtime path changed: {path}")
                hit = True
        if not hit and path.startswith("apps/"):
            global_reasons.append(f"unmapped runtime path (fail-closed): {path}")
        elif not hit:
            ignored += 1
    return global_reasons, rows, ignored, workflow


# ---------------------------------------------------------------- fingerprint / snapshot
def rows_for(target, path_map: dict):
    return sorted(path_map["rows"]) if target == "global" else list(target)


def compare_fingerprints(old: dict, new: dict, path_map: dict):
    reasons = {}
    for key in sorted(set(old) | set(new)):
        if old.get(key) == new.get(key):
            continue
        target = path_map["build_inputs"].get(key, "global")  # unknown build input => global
        for row in rows_for(target, path_map):
            reasons.setdefault(row, []).append(f"build input differs: {key}")
    return reasons


def key_spec(key: str, path_map: dict):
    name = key.split(".", 1)[1] if "." in key else key
    return path_map["config_keys"].get(name) or path_map.get("config_derived_keys", {}).get(name)


def value_ok(spec: dict, value: str) -> bool:
    pattern = spec.get("value_pattern")
    if value in (SET, UNSET):
        return False
    if pattern is None:
        return True
    parts = [v for v in value.split(spec["list_separator"]) if v != ""] if spec.get("list_separator") else [value]
    return bool(parts) and all(re.fullmatch(pattern, part) for part in parts)


def compare_snapshots(old: dict, new: dict, path_map: dict):
    """Apply the section 2.2 reopen rules. Returns {row: [reasons]}; every row for fail-closed cases."""
    reasons: dict[str, list[str]] = {}

    def add(target, text):
        for row in rows_for(target, path_map):
            reasons.setdefault(row, []).append(text)

    old_values, new_values = old.get("values", {}), new.get("values", {})
    for key in sorted(set(old_values) | set(new_values)):
        before, after = old_values.get(key, UNSET), new_values.get(key, UNSET)
        spec = key_spec(key, path_map)
        if spec is None:
            add("global", f"unclassified config key {key} (add it to config_keys; fail-closed)")
            continue
        if spec.get("plain"):
            for label, value in (("from", before), ("to", after)):
                if value != UNSET and not value_ok(spec, value):
                    add("global", f"plain key {key} ({label}) is {value if value == SET else 'not matching value_pattern'}; review required")
            if before != after:
                add(spec["rows"], f"config value changed: {key}")
        elif (before == UNSET) != (after == UNSET):
            add(spec["rows"], f"secret/config presence changed: {key} {before} -> {after}")
    if old.get("composeFiles") != new.get("composeFiles"):
        add("global", "loaded Compose files differ between snapshots")
    if old.get("docker_certs_sha256") != new.get("docker_certs_sha256"):
        add(path_map["config_derived_keys"]["docker_certs_sha256"]["rows"], "docker/certs content differs (custom CA)")
    if old.get("images", {}).get("postgres") != new.get("images", {}).get("postgres"):
        add("global", "PostgreSQL image reference differs between snapshots")
    return reasons


# ---------------------------------------------------------------- ledger mode
def parse_ledger(path: Path) -> dict:
    header = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^-\s*(row|sha|snapshot|fingerprint)\s*:\s*(\S+)\s*$", line, re.IGNORECASE)
        if match:
            header[match.group(1).lower()] = match.group(2)
    return header


def check_ledgers(args, path_map: dict) -> int:
    repo = Path(args.repo).resolve()
    target = git(repo, "rev-parse", f"{args.to}^{{commit}}").strip()
    ledger_dir = (repo / args.ledger_dir) if not Path(args.ledger_dir).is_absolute() else Path(args.ledger_dir)
    ledgers = sorted(ledger_dir.glob("R*.md")) if ledger_dir.is_dir() else []
    snapshot_pair = (load_json(Path(args.snapshot_from)), load_json(Path(args.snapshot_to))) \
        if args.snapshot_from and args.snapshot_to else None
    fingerprint_pair = (load_json(Path(args.fingerprint_from)), load_json(Path(args.fingerprint_to))) \
        if args.fingerprint_from and args.fingerprint_to else None
    report, reopened = [], 0
    for ledger in ledgers:
        header = parse_ledger(ledger)
        entry = {"ledger": str(ledger.relative_to(repo)) if ledger.is_relative_to(repo) else str(ledger), **header}
        reasons: list[str] = []
        row, sha = header.get("row"), (args.from_sha or header.get("sha") or "")
        if args.from_sha:
            sha = git(repo, "rev-parse", f"{args.from_sha}^{{commit}}", check=False).strip() or args.from_sha
        if row not in path_map["rows"]:
            reasons.append(f"unknown or missing row in ledger header: {row!r}")
        if not SHA.match(sha):
            reasons.append("ledger has no full 40-hex sha")
        else:
            source = git(repo, "rev-parse", f"{sha}^{{commit}}", check=False).strip()
            ancestor = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", sha, target]).returncode == 0
            if not source or not ancestor:
                reasons.append("ledger sha is not an ancestor of the target commit")
            elif row in path_map["rows"]:
                global_reasons, per_row, ignored, workflow = classify_changes(repo, path_map, sha, target)
                reasons += global_reasons + per_row.get(row, [])
                entry["ignoredNonRuntimeFiles"] = ignored
                entry["buildWorkflowChanged"] = workflow
                if workflow:
                    entry["note"] = "workflow changed: CI evidence (E-CI) must be re-run on the target commit"
        if row in path_map["rows"]:
            for pair, compare in ((snapshot_pair, compare_snapshots), (fingerprint_pair, compare_fingerprints)):
                if pair:
                    found = compare(pair[0], pair[1], path_map)
                    reasons += found.get(row, [])
        if args.require_snapshot and not snapshot_pair:
            reasons.append("config snapshot comparison is required (C5.4) but no snapshots were supplied")
        entry["verdict"] = "Reopened" if reasons else "Valid"
        entry["reasons"] = sorted(set(reasons))
        reopened += bool(reasons)
        report.append(entry)
    summary = {"target": target, "ledgers": len(report), "valid": len(report) - reopened, "reopened": reopened}
    print(json.dumps({"summary": summary, "ledgers": report}, indent=2, ensure_ascii=False))
    return 1 if reopened and not args.allow_reopened else 0


# ---------------------------------------------------------------- manifest mode
PIN = re.compile(r"docker\.io/library/postgres:[0-9][0-9A-Za-z.\-]*@sha256:[0-9a-f]{64}")


def check_manifest(args) -> int:
    directory = Path(args.manifest).resolve()
    repo = Path(args.repo).resolve()
    manifest = load_json(directory / "release-manifest.json")
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    sha = manifest.get("source_sha", "")
    check("source_sha is a full 40-hex commit", bool(SHA.match(sha)), sha)
    if SHA.match(sha):
        tag = manifest.get("tag")
        tagged = git(repo, "rev-parse", f"{tag}^{{commit}}", check=False).strip() if tag else ""
        check("tag resolves to source_sha", tagged == sha, f"{tag} -> {tagged or 'not found'}")
        if manifest.get("source_tree"):
            check("source_tree matches commit", git(repo, "rev-parse", f"{sha}^{{tree}}", check=False).strip()
                  == manifest["source_tree"])
    images = manifest.get("images", [])
    upstream = [i for i in images if i.get("upstream")]
    app = [i for i in images if not i.get("upstream")]
    check("exactly 4 images (3 application + 1 upstream PostgreSQL)", len(images) == 4 and len(upstream) == 1 and len(app) == 3,
          f"{len(app)} application, {len(upstream)} upstream")
    check("application images carry revision label = source_sha",
          bool(app) and all(i.get("label_revision") == sha for i in app))
    if upstream and SHA.match(sha):
        compose = git(repo, "show", f"{sha}:compose.yaml", check=False)
        pins = set(PIN.findall(compose))
        check("upstream PostgreSQL reference equals compose.yaml pin at source_sha", {upstream[0].get("ref")} == pins,
              f"manifest={upstream[0].get('ref')} compose={sorted(pins)}")
        digest = (upstream[0].get("ref") or "").rsplit("@", 1)[-1]
        check("upstream digest is recorded in the image id/digest", digest in (upstream[0].get("id"), upstream[0].get("digest")))
        platforms = {i.get("platform") for i in app}
        check("upstream platform equals application platform", len(platforms) == 1 and upstream[0].get("platform") in platforms)
    images_json = directory / "images" / "images.json"
    if images_json.is_file():
        listed = load_json(images_json)
        check("images/images.json matches manifest ids", sorted(i.get("id") for i in listed) == sorted(i.get("id") for i in images))
    else:
        check("images/images.json present", False, str(images_json))
    check("custom_ca_files is empty", manifest.get("custom_ca_files") == [])
    check("lock/image comparison recorded and empty", manifest.get("lock_image_diff") == [],
          f"{manifest.get('lock_image_diff')!r}")
    sums = directory / "SHA256SUMS"
    if sums.is_file():
        listed = {}
        for line in sums.read_text(encoding="utf-8").splitlines():
            if line.strip():
                digest, _, name = line.partition("  ")
                listed[name.strip().lstrip("*")] = digest.strip()
        bad = [n for n, d in listed.items() if not (directory / n).is_file() or sha256_file(directory / n) != d]
        present = {str(p.relative_to(directory)).replace("\\", "/") for p in directory.rglob("*") if p.is_file()} - {"SHA256SUMS"}
        check("SHA256SUMS matches files", not bad, f"mismatch/missing: {bad}")
        check("SHA256SUMS covers every file", present <= set(listed), f"unlisted: {sorted(present - set(listed))[:5]}")
    else:
        check("SHA256SUMS present", False)
    docs = manifest.get("docs_commit")
    if docs and SHA.match(sha):
        paths = [p for p in git(repo, "diff", "--name-only", sha, docs, check=False).splitlines() if p]
        ancestor = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", sha, docs]).returncode == 0
        check("docs commit D only touches docs/release/** and F is its ancestor",
              ancestor and all(p.startswith("docs/release/") for p in paths), f"outside: {[p for p in paths if not p.startswith('docs/release/')][:5]}")
    tar = manifest.get("images_tar")
    if tar and (directory / tar).is_file():
        digest12 = sha256_file(directory / tar)[:12]
        log = directory / "evidence" / f"clean-install-{digest12}.md"
        check("clean-install log exists for this artifact digest and names the full digest",
              log.is_file() and sha256_file(directory / tar) in log.read_text(encoding="utf-8"), str(log.name))
    ledgers = manifest.get("ledgers", [])
    check("every cited ledger has verdict Valid or was re-run on the artifact",
          all(item.get("verdict") in ("Valid", "Rerun-on-artifact") for item in ledgers),
          f"{[i.get('ledger') for i in ledgers if i.get('verdict') not in ('Valid', 'Rerun-on-artifact')]}")
    failed = [c for c in checks if not c["ok"]]
    print(json.dumps({"manifest": str(directory), "passed": len(checks) - len(failed), "failed": len(failed),
                      "checks": checks}, indent=2, ensure_ascii=False))
    return 1 if failed else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="from_sha", help="Override the sha recorded in ledgers (S).")
    parser.add_argument("--to", help="Target commit F.")
    parser.add_argument("--repo", default=str(ROOT))
    parser.add_argument("--path-map", default=str(DEFAULT_MAP))
    parser.add_argument("--ledger-dir", default="docs/release/evidence")
    parser.add_argument("--snapshot-from")
    parser.add_argument("--snapshot-to")
    parser.add_argument("--fingerprint-from")
    parser.add_argument("--fingerprint-to")
    parser.add_argument("--require-snapshot", action="store_true", help="Reopen ledgers when no snapshot pair is given (C5.4).")
    parser.add_argument("--allow-reopened", action="store_true", help="Exit 0 even when ledgers are Reopened.")
    parser.add_argument("--manifest", help="Directory containing release-manifest.json (T53).")
    args = parser.parse_args(argv)
    try:
        if args.manifest:
            return check_manifest(args)
        if not args.to:
            parser.error("--to is required in ledger mode")
        return check_ledgers(args, load_json(Path(args.path_map)))
    except InputError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
