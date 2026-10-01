from pathlib import Path
import re
from threading import Lock
from uuid import UUID

from app.config import settings
from app.models.job import Job, ReportSource


_SESSION_MARKER = ".vahan-session-id"
_SESSION_DIRECTORY_LOCK = Lock()


def report_session_dir(session_id: UUID, *, create: bool = False) -> Path | None:
    """Return this run's report folder, named from the first five session characters."""
    session_value = str(session_id)
    prefix = session_value[:5].lower()
    root = Path(settings.excel_report_dir)

    with _SESSION_DIRECTORY_LOCK:
        if create:
            root.mkdir(parents=True, exist_ok=True)
            suffix = 0
            while True:
                folder_name = prefix if suffix == 0 else f"{prefix}-{suffix}"
                candidate = root / folder_name
                try:
                    candidate.mkdir(exist_ok=False)
                except FileExistsError:
                    if candidate.is_symlink():
                        suffix += 1
                        continue
                    marker = candidate / _SESSION_MARKER
                    try:
                        if marker.is_file() and marker.read_text(encoding="utf-8").strip() == session_value:
                            return candidate
                    except OSError:
                        pass
                    suffix += 1
                    continue
                try:
                    (candidate / _SESSION_MARKER).write_text(session_value, encoding="utf-8")
                except OSError:
                    candidate.rmdir()
                    raise
                return candidate

        if not root.is_dir():
            return None
        base_folder = root / prefix
        for candidate in [base_folder, *sorted(root.glob(f"{prefix}-*"))]:
            if not candidate.is_dir() or candidate.is_symlink():
                continue
            marker = candidate / _SESSION_MARKER
            try:
                if marker.is_file() and marker.read_text(encoding="utf-8").strip() == session_value:
                    return candidate
            except OSError:
                continue
    return None


def session_folder_name(session_id: UUID) -> str | None:
    folder = report_session_dir(session_id)
    return folder.name if folder else None


def write_no_data_marker(job: Job) -> str:
    """Save one text marker beside the report files for this State."""
    title = job.scenario_name or f"No data for {job.filters.rtos[0] if job.filters.rtos else 'RTO'}, {job.filters.states[0] if job.filters.states else 'State'}"
    safe_title = re.sub(r'[\\/*?:"<>|\r\n\t]', "_", title).strip(". ") or "No data"
    state = job.filters.states[0] if job.filters.states else "Unknown State"
    safe_state = re.sub(r'[\\/*?:"<>|\r\n\t]', "_", state).strip(". ") or "Unknown State"
    session_dir = report_session_dir(job.session_id, create=True)
    if session_dir is None:
        raise OSError("Could not create the report session folder.")
    destination_dir = session_dir / safe_state
    destination_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{safe_title}.txt"
    temporary = destination_dir / f".{job.id}.txt.tmp"
    try:
        temporary.write_text(f"{title}\n", encoding="utf-8")
        temporary.replace(destination_dir / file_name)
    finally:
        temporary.unlink(missing_ok=True)
    return file_name


def stored_no_data_path(job: Job) -> Path | None:
    if not job.no_data_file_name or Path(job.no_data_file_name).name != job.no_data_file_name:
        return None
    session_dir = report_session_dir(job.session_id)
    if session_dir is None:
        return None
    state = job.filters.states[0] if job.filters.states else "Unknown State"
    safe_state = re.sub(r'[\\/*?:"<>|\r\n\t]', "_", state).strip(". ") or "Unknown State"
    path = (session_dir / "web-cu" / safe_state if job.source == ReportSource.OLD else session_dir / safe_state) / job.no_data_file_name
    return path if path.is_file() and not path.is_symlink() else None


def _is_stored_workbook(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _find_workbook(folder: Path, file_name: str) -> list[Path]:
    """Find a workbook in current or source-separated State folders."""
    direct = folder / file_name
    if _is_stored_workbook(direct):
        return [direct]
    matches: list[Path] = []
    if folder.is_dir():
        for child in folder.iterdir():
            if not child.is_dir() or child.is_symlink():
                continue
            candidate = child / file_name
            if _is_stored_workbook(candidate):
                matches.append(candidate)
            if child.name in {"web-cu", "web-moi"}:
                for state_dir in child.iterdir():
                    if state_dir.is_dir() and not state_dir.is_symlink():
                        candidate = state_dir / file_name
                        if _is_stored_workbook(candidate):
                            matches.append(candidate)
    return matches


def stored_excel_path(file_name: str | None, session_id: UUID | None = None) -> Path | None:
    if not file_name or Path(file_name).name != file_name or not file_name.lower().endswith(".xlsx"):
        return None

    root = Path(settings.excel_report_dir)
    if session_id is not None:
        session_dir = report_session_dir(session_id)
        if session_dir:
            matches = _find_workbook(session_dir, file_name)
            if len(matches) == 1:
                return matches[0]
        # Reports created before per-session folders were introduced remain accessible.
        legacy_path = root / file_name
        return legacy_path if _is_stored_workbook(legacy_path) else None

    legacy_path = root / file_name
    if _is_stored_workbook(legacy_path):
        return legacy_path

    # The filename contains the job UUID, so a matching file in a session folder
    # identifies one report without confusing it with another run.
    matches: list[Path] = []
    if root.is_dir():
        for folder in root.iterdir():
            if not folder.is_dir() or folder.is_symlink() or not (folder / _SESSION_MARKER).is_file():
                continue
            matches.extend(_find_workbook(folder, file_name))
    return matches[0] if len(matches) == 1 else None
