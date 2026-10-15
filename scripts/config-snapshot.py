#!/usr/bin/env python3
"""Write a secret-free runtime-config snapshot for release evidence (PLAN T28b, section 2.2, appendix B.2).

    config-snapshot.py --env-file .docker.env --out config-snapshot-<id>.json

Allowlist model: a value is written verbatim only when its key is `plain: true` in docs/release/path-map.json
(`config_keys` / `config_derived_keys`) AND it full-matches the reviewed `value_pattern`. Every other value, including
new or unknown keys and URLs that carry credentials, is written as `<set>` / `<unset>` - never a value, never a hash.
Exit codes: 0 ok, 2 usage/compose error, 3 compose override outside the source bundle, 4 secret-looking text found
(nothing is written).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNSET, SET = "<unset>", "<set>"
ALLOWED_COMPOSE_FILES = {"compose.yaml"}
OVERRIDE_GLOBS = ("compose.override.y*ml", "docker-compose.override.y*ml", "docker-compose.y*ml", "compose.yml")
IMAGE_PATTERN = r"^[a-z0-9][a-z0-9./_:-]*(@sha256:[0-9a-f]{64})?$"
SECRET_PATTERNS = [
    re.compile(r"://[^/\s:@]+:[^/\s@]+@"),
    re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key|private[_-]?key)\b\s*[:=]\s*[\"']?[^\s\"',}]{6,}"),
]
STRIP_BEFORE_ENTROPY = re.compile(r"sha256:[0-9a-f]{64}|\b[0-9a-f]{40,64}\b")


class Refused(Exception):
    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code


def entropy(text: str) -> float:
    return -sum(text.count(c) / len(text) * math.log2(text.count(c) / len(text)) for c in set(text)) if text else 0.0


def secret_findings(text: str) -> list[str]:
    findings = [p.pattern for p in SECRET_PATTERNS if p.search(text)]
    for token in re.findall(r"[A-Za-z0-9_\-+/=]{32,}", STRIP_BEFORE_ENTROPY.sub("", text)):
        if entropy(token) > 3.6 and "/" not in token[:3]:
            findings.append(f"high-entropy token of length {len(token)}")
    return findings


def spec_for(name: str, path_map: dict):
    return path_map["config_keys"].get(name) or path_map.get("config_derived_keys", {}).get(name)


def render(name: str, value, path_map: dict, review_errors: list[str], where: str):
    """Allowlist rule for one value; returns the string to store."""
    if value is None:
        return UNSET
    spec = spec_for(name, path_map)
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, separators=(",", ":"))
    if not spec or not spec.get("plain"):
        return SET
    pattern = spec.get("value_pattern")
    separator = spec.get("list_separator")
    parts = [p for p in text.split(separator) if p != ""] if separator else [text]
    if pattern and not (parts and all(re.fullmatch(pattern, part) for part in parts)):
        review_errors.append(f"{where}: value does not full-match the reviewed pattern; recorded as {SET}")
        return SET
    return text


def compose_config(env_file: Path, project_dir: Path, compose_json: Path | None) -> dict:
    if compose_json:
        return json.loads(compose_json.read_text(encoding="utf-8"))
    result = subprocess.run(["docker", "compose", "--env-file", str(env_file), "config", "--format", "json"],
                            cwd=project_dir, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise Refused("docker compose config failed (details withheld: they may echo configuration).", 2)
    return json.loads(result.stdout)


def loaded_compose_files(project_dir: Path) -> list[str]:
    found = {"compose.yaml"} if (project_dir / "compose.yaml").is_file() else set()
    for pattern in OVERRIDE_GLOBS:
        found |= {p.name for p in project_dir.glob(pattern)}
    for entry in filter(None, os.environ.get("COMPOSE_FILE", "").split(os.pathsep)):
        found.add(os.path.relpath(Path(entry).resolve(), project_dir).replace("\\", "/"))
    return sorted(found)


def certs_hash(project_dir: Path) -> str:
    directory = project_dir / "docker" / "certs"
    entries = sorted(f"{p.name}:{hashlib.sha256(p.read_bytes()).hexdigest()}" for p in directory.glob("*")
                     if p.is_file() and p.name not in {".gitkeep", "README.md"}) if directory.is_dir() else []
    return hashlib.sha256("\n".join(entries).encode()).hexdigest() if entries else "none"


def build_snapshot(config: dict, path_map: dict, project_dir: Path, image_ids: dict | None = None) -> dict:
    review_errors: list[str] = []
    values: dict[str, str] = {}
    images: dict[str, str] = {}
    for service, body in sorted(config.get("services", {}).items()):
        for key, value in sorted((body.get("environment") or {}).items()):
            values[f"{service}.{key}"] = render(key, value, path_map, review_errors, f"{service}.{key}")
        values[f"{service}.image"] = render("image", body.get("image"), path_map, review_errors, f"{service}.image")
        if body.get("image"):
            images[service] = body["image"]
        replicas = (body.get("deploy") or {}).get("replicas")
        values[f"{service}.replicas"] = render("replicas", None if replicas is None else str(replicas),
                                                 path_map, review_errors, f"{service}.replicas")
        ports = [{k: p.get(k) for k in ("host_ip", "published", "target", "protocol")} for p in body.get("ports") or []]
        values[f"{service}.published_ports"] = render("published_ports", ports or None, path_map, review_errors,
                                                      f"{service}.published_ports")
        for field in ("command", "entrypoint", "labels"):
            values[f"{service}.{field}"] = SET if body.get(field) else UNSET
        values[f"{service}.build_args"] = SET if (body.get("build") or {}).get("args") else UNSET
    snapshot = {
        "version": 1, "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "composeFiles": loaded_compose_files(project_dir),
        "composeProfiles": os.environ.get("COMPOSE_PROFILES", ""),
        "values": values, "images": images,
        "docker_certs_sha256": certs_hash(project_dir),
        "reviewErrors": review_errors,
    }
    if image_ids:
        snapshot["imageIds"] = image_ids
    return snapshot


def image_ids_for(refs: list[str]) -> dict:
    found = {}
    for ref in refs:
        result = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", ref], capture_output=True, text=True)
        found[ref] = result.stdout.strip() if result.returncode == 0 else None
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env-file", required=False, default=str(ROOT / ".docker.env"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--project-dir", default=str(ROOT))
    parser.add_argument("--path-map", default=str(ROOT / "docs/release/path-map.json"))
    parser.add_argument("--compose-json", help="Use a captured `docker compose config --format json` (tests).")
    parser.add_argument("--image-ids", action="store_true", help="Also record local image IDs of the 4 images.")
    args = parser.parse_args(argv)
    try:
        project_dir = Path(args.project_dir).resolve()
        path_map = json.loads(Path(args.path_map).read_text(encoding="utf-8"))
        files = loaded_compose_files(project_dir)
        extra = [f for f in files if f not in ALLOWED_COMPOSE_FILES]
        if extra:
            raise Refused(f"Compose file(s) outside the source bundle are loaded: {extra}. Release verification stops.", 3)
        config = compose_config(Path(args.env_file), project_dir, Path(args.compose_json) if args.compose_json else None)
        refs = sorted({b.get("image") for b in config.get("services", {}).values() if b.get("image")})
        snapshot = build_snapshot(config, path_map, project_dir, image_ids_for(refs) if args.image_ids else None)
        text = json.dumps(snapshot, indent=1, sort_keys=True, ensure_ascii=False)
        findings = secret_findings(text)
        if findings:
            raise Refused(f"Snapshot looks like it contains a secret ({findings}); not written.", 4)
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.out}: {len(snapshot['values'])} keys, "
              f"{sum(v not in (SET, UNSET) for v in snapshot['values'].values())} plain, "
              f"{len(snapshot['reviewErrors'])} review error(s)")
        return 0
    except Refused as refusal:
        print(f"error: {refusal}", file=sys.stderr)
        return refusal.code
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
