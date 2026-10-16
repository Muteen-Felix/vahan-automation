#!/usr/bin/env python3
"""Fail when a test file is unregistered, not referenced by CI, skipped silently or deleted silently (PLAN T13, appendix B.1).

    check-test-registration.py [--repo .] [--manifest scripts/test-manifest.json]
                               [--workflow .github/workflows/platform.yml] [--require-history] [--discover]

What it proves: a test marked `ci` is *referenced* by a `run:` step (directly, through `npm run`, through a
`node scripts/test-platform.mjs` file list, or through `unittest discover`). It does **not** prove the step ran or
passed: only the CI run does. `if:` conditions on steps are not evaluated.

Exit codes: 0 ok, 1 violations, 2 usage/config error (including `--require-history` without the baseline commit).
Standard library and `git` only.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import posixpath
import re
import shlex
import subprocess
import sys
import tokenize
import io
from pathlib import Path

STATUSES = {"ci", "deferred", "manual", "not-applicable", "removed"}
VIAS = {"workflow-run", "npm-script", "test-platform", "script"}
EXCUSED = {"deferred", "manual", "not-applicable", "removed"}  # statuses that need reason + owner
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".vite", "dist", "outputs"}
# B.1 (1) plus the repository-level scripts/ directory, which CI also runs (see platform.yml).
PATTERNS = [
    ("apps/api-server/verification", "test_*.py", False),
    ("apps/api-server/tests", "test_*.py", False),
    ("apps/api-server/scripts", "test[-_]*.py", False),
    ("apps/browser-runner", "test-*.mjs", False),
    ("apps/web-ui/scripts", "test-*.mjs", False),
    ("tools", "test_*.py", True),
    ("scripts", "test[-_]*.py", False),
]
SKIP_MARKERS = [
    re.compile(r"@unittest\.skip"), re.compile(r"\bself\.skipTest\("), re.compile(r"\bunittest\.SkipTest\b"),
    re.compile(r"\bpytest\.skip\("), re.compile(r"\bpytest\.mark\.(skip|skipif|xfail)\b"),
    re.compile(r"\bpytest\.importorskip\("), re.compile(r"\b(test|it|describe)\.(skip|todo|fixme)\("),
    re.compile(r"\b(xit|xdescribe|xtest)\("),
]
ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")


def norm(path: str) -> str:
    return posixpath.normpath(path.replace("\\", "/"))


# ------------------------------------------------------------------------------------------ candidates
def candidates(root: Path) -> list[str]:
    found: set[str] = set()
    for base, pattern, recursive in PATTERNS:
        start = root / base
        if not start.is_dir():
            continue
        for current, dirs, files in os.walk(start):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                if fnmatch.fnmatchcase(name, pattern):
                    found.add(norm(os.path.relpath(Path(current) / name, root)))
            if not recursive:
                dirs[:] = []
    return sorted(found)


def blank_python(source: str) -> str:
    """Replace string and comment text with spaces so a marker quoted in a fixture is not mistaken for a real skip."""
    lines = source.splitlines(keepends=True)
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return source
    skip_types = {tokenize.STRING, tokenize.COMMENT}
    for name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
        if hasattr(tokenize, name):
            skip_types.add(getattr(tokenize, name))
    for token in tokens:
        if token.type not in skip_types:
            continue
        (start_row, start_col), (end_row, end_col) = token.start, token.end
        for row in range(start_row, end_row + 1):
            line = lines[row - 1]
            body = line.rstrip("\r\n")
            first = start_col if row == start_row else 0
            last = end_col if row == end_row else len(body)
            lines[row - 1] = body[:first] + " " * (last - first) + body[last:] + line[len(body):]
    return "".join(lines)


def blank_javascript(source: str) -> str:
    out: list[str] = []
    mode, quote, index = "code", "", 0
    while index < len(source):
        char, pair = source[index], source[index:index + 2]
        if mode == "code":
            if pair == "//":
                mode = "line"
            elif pair == "/*":
                mode = "block"
            elif char in "'\"`":
                mode, quote = "string", char
            out.append(char if mode == "code" else " ")
        elif mode == "line":
            if char == "\n":
                mode = "code"
                out.append(char)
            else:
                out.append(" ")
        elif mode == "block":
            out.append(" " if char != "\n" else char)
            if pair == "*/":
                out.append(" ")
                index += 1
                mode = "code"
        else:  # string
            if char == "\\":
                out.append("  ")
                index += 1
            else:
                out.append(" " if char != "\n" else char)
                if char == quote:
                    mode = "code"
        index += 1
    return "".join(out)


def code_only(path: str, source: str) -> str:
    return blank_python(source) if path.endswith(".py") else blank_javascript(source)


def is_test_like(path: str) -> bool:
    return re.match(r"^test[-_]", posixpath.basename(path)) is not None


# ------------------------------------------------------------------------------------------ workflow
def run_blocks(text: str) -> list[tuple[str, str]]:
    """(run text, working-directory) for every `run:` step. Minimal YAML reader: enough for GitHub workflows."""
    lines = text.splitlines()
    blocks: list[tuple[str, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)(-\s+)?run:\s*(.*)$", line)
        if not match:
            continue
        key_column = len(match.group(1)) + len(match.group(2) or "")
        value = match.group(3).strip()
        if value[:1] in "|>":
            body: list[str] = []
            for follow in lines[index + 1:]:
                if follow.strip() and len(follow) - len(follow.lstrip()) <= key_column:
                    break
                body.append(follow.strip())
            value = "\n".join(body)
        start = index
        while start > 0 and not re.match(r"^\s*-\s", lines[start]):
            start -= 1
        step_column = len(lines[start]) - len(lines[start].lstrip())
        workdir = "."
        for scan in range(start, len(lines)):
            if scan > start and re.match(r"^\s*-\s", lines[scan]) and len(lines[scan]) - len(lines[scan].lstrip()) <= step_column:
                break
            found = re.match(r"^\s*(?:-\s+)?working-directory:\s*(\S+)\s*$", lines[scan])
            if found:
                workdir = found.group(1).strip("'\"")
                break
        blocks.append((value, workdir))
    return blocks


def commands(run_text: str) -> list[list[str]]:
    """Split a run block into commands, drop heredoc bodies, strip leading VAR=value assignments."""
    kept: list[str] = []
    terminator = None
    for raw in run_text.splitlines():
        if terminator is not None:
            if raw.strip() == terminator:
                terminator = None
            continue
        heredoc = re.search(r"<<-?\s*['\"]?([A-Za-z_]+)['\"]?", raw)
        if heredoc:
            terminator = heredoc.group(1)
            raw = raw[:heredoc.start()]
        kept.append(raw)
    joined = re.sub(r"\\\s*\n", " ", "\n".join(kept))
    result: list[list[str]] = []
    for part in re.split(r"&&|\|\||;|\||\n", joined):
        part = part.strip()
        if not part:
            continue
        try:
            tokens = shlex.split(part, posix=True)
        except ValueError:
            tokens = part.split()
        while tokens and ENV_ASSIGNMENT.match(tokens[0]):
            tokens.pop(0)
        if tokens:
            result.append(tokens)
    return result


class Resolver:
    def __init__(self, root: Path, tests: list[str]):
        self.root, self.tests = root, tests
        self.by_basename: dict[str, list[str]] = {}
        for path in tests:
            self.by_basename.setdefault(posixpath.basename(path), []).append(path)
        self.hits: dict[str, dict[str, set]] = {}  # path -> {"via": set, "command": set}

    def add(self, path: str, via: str, command: str) -> None:
        path = norm(path)
        entry = self.hits.setdefault(path, {"via": set(), "command": set()})
        entry["via"].add(via)
        entry["command"].add(command)

    def files_in(self, directory: str, pattern: str | None, recursive: bool) -> list[str]:
        base = self.root / directory
        out: list[str] = []
        if not base.is_dir():
            return out
        for current, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                ok = fnmatch.fnmatchcase(name, pattern) if pattern else (
                    fnmatch.fnmatchcase(name, "test_*.py") or fnmatch.fnmatchcase(name, "*_test.py"))
                if ok:
                    out.append(norm(os.path.relpath(Path(current) / name, self.root)))
            if not recursive:
                break
        return out

    def interpret(self, tokens: list[str], workdir: str, via: str, label: str, depth: int = 0) -> None:
        if not tokens or depth > 4:
            return
        head = posixpath.basename(tokens[0])
        rel = lambda token: norm(posixpath.join(workdir, token))  # noqa: E731
        if re.fullmatch(r"python[0-9.]*|py", head):
            args = tokens[1:]
            if args[:1] == ["-m"] and len(args) >= 2:
                module = args[1]
                rest = args[2:]
                if module == "pytest":
                    for token in rest:
                        token = token.split("::", 1)[0]
                        if token.startswith("-"):
                            continue
                        target = rel(token)
                        if (self.root / target).is_dir():
                            for found in self.files_in(target, None, True):
                                self.add(found, via, label)
                        elif (self.root / target).is_file():
                            self.add(target, via, label)
                elif module == "coverage" and rest[:1] == ["run"]:
                    nested_module = next((position for position, token in enumerate(rest) if token == "-m"), None)
                    if nested_module is not None and nested_module + 1 < len(rest):
                        self.interpret(["python", "-m", *rest[nested_module + 1:]],
                                       workdir, via, label, depth + 1)
                elif module == "unittest" and rest[:1] == ["discover"]:
                    directory, pattern = ".", "test*.py"
                    for position, token in enumerate(rest):
                        if token == "-s" and position + 1 < len(rest):
                            directory = rest[position + 1]
                        if token == "-p" and position + 1 < len(rest):
                            pattern = rest[position + 1]
                    for found in self.files_in(rel(directory), pattern, False):
                        self.add(found, via, label)
                return
            for token in args:
                if token.endswith(".py") and not token.startswith("-") and (self.root / rel(token)).is_file():
                    self.add(rel(token), "script" if via == "workflow-run" else via, label)
                    return
            return
        if head == "node":
            flags = [t for t in tokens[1:] if t.startswith("-")]
            if "--check" in flags or "-c" in flags:
                return  # syntax check only: not a test run
            script = next((t for t in tokens[1:] if not t.startswith("-")), None)
            if script and script.endswith((".mjs", ".js")):
                target = rel(script)
                if (self.root / target).is_file():
                    self.add(target, "script" if via == "workflow-run" else via, label)
                    self.expand_test_files(target, label)
            return
        if head == "npm":
            if tokens[1:2] == ["test"]:
                name = "test"
            elif tokens[1:2] == ["run"] or tokens[1:2] == ["run-script"]:
                name = next((t for t in tokens[2:] if not t.startswith("-")), "")
            else:
                return
            package = self.root / workdir / "package.json"
            if not package.is_file():
                return
            script = (json.loads(package.read_text(encoding="utf-8")).get("scripts") or {}).get(name)
            if script:
                for sub in commands(script):
                    self.interpret(sub, workdir, "npm-script", f"npm run {name} ({workdir})", depth + 1)
            return
        if head == "docker":
            for token in tokens:
                if token.endswith((".mjs", ".py")):
                    matches = self.by_basename.get(posixpath.basename(token), [])
                    if len(matches) == 1:
                        self.add(matches[0], via, label)

    def expand_test_files(self, platform_file: str, label: str) -> None:
        path = self.root / platform_file
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            return
        names: list[str] = []
        match = re.search(r"\btestFiles\s*=\s*\[(.*?)\]", source, re.DOTALL)
        if match:
            names += re.findall(r"['\"]([^'\"]+\.mjs)['\"]", match.group(1))
        # Files the platform script starts directly: runNode(['scripts/x.mjs', ...]).
        names += re.findall(r"\brunNode\(\s*\[\s*['\"]([^'\"]+\.mjs)['\"]", source)
        if not names:
            return
        package_dir = path.parent
        while package_dir != self.root and not (package_dir / "package.json").is_file():
            package_dir = package_dir.parent
        for name in names:
            self.add(norm(os.path.relpath(package_dir / name, self.root)), "test-platform", f"{label} -> {platform_file}")


def workflow_hits(root: Path, workflow: Path, tests: list[str]) -> Resolver:
    resolver = Resolver(root, tests)
    for text, workdir in run_blocks(workflow.read_text(encoding="utf-8")):
        for tokens in commands(text):
            label = " ".join(tokens)[:200]
            resolver.interpret(tokens, workdir, "workflow-run", label if workdir == "." else f"cd {workdir} && {label}")
    return resolver


# ------------------------------------------------------------------------------------------ checks
def deleted_tests(root: Path, base: str) -> list[str] | None:
    if git(root, "cat-file", "-e", f"{base}^{{commit}}").returncode != 0:
        return None
    out = git(root, "diff", "--name-status", "--diff-filter=D", f"{base}..HEAD")
    if out.returncode != 0:
        return None
    paths = [line.split("\t", 1)[1].strip() for line in out.stdout.splitlines() if "\t" in line]
    return sorted(p for p in map(norm, paths) if is_test_like(p) and p.endswith((".py", ".mjs")))


def reference_corpus(root: Path, workflow_text: str) -> str:
    """Text in which a removed test must no longer appear: the workflow, every package.json and the platform runner."""
    parts = [workflow_text]
    for base in (root / "apps",):
        if not base.is_dir():
            continue
        for current, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                full = Path(current) / name
                if name == "package.json" or name == "test-platform.mjs":
                    parts.append(full.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def mentions(corpus: str, path: str) -> bool:
    base = re.escape(posixpath.basename(path))
    return path in corpus or re.search(rf"(?<![\w.-]){base}(?![\w-])", corpus) is not None


def check(root: Path, manifest: dict, workflow: Path, require_history: bool = False, base: str | None = None):
    problems: list[str] = []
    notes: list[str] = []
    tests = candidates(root)
    resolver = workflow_hits(root, workflow, tests)
    workflow_text = workflow.read_text(encoding="utf-8")
    corpus = reference_corpus(root, workflow_text)
    entries = manifest.get("tests", [])
    by_path: dict[str, list[dict]] = {}
    for entry in entries:
        by_path.setdefault(norm(str(entry.get("path", ""))), []).append(entry)

    for path, group in by_path.items():
        if len(group) > 1:
            problems.append(f"DUPLICATE: {path} has {len(group)} manifest entries (need exactly one)")
    for path in tests:
        if path not in by_path:
            problems.append(f"UNREGISTERED: {path} matches a test pattern but has no manifest entry")
    for path, hit in sorted(resolver.hits.items()):
        if is_test_like(path) and path not in by_path:
            problems.append(f"UNREGISTERED-IN-CI: {path} is run by the workflow but missing from the manifest")

    for path, group in sorted(by_path.items()):
        entry = group[0]
        status = entry.get("status")
        where = f"{path}"
        if status not in STATUSES:
            problems.append(f"BAD-STATUS: {where}: status {status!r} is not one of {sorted(STATUSES)}")
            continue
        exists = (root / path).is_file()
        if status == "removed":
            if exists:
                problems.append(f"REMOVED-BUT-PRESENT: {where} is marked removed but the file still exists")
            for field in ("removed_in", "reason", "owner"):
                if not entry.get(field):
                    problems.append(f"MISSING-{field.upper()}: {where} (status removed)")
            if not (entry.get("equivalent_tests") or entry.get("coverage_assessment")):
                problems.append(f"MISSING-EQUIVALENT: {where} needs equivalent_tests or coverage_assessment")
            if mentions(corpus, path) or path in resolver.hits:
                problems.append(f"REMOVED-BUT-REFERENCED: {where} is still referenced by the workflow or an npm script")
            continue
        if not exists:
            problems.append(f"MISSING-FILE: {where} is in the manifest (status {status}) but not on disk")
            continue
        if status in EXCUSED:
            for field in ("reason", "owner"):
                if not entry.get(field):
                    problems.append(f"MISSING-{field.upper()}: {where} (status {status})")
            if status == "deferred" and not entry.get("until"):
                problems.append(f"MISSING-UNTIL: {where} (status deferred)")
        if status == "ci":
            hit = resolver.hits.get(path)
            if not hit:
                problems.append(f"NOT-REFERENCED: {where} is marked ci but no workflow run step reaches it")
            else:
                via = entry.get("via")
                if via not in VIAS:
                    problems.append(f"BAD-VIA: {where}: via {via!r} is not one of {sorted(VIAS)}")
                elif via not in hit["via"]:
                    problems.append(f"WRONG-VIA: {where}: manifest says {via!r}, workflow reaches it via {sorted(hit['via'])}")
            if not entry.get("command"):
                problems.append(f"MISSING-COMMAND: {where} (status ci)")
            for variable in entry.get("env") or []:
                if variable not in workflow_text:
                    problems.append(f"UNKNOWN-ENV: {where}: {variable} does not appear in the workflow")
        source = (root / path).read_text(encoding="utf-8", errors="replace")
        code = code_only(path, source)
        marked = [m.pattern for m in SKIP_MARKERS if m.search(code)]
        if marked and not entry.get("deferred_tests"):
            problems.append(f"UNDECLARED-SKIP: {where} contains skip/xfail markers {marked} but lists no deferred_tests")
        for name in entry.get("deferred_tests") or []:
            if not re.search(rf"\b{re.escape(name)}\b", source):
                problems.append(f"STALE-DEFERRED: {where}: deferred test {name!r} no longer exists in the file")
        for name in entry.get("removed_tests") or []:
            if re.search(rf"\b{re.escape(name)}\b", source):
                problems.append(f"REMOVED-TEST-PRESENT: {where}: {name!r} is declared removed but is still in the file")

    baseline = base or manifest.get("baseline")
    deleted = deleted_tests(root, baseline) if baseline else None
    if deleted is None:
        message = f"deleted-file check NOT RUN: baseline {baseline!r} is not reachable (shallow clone or unknown ref)"
        if require_history:
            problems.append("NO-HISTORY: " + message)
        else:
            notes.append(message)
    else:
        for path in deleted:
            group = by_path.get(path)
            if not group or group[0].get("status") != "removed":
                problems.append(f"SILENT-DELETE: {path} was deleted since {baseline[:12]} without a `removed` manifest entry")
        for path, group in by_path.items():
            if group[0].get("status") == "removed" and path not in deleted:
                problems.append(f"FALSE-REMOVED: {path} is marked removed but was not deleted since {baseline[:12]}")
    return problems, notes, tests, resolver


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    root_default = Path(__file__).resolve().parents[1]
    parser.add_argument("--repo", default=str(root_default))
    parser.add_argument("--manifest", default=None)
    parser.add_argument("--workflow", default=None)
    parser.add_argument("--base", default=None, help="Override manifest.baseline for the deleted-file check.")
    parser.add_argument("--require-history", action="store_true", help="Fail instead of warning when the baseline is not reachable.")
    parser.add_argument("--discover", action="store_true", help="Print candidates and how the workflow reaches them (JSON), then exit.")
    args = parser.parse_args(argv)
    root = Path(args.repo).resolve()
    manifest_path = Path(args.manifest) if args.manifest else root / "scripts/test-manifest.json"
    workflow = Path(args.workflow) if args.workflow else root / ".github/workflows/platform.yml"
    try:
        if not workflow.is_file():
            raise OSError(f"workflow not found: {workflow}")
        if args.discover:
            tests = candidates(root)
            resolver = workflow_hits(root, workflow, tests)
            report = {path: ({"via": sorted(resolver.hits[path]["via"]), "command": sorted(resolver.hits[path]["command"])}
                             if path in resolver.hits else None) for path in tests}
            print(json.dumps(report, indent=1, sort_keys=True))
            return 0
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    problems, notes, tests, resolver = check(root, manifest, workflow, args.require_history, args.base)
    by_status: dict[str, int] = {}
    for entry in manifest.get("tests", []):
        by_status[entry.get("status", "?")] = by_status.get(entry.get("status", "?"), 0) + 1
    for note in notes:
        print(f"note: {note}")
    for problem in problems:
        print(f"FAIL {problem}")
    summary = ", ".join(f"{k}={v}" for k, v in sorted(by_status.items()))
    print(f"{len(tests)} test files, {len(manifest.get('tests', []))} manifest entries ({summary}); "
          f"{len(problems)} problem(s)")
    if problems:
        return 1
    print("OK: every test file is registered and every `ci` entry is referenced by the workflow "
          "(referenced, not proven to have run).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
