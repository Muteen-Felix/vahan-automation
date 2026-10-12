"""Estimate browser-worker capacity from the server running this launcher."""

from __future__ import annotations

import ctypes
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "--env-file", ".docker.env"]
GIB = 1024**3
DEFAULT_WORKER_MEMORY = int(1.1 * GIB)
WORKER_MEMORY_SAFETY_FACTOR = 1.4
DEFAULT_WORKER_CPUS = 1.5
ENGINE_MEMORY_RESERVE_RATIO = 0.25
MIN_ENGINE_MEMORY_RESERVE = int(1.5 * GIB)
MIN_HOST_HEADROOM = int(1.5 * GIB)
HOST_HEADROOM_RATIO = 0.10
CPU_RESERVE_RATIO = 0.15
MIN_CPU_RESERVE = 1
DEFAULT_WORKER_TARGET = 20


@dataclass(frozen=True)
class WorkerCapacityAssessment:
    host_cpus: int
    docker_cpus: int
    docker_memory_bytes: int
    host_total_memory_bytes: int | None
    host_available_memory_bytes: int | None
    current_workers: int
    observed_worker_memory_bytes: int | None
    observed_worker_cpu_cores: float | None
    estimated_worker_memory_bytes: int
    estimated_worker_cpu_cores: float
    cpu_worker_limit: int
    docker_memory_worker_limit: int
    docker_cpu_worker_limit: int
    host_worker_limit: int
    host_memory_for_next_worker_bytes: int | None
    recommended_workers: int


def _capture(command: list[str]) -> str:
    result = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _windows_memory() -> tuple[int, int] | None:
    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    try:
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
    except (AttributeError, OSError):
        return None
    return int(status.ullTotalPhys), int(status.ullAvailPhys)


def _host_memory() -> tuple[int | None, int | None]:
    if sys.platform == "win32":
        value = _windows_memory()
        return value if value else (None, None)

    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        values: dict[str, int] = {}
        for line in meminfo.read_text(encoding="ascii").splitlines():
            match = re.match(r"^(MemTotal|MemAvailable):\s+(\d+)\s+kB$", line)
            if match:
                values[match.group(1)] = int(match.group(2)) * 1024
        return values.get("MemTotal"), values.get("MemAvailable")

    try:
        total = int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        total = None
    return total, None


def _parse_size(value: str) -> int | None:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kmgt]?i?b)\s*", value, re.I)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2).lower()
    powers = {"b": 0, "kb": 1, "kib": 1, "mb": 2, "mib": 2,
              "gb": 3, "gib": 3, "tb": 4, "tib": 4}
    base = 1000 if unit.endswith("b") and "i" not in unit else 1024
    if unit == "b":
        return int(amount)
    return int(amount * base ** powers[unit])


def _current_worker_stats() -> tuple[int, int | None, float | None]:
    container_ids = _capture([*COMPOSE, "ps", "-q", "runner"]).splitlines()
    container_ids = [container_id.strip() for container_id in container_ids if container_id.strip()]
    if not container_ids:
        return 0, None, None

    output = _capture([
        "docker",
        "stats",
        "--no-stream",
        "--format",
        "{{.Container}}|{{.CPUPerc}}|{{.MemUsage}}",
        *container_ids,
    ])
    memory_samples: list[int] = []
    cpu_samples: list[float] = []
    for line in output.splitlines():
        columns = line.split("|", maxsplit=2)
        if len(columns) != 3:
            continue
        cpu = re.fullmatch(r"\s*(\d+(?:\.\d+)?)%\s*", columns[1])
        if cpu:
            cpu_samples.append(float(cpu.group(1)) / 100)
        memory_value = columns[2].split("/", maxsplit=1)[0].strip()
        memory = _parse_size(memory_value)
        if memory is not None:
            memory_samples.append(memory)
    return len(container_ids), max(memory_samples, default=None), max(cpu_samples, default=None)


def assess_worker_capacity() -> WorkerCapacityAssessment:
    """Choose up to 20 workers from server CPU and available host memory.

    Existing replicas are never removed by the recommendation. This matters
    when the launcher is used to assess a live stack that still has active jobs.
    """
    info = _capture([
        "docker",
        "info",
        "--format",
        "{{.NCPU}}|{{.MemTotal}}",
    ]).split("|", maxsplit=1)
    if len(info) != 2:
        raise RuntimeError("Docker did not return its CPU and memory capacity.")
    docker_cpus, docker_memory = int(info[0]), int(info[1])
    if docker_cpus < 1 or docker_memory < 1:
        raise RuntimeError("Docker reported invalid CPU or memory capacity.")

    current_workers, observed_worker_memory, observed_worker_cpu = _current_worker_stats()
    host_total, host_available = _host_memory()
    host_cpus = os.cpu_count()
    if not host_cpus or not host_total or host_available is None:
        raise RuntimeError("Cannot read server CPU and available RAM. Run the launcher directly on the server.")

    estimated_worker_memory = max(
        DEFAULT_WORKER_MEMORY,
        math.ceil((observed_worker_memory or 0) * WORKER_MEMORY_SAFETY_FACTOR),
    )
    estimated_worker_cpu = max(
        DEFAULT_WORKER_CPUS,
        observed_worker_cpu or 0,
    )

    cpu_reserve = max(MIN_CPU_RESERVE, math.ceil(host_cpus * CPU_RESERVE_RATIO))
    cpu_budget = max(0, host_cpus - cpu_reserve)
    cpu_limit = math.floor(cpu_budget / estimated_worker_cpu)
    if host_cpus >= 2 and cpu_limit == 0:
        cpu_limit = 1

    engine_memory_reserve = max(
        MIN_ENGINE_MEMORY_RESERVE,
        math.ceil(docker_memory * ENGINE_MEMORY_RESERVE_RATIO),
    )
    engine_memory_budget = max(0, docker_memory - engine_memory_reserve)
    docker_memory_limit = engine_memory_budget // estimated_worker_memory
    docker_cpu_budget = max(0, docker_cpus - max(MIN_CPU_RESERVE, math.ceil(docker_cpus * CPU_RESERVE_RATIO)))
    docker_cpu_limit = math.floor(docker_cpu_budget / estimated_worker_cpu)
    if docker_cpus >= 2 and docker_cpu_limit == 0:
        docker_cpu_limit = 1

    host_headroom = max(
        MIN_HOST_HEADROOM,
        math.ceil(host_total * HOST_HEADROOM_RATIO),
    )
    host_memory_for_next_worker = host_headroom + estimated_worker_memory
    additional_memory = max(0, host_available - host_headroom)
    additional_workers = additional_memory // estimated_worker_memory
    # Host availability is measured after the current stack has consumed RAM.
    host_limit = current_workers + additional_workers

    resource_limit = min(DEFAULT_WORKER_TARGET, cpu_limit, host_limit)
    # Preserve a live worker pool; the launcher may not disrupt active jobs by
    # scaling it down automatically when a fresh sample reports lower capacity.
    recommended = max(current_workers, resource_limit)
    return WorkerCapacityAssessment(
        host_cpus=host_cpus,
        docker_cpus=docker_cpus,
        docker_memory_bytes=docker_memory,
        host_total_memory_bytes=host_total,
        host_available_memory_bytes=host_available,
        current_workers=current_workers,
        observed_worker_memory_bytes=observed_worker_memory,
        observed_worker_cpu_cores=observed_worker_cpu,
        estimated_worker_memory_bytes=estimated_worker_memory,
        estimated_worker_cpu_cores=estimated_worker_cpu,
        cpu_worker_limit=cpu_limit,
        docker_memory_worker_limit=docker_memory_limit,
        docker_cpu_worker_limit=docker_cpu_limit,
        host_worker_limit=host_limit,
        host_memory_for_next_worker_bytes=host_memory_for_next_worker,
        recommended_workers=recommended,
    )


def _format_memory(value: int | None) -> str:
    return "unavailable" if value is None else f"{value / GIB:.2f} GiB"


def print_assessment(value: WorkerCapacityAssessment) -> None:
    print(f"Server worker capacity assessment (automatic target: {DEFAULT_WORKER_TARGET})")
    print(f"  Server CPU: {value.host_cpus} logical cores")
    print(
        f"  Docker Engine: {value.docker_cpus} vCPU, "
        f"{_format_memory(value.docker_memory_bytes)} RAM"
    )
    if value.host_total_memory_bytes is not None:
        print(f"  Host RAM: {_format_memory(value.host_total_memory_bytes)} total, "
              f"{_format_memory(value.host_available_memory_bytes)} available")
    print(f"  Current runners: {value.current_workers}")
    if value.observed_worker_memory_bytes is not None:
        print(
            f"  Current max runner sample: {_format_memory(value.observed_worker_memory_bytes)} RAM, "
            f"{value.observed_worker_cpu_cores or 0:.2f} CPU"
        )
    print(
        f"  Planning budget per runner: {_format_memory(value.estimated_worker_memory_bytes)} RAM, "
        f"{value.estimated_worker_cpu_cores:.2f} CPU"
    )
    print(f"  Server capacity limits: CPU={value.cpu_worker_limit}, "
          f"available RAM={value.host_worker_limit}, automatic target={DEFAULT_WORKER_TARGET}")
    docker_limit = min(value.docker_cpu_worker_limit, value.docker_memory_worker_limit)
    if value.recommended_workers > docker_limit:
        print(f"  Docker allocation supports an estimated {docker_limit} runner(s), below the server selection. "
              "Increase Docker CPU/RAM allocation before running the selected pool.")
    if (value.host_available_memory_bytes is not None
            and value.current_workers < min(DEFAULT_WORKER_TARGET, value.cpu_worker_limit)
            and value.host_memory_for_next_worker_bytes is not None):
        needed = value.host_memory_for_next_worker_bytes
        if value.host_available_memory_bytes < needed:
            shortfall = needed - value.host_available_memory_bytes
            print(
                f"  To safely add one runner: host should have {_format_memory(needed)} free; "
                f"currently short by {_format_memory(shortfall)}."
            )
        else:
            print("  Host RAM has headroom for at least one more runner.")
    resource_limit = min(
        DEFAULT_WORKER_TARGET,
        value.cpu_worker_limit,
        value.host_worker_limit,
    )
    if value.current_workers > resource_limit:
        print(
            f"  Recommended: keep {value.recommended_workers} current runners; "
            "the current pool is above the fresh resource estimate, so it will not be scaled "
            "down automatically."
        )
    else:
        print(f"  Recommended: {value.recommended_workers} runner(s).")
