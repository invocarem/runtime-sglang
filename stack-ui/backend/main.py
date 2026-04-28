"""FastAPI wrapper: benchmark, models, presets, and optional spark_runtime launch."""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

# Repo root (build-sglang) — parent of stack-ui/
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spark_runtime import load_presets, run_benchmark

app = FastAPI(title="SGLang stack UI API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _launch_allowed() -> bool:
    return os.environ.get("STACK_UI_ALLOW_LAUNCH", "").strip() == "1"


def _resolve_presets_path(presets_file: str) -> Path:
    p = Path(presets_file)
    if not p.is_absolute():
        p = _REPO_ROOT / p
    return p


def _preset_public_summary(cfg: dict[str, object]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("model_path", "venv_path"):
        v = cfg.get(key)
        if isinstance(v, str):
            out[key] = v
    for key in ("tp", "port"):
        v = cfg.get(key)
        if isinstance(v, int):
            out[key] = v
        elif isinstance(v, str) and v.isdigit():
            out[key] = int(v)
    return out


class BenchmarkRequest(BaseModel):
    base_url: str = Field(default="http://127.0.0.1:30000")
    api_key: str = Field(default="EMPTY")
    model: str = Field(default="default")
    prompt: str = Field(default="Write a short haiku about distributed inference.")
    max_tokens: int = Field(default=64, ge=1)
    requests: int = Field(default=20, ge=1)
    timeout_sec: int = Field(default=120, ge=1)


class LaunchRequest(BaseModel):
    preset: str = Field(..., min_length=1)
    mode: Literal["solo", "cluster"] = "solo"
    host: str = ""
    hosts: str = ""
    presets_file: str = "model_presets.json"
    env_file: str = ""
    log_file: str = "sglang_solo.log"
    dist_addr: str = "spark-01:20000"
    log_dir: str = "~/runtime-sglang/logs"


class StopRequest(BaseModel):
    base_url: str | None = Field(
        default=None,
        description=(
            "Inference base URL (same as Refresh models). When launch.pid is missing, only "
            "the URL's TCP port is used to locate listeners on this machine (hostname is ignored)."
        ),
    )


def _extract_model_ids(payload: dict[str, Any]) -> list[str]:
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    ids: list[str] = []
    for item in data:
        if isinstance(item, dict):
            mid = item.get("id")
            if isinstance(mid, str):
                ids.append(mid)
    return ids


def fetch_openai_models(base_url: str, api_key: str, timeout_sec: int) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/v1/models"
    req = urllib.request.Request(
        url=url,
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise HTTPException(
            status_code=exc.code,
            detail=f"Upstream /v1/models HTTP {exc.code}: {body[:500]}",
        ) from exc
    except urllib.error.URLError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not reach inference server: {exc}",
        ) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Upstream request timed out.") from exc

    try:
        parsed: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Invalid JSON from /v1/models: {exc}",
        ) from exc

    if not isinstance(parsed, dict):
        raise HTTPException(status_code=502, detail="/v1/models returned non-object JSON.")

    return {
        "model_ids": _extract_model_ids(parsed),
        "upstream": parsed,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.head("/health")
def health_head() -> Response:
    return Response(status_code=200)


def _launch_log_path() -> Path:
    return _REPO_ROOT / "stack-ui" / "logs" / "launch.log"


def _launch_pid_path() -> Path:
    return _REPO_ROOT / "stack-ui" / "logs" / "launch.pid"


def _write_launch_pid(pid: int) -> None:
    path = _launch_pid_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid), encoding="utf-8")


def _read_launch_pid() -> int | None:
    path = _launch_pid_path()
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return int(raw)
    except (OSError, ValueError):
        return None


def _signal_launch_tree(pid: int) -> None:
    """Try SIGTERM on the process group, then on pid alone."""
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)
        return
    except ProcessLookupError:
        return
    except PermissionError:
        pass
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def _port_and_host_from_base_url(base_url: str) -> tuple[int, str] | None:
    try:
        parsed = urlparse(base_url.strip())
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    host = parsed.hostname
    if not host:
        return None
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return port, host


def _pids_listening_on_tcp_port(port: int) -> list[int]:
    """Return PIDs that have TCP LISTEN on ``port`` (Linux; best-effort)."""
    collected: list[int] = []
    for args in (
        ["lsof", "-w", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
        ["lsof", "-w", "-t", f"-i:{port}", "-sTCP:LISTEN"],
    ):
        try:
            r = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            continue
        if r.returncode != 0:
            continue
        for part in r.stdout.split():
            if part.isdigit():
                collected.append(int(part))
        if collected:
            break
    if not collected:
        try:
            r = subprocess.run(
                ["ss", "-lntp", "sport", "=", f":{port}"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except FileNotFoundError:
            r = None
        if r is not None and r.returncode == 0:
            for m in re.finditer(r"pid=(\d+)", r.stdout):
                collected.append(int(m.group(1)))

    seen: set[int] = set()
    ordered: list[int] = []
    for p in collected:
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered


def _read_file_tail(path: Path, max_bytes: int) -> str:
    if not path.is_file():
        return ""
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    try:
        with open(path, "rb") as f:
            if size <= max_bytes:
                raw = f.read()
            else:
                f.seek(size - max_bytes)
                raw = f.read()
    except OSError:
        return ""
    return raw.decode("utf-8", errors="replace")


def _launch_log_fingerprint(path: Path) -> tuple[int, int] | None:
    """Change when the file is created, removed, truncated, or appended to (no extra deps; works on NFS)."""
    if not path.is_file():
        return None
    try:
        st = path.stat()
        return (int(st.st_mtime_ns), st.st_size)
    except OSError:
        return None


@app.get("/api/launch-log")
def api_launch_log(
    tail_bytes: int = Query(
        131_072,
        ge=1,
        le=2_000_000,
        description="Return at most this many bytes from the end of launch.log",
    ),
) -> dict[str, Any]:
    """Read stack-ui/logs/launch.log (tail) for display in the starter UI."""
    path = _launch_log_path()
    content = _read_file_tail(path, tail_bytes)
    return {
        "path": str(path),
        "exists": path.is_file(),
        "tail_bytes": tail_bytes,
        "content": content,
    }


LAUNCH_LOG_STREAM_POLL_SEC = 0.25
LAUNCH_LOG_STREAM_PING_SEC = 20.0


@app.get("/api/launch-log/stream")
async def api_launch_log_stream(
    tail_bytes: int = Query(
        131_072,
        ge=1,
        le=2_000_000,
        description="Return at most this many bytes from the end of launch.log on each event",
    ),
) -> StreamingResponse:
    """Server-Sent Events: stream the log tail whenever mtime/size changes (stat polling, no watchdog)."""

    async def event_generator() -> AsyncIterator[str]:
        path = _launch_log_path()
        last_printed: str = json.dumps(
            {
                "path": str(path),
                "exists": path.is_file(),
                "tail_bytes": tail_bytes,
                "content": _read_file_tail(path, tail_bytes),
            },
        )
        last_fp = _launch_log_fingerprint(path)
        yield f"data: {last_printed}\n\n"
        since_ping = 0.0
        while True:
            await asyncio.sleep(LAUNCH_LOG_STREAM_POLL_SEC)
            since_ping += LAUNCH_LOG_STREAM_POLL_SEC
            cur = _launch_log_fingerprint(path)
            if cur != last_fp:
                last_fp = cur
                last_printed = json.dumps(
                    {
                        "path": str(path),
                        "exists": path.is_file(),
                        "tail_bytes": tail_bytes,
                        "content": _read_file_tail(path, tail_bytes),
                    },
                )
                since_ping = 0.0
                yield f"data: {last_printed}\n\n"
            elif since_ping >= LAUNCH_LOG_STREAM_PING_SEC:
                since_ping = 0.0
                yield ": ping\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/models")
def list_models(
    base_url: str = Query(..., description="OpenAI-compatible server base URL"),
    api_key: str = Query("EMPTY"),
    timeout_sec: int = Query(30, ge=1, le=300),
) -> dict[str, Any]:
    return fetch_openai_models(base_url, api_key, timeout_sec)


@app.get("/api/presets")
def api_presets(
    presets_file: str = Query(
        "model_presets.json",
        description="Path to JSON presets (relative to repo root unless absolute)",
    ),
) -> dict[str, Any]:
    path = _resolve_presets_path(presets_file)
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Presets file not found: {path}",
        )
    try:
        presets = load_presets(str(path))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    summaries = {
        name: _preset_public_summary(cfg)
        for name, cfg in presets.items()
    }
    return {
        "presets_file": str(path),
        "preset_names": sorted(presets.keys()),
        "presets": summaries,
        "launch_enabled": _launch_allowed(),
        "launch_hint": "Start the API with STACK_UI_ALLOW_LAUNCH=1 to enable launching from the UI.",
    }


@app.post("/api/launch")
def api_launch(req: LaunchRequest) -> dict[str, Any]:
    if not _launch_allowed():
        raise HTTPException(
            status_code=403,
            detail="Launch is disabled. Set environment variable STACK_UI_ALLOW_LAUNCH=1 on the stack-ui backend.",
        )

    presets_path = _resolve_presets_path(req.presets_file)
    if not presets_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Presets file not found: {presets_path}",
        )
    try:
        presets = load_presets(str(presets_path))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if req.preset not in presets:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown preset '{req.preset}'. Available: {', '.join(sorted(presets))}",
        )

    spark_py = _REPO_ROOT / "spark_runtime.py"
    if not spark_py.is_file():
        raise HTTPException(status_code=500, detail=f"Missing spark_runtime.py at {spark_py}")

    cmd: list[str] = [
        sys.executable,
        str(spark_py),
        "launch",
        "--preset",
        req.preset,
        "--mode",
        req.mode,
        "--presets-file",
        str(presets_path),
        "--log-file",
        req.log_file,
    ]

    if req.env_file.strip():
        ef = Path(req.env_file.strip())
        if not ef.is_absolute():
            ef = _REPO_ROOT / ef
        if not ef.is_file():
            raise HTTPException(status_code=400, detail=f"Env file not found: {ef}")
        cmd.extend(["--env-file", str(ef)])

    if req.mode == "solo":
        if req.host.strip():
            cmd.extend(["--host", req.host.strip()])
    else:
        host_list = [h.strip() for h in req.hosts.replace(",", " ").split() if h.strip()]
        if not host_list:
            raise HTTPException(
                status_code=400,
                detail="Cluster launch requires at least one host (comma-separated).",
            )
        cmd.append("--hosts")
        cmd.extend(host_list)
        cmd.extend(["--dist-addr", req.dist_addr])
        cmd.extend(["--log-dir", req.log_dir])

    log_dir = _launch_log_path().parent
    log_dir.mkdir(parents=True, exist_ok=True)
    launch_log = _launch_log_path()

    try:
        with open(launch_log, "ab", buffering=0) as lf:
            lf.write(
                f"\n--- launch preset={req.preset} mode={req.mode} ---\n".encode(),
            )
            lf.flush()
            proc = subprocess.Popen(
                cmd,
                cwd=str(_REPO_ROOT),
                stdout=lf,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=os.environ.copy(),
            )
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start process: {exc}") from exc

    _write_launch_pid(proc.pid)

    return {
        "pid": proc.pid,
        "command": cmd,
        "cwd": str(_REPO_ROOT),
        "log_file": str(launch_log),
        "note": "Child process runs spark_runtime launch (sglang stays up until stopped).",
    }


@app.post("/api/stop")
def api_stop(req: StopRequest = Body(default_factory=StopRequest)) -> dict[str, Any]:
    """Stop inference: prefer ``launch.pid`` from UI Launch; else SIGTERM local listeners on the port parsed from ``base_url``."""
    recorded = _read_launch_pid()
    path = _launch_pid_path()

    if recorded is not None:
        try:
            _signal_launch_tree(recorded)
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        return {
            "stopped_pids": [recorded],
            "method": "launch_pid_file",
            "note": "Sent SIGTERM using PID recorded when Launch ran.",
        }

    raw_url = (req.base_url or "").strip()
    if not raw_url:
        raise HTTPException(
            status_code=400,
            detail=(
                "No stack-ui/logs/launch.pid on disk. Send base_url in the request body "
                "(same URL as Benchmark / Refresh models) to stop whatever is listening on that port locally, "
                "or stop the server manually."
            ),
        )

    parsed = _port_and_host_from_base_url(raw_url)
    if parsed is None:
        raise HTTPException(status_code=400, detail="Invalid base_url; expected http(s) URL with host.")
    port, _host = parsed

    pids = _pids_listening_on_tcp_port(port)
    if not pids:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No local TCP listener found on port {port}. "
                "If inference runs on another host or inside a container namespace, stop it there."
            ),
        )

    for pid in pids:
        _signal_launch_tree(pid)

    return {
        "stopped_pids": pids,
        "method": "port_listen",
        "port": port,
        "note": (
            f"Sent SIGTERM to local PID(s) listening on TCP port {port} "
            "(no launch.pid was present; hostname in base_url is not used—only the port)."
        ),
    }


@app.post("/api/benchmark")
def benchmark(req: BenchmarkRequest) -> dict[str, float | int]:
    result = run_benchmark(
        base_url=req.base_url,
        api_key=req.api_key,
        model=req.model,
        prompt=req.prompt,
        max_tokens=req.max_tokens,
        requests=req.requests,
        timeout_sec=req.timeout_sec,
    )
    if result is None:
        raise HTTPException(
            status_code=502,
            detail="No successful benchmark requests.",
        )
    return result
