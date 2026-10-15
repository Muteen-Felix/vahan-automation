#!/usr/bin/env python3
"""Save full vulnerability reports/SBOMs; reject fixable HIGH/CRITICAL findings.

Unfixed vendor findings remain in reports and the summary, never suppressed.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from postgres_pin import pinned_reference

SCANNER = ("docker.io/aquasec/trivy:0.66.0@sha256:"
    "086971aaf400beebd94e8300fd8ea623774419597169156cec56eec5b00dfb1e")
# PostgreSQL is the official upstream image pinned by digest in compose.yaml (D-33);
# the three application images are built by CI under the security-test namespace.
OFFICIAL_POSTGRES = pinned_reference()
# Decision D-36 (Felix, 13/10/2026): the fixable Go-stdlib findings of the privilege-drop helper bundled in the
# official PostgreSQL image are accepted. The exception is bound to this exact image digest, this exact binary and
# the Go standard library only; any other fixable HIGH/CRITICAL finding, or a different digest, still fails.
ACCEPTED_EXCEPTIONS = {
    OFFICIAL_POSTGRES.rsplit("@", 1)[1]: {
        "decision": "D-36", "target": "usr/local/bin/gosu", "type": "gobinary", "package": "stdlib",
        "reason": "gosu runs once as root to drop privileges and does not use net/http or crypto/tls (assumption "
                  "to be re-confirmed by Security); replaced when upstream ships a rebuilt gosu.",
    }
}
IMAGES = [OFFICIAL_POSTGRES,
          *[f"vahan-security-test/{name}:round4" for name in ("api", "web", "runner")]]


def run(*command: str) -> str:
    result = subprocess.run(command, text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(f"{' '.join(command)} failed:\n{result.stderr}")
    return result.stdout


def active_docker_socket() -> str:
    endpoint = os.environ.get("DOCKER_HOST")
    if not endpoint:
        endpoint = json.loads(run("docker", "context", "inspect"))[0]["Endpoints"]["docker"]["Host"]
    if endpoint.startswith("unix://"):
        return endpoint.removeprefix("unix://")
    if endpoint.startswith("npipe://"):
        # Docker Desktop exposes its Linux engine socket inside Linux containers.
        return "/var/run/docker.sock"
    raise RuntimeError("The scanner needs a local Unix Docker socket or Docker Desktop Linux engine.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ca-cert", type=Path,
        help="Optional local enterprise trust root for the scanner's HTTPS downloads.")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    container = f"vahan-scan-{secrets.token_hex(6)}"
    summary = {}
    failures = []
    try:
        run("docker", "run", "-d", "--name", container,
            "-v", f"{active_docker_socket()}:/var/run/docker.sock", "--entrypoint", "/bin/sh",
            SCANNER, "-c", "mkdir -p /reports; sleep 3600")
        if args.ca_cert:
            run("docker", "cp", str(args.ca_cert.resolve()),
                f"{container}:/usr/local/share/ca-certificates/enterprise.crt")
            run("docker", "exec", container, "update-ca-certificates")
        # Trivy reads images from the local engine; make sure the pinned digest is present.
        run("docker", "pull", OFFICIAL_POSTGRES)
        for image in IMAGES:
            name = image.split("/")[-1].split(":")[0]
            try:
                for suffix, format_name in (("vulnerabilities.json", "json"), ("cdx.json", "cyclonedx")):
                    destination = f"/reports/{name}.{suffix}"
                    run("docker", "exec", container, "trivy", "image", "--scanners", "vuln",
                        "--format", format_name, "--output", destination, image)
                    run("docker", "cp", f"{container}:{destination}", str(args.output_dir / f"{name}.{suffix}"))
                report = json.loads((args.output_dir / f"{name}.vulnerabilities.json").read_text(encoding="utf-8"))
                counts = {"high": 0, "critical": 0, "fixableHighCritical": 0, "acceptedFixable": 0}
                exception = ACCEPTED_EXCEPTIONS.get(image.rsplit("@", 1)[1]) if "@" in image else None
                for result in report.get("Results", []):
                    for finding in result.get("Vulnerabilities") or []:
                        severity = finding.get("Severity", "").lower()
                        if severity in ("high", "critical"):
                            counts[severity] += 1
                            if finding.get("FixedVersion"):
                                accepted = bool(exception and result.get("Target") == exception["target"]
                                    and result.get("Type") == exception["type"]
                                    and finding.get("PkgName") == exception["package"])
                                counts["acceptedFixable" if accepted else "fixableHighCritical"] += 1
                summary[name] = counts
                print(f"{name}: {json.dumps(counts)}", flush=True)
            except Exception as error:
                failures.append(f"{name}: {error}")
        (args.output_dir / "summary.json").write_text(json.dumps({
            "policy": "Fail HIGH/CRITICAL with a vendor fix; retain all unfixed findings in full reports. "
                      "Findings covered by an explicit exception are counted as acceptedFixable and never hidden.",
            "exceptions": ACCEPTED_EXCEPTIONS,
            "images": summary, "scanned": {i.split("/")[-1].split(":")[0]: i for i in IMAGES},
            "errors": failures,
        }, indent=2) + "\n", encoding="utf-8")
    finally:
        subprocess.run(["docker", "rm", "-f", container], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
    if failures or any(item["fixableHighCritical"] for item in summary.values()):
        raise SystemExit("Image scan failed: fixable HIGH/CRITICAL findings or scan errors; inspect artifacts.")


if __name__ == "__main__":
    main()
