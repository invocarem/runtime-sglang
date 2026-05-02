"""FastAPI wrapper: benchmark, models, presets, and optional spark_runtime launch."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse
from urllib.parse import urljoin
import logging

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

# Repo root (build-sglang) — parent of stack-ui/
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
# Add the runtime directory to path
_RUNTIME_PATH = _REPO_ROOT / "stack-cli" / "runtime"
if str(_RUNTIME_PATH) not in sys.path:
    sys.path.insert(0, str(_RUNTIME_PATH))

from spark_runtime import load_presets, run_benchmark

app = FastAPI(title="SGLang stack UI API")


class _SuppressClusterLogAccessFilter(logging.Filter):
    """Drop chatty cluster-log access lines from uvicorn access logger."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        return ("/api/cluster-log?" not in msg) and ("/api/cluster-log/stream" not in msg)


if os.environ.get("STACK_UI_SUPPRESS_CLUSTER_LOG_ACCESS", "1").strip() == "1":
    logging.getLogger("uvicorn.access").addFilter(_SuppressClusterLogAccessFilter())

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _launch_allowed() -> bool:
    return os.environ.get("STACK_UI_ALLOW_LAUNCH", "").strip() == "1"


_RUNTIME_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1"}
_DEFAULT_CLUSTER_LOG_DIR = "~/code/build-sglang/logs"


def _runtime_request_timeout_sec() -> int:
    raw = os.environ.get("SGLANG_REQUEST_TIMEOUT_MS", "120000").strip()
    try:
        ms = int(raw)
    except ValueError:
        ms = 120000
    ms = max(ms, 1000)
    return int(ms / 1000)


def _models_timeout_sec() -> int:
    raw = os.environ.get("SGLANG_MODELS_TIMEOUT_MS", "5000").strip()
    try:
        ms = int(raw)
    except ValueError:
        ms = 5000
    ms = max(ms, 1000)
    return int(ms / 1000)


def _assert_runtime_url_safe(url_string: str) -> str:
    parsed = urlparse(url_string)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=500, detail="Only http(s) URLs are allowed for SGLang upstream.")
    host = (parsed.hostname or "").lower()
    if os.environ.get("SGLANG_ALLOW_ANY_HOST", "").strip() == "1":
        return url_string
    if host not in _RUNTIME_ALLOWED_HOSTS:
        raise HTTPException(
            status_code=500,
            detail="SGLang host must be localhost/127.0.0.1/::1 (or set SGLANG_ALLOW_ANY_HOST=1).",
        )
    return url_string


def _runtime_base_url() -> str:
    base = os.environ.get("SGLANG_BASE_URL", "http://127.0.0.1:30000").strip() or "http://127.0.0.1:30000"
    return _assert_runtime_url_safe(base).rstrip("/")


def _runtime_metrics_url() -> str:
    full = os.environ.get("SGLANG_METRICS_URL", "").strip()
    if full:
        return _assert_runtime_url_safe(full)
    metrics_path = os.environ.get("SGLANG_METRICS_PATH", "/metrics")
    return urljoin(_runtime_base_url() + "/", metrics_path.lstrip("/"))


def _resolve_presets_path(presets_file: str) -> Path:
    p = Path(presets_file)
    if not p.is_absolute():
        p = _REPO_ROOT / p
    return p


def _resolve_tools_definitions_path(definitions_file: str) -> Path:
    p = Path(definitions_file)
    if not p.is_absolute():
        p = _REPO_ROOT / p
    return p


def _load_tools_definitions(definitions_file: str) -> list[dict[str, Any]]:
    path = _resolve_tools_definitions_path(definitions_file)
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Tools definitions file not found: {path}",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Invalid JSON in tools definitions: {exc}",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read tools definitions: {exc}",
        ) from exc

    tools = payload.get("tools") if isinstance(payload, dict) else None
    if not isinstance(tools, list):
        raise HTTPException(status_code=500, detail="tools definitions must contain a 'tools' array.")
    normalized: list[dict[str, Any]] = []
    for item in tools:
        if not isinstance(item, dict):
            continue
        tool_id = item.get("id")
        label = item.get("label")
        if not isinstance(tool_id, str) or not tool_id.strip():
            continue
        if not isinstance(label, str) or not label.strip():
            continue
        normalized.append(item)
    return normalized


class ToolRunRequest(BaseModel):
    tool: str = Field(..., min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)


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
    log_dir: str = _DEFAULT_CLUSTER_LOG_DIR


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


def _runtime_json_request(method: str, url: str, timeout_sec: int, body: Any | None = None) -> tuple[int, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url=url, headers=headers, method=method.upper(), data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as response:
            status = int(getattr(response, "status", 200))
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise HTTPException(status_code=exc.code, detail=f"Upstream HTTP {exc.code}: {body_text[:1000]}") from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach inference server: {exc}") from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Upstream request timed out.") from exc

    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Invalid JSON from upstream: {exc}") from exc
    return status, parsed


def _runtime_text_request(url: str, timeout_sec: int) -> tuple[int, str]:
    req = urllib.request.Request(url=url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as response:
            status = int(getattr(response, "status", 200))
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise HTTPException(status_code=exc.code, detail=f"Upstream HTTP {exc.code}: {body_text[:1000]}") from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach inference server: {exc}") from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Upstream request timed out.") from exc
    return status, raw


def _assistant_from_completion_body(payload: Any) -> str | None:
    def _content_to_text(content: Any) -> str | None:
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return None
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                if item:
                    parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
        return "".join(parts) if parts else None

    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        text = _content_to_text(content)
        if text is not None:
            return text
        reasoning = message.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning.strip():
            return reasoning
    text = first.get("text")
    if isinstance(text, str):
        return text
    return None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.head("/health")
def health_head() -> Response:
    return Response(status_code=200)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    _, models = _runtime_json_request("GET", _runtime_base_url() + "/v1/models", _models_timeout_sec())
    if not isinstance(models, dict):
        raise HTTPException(status_code=502, detail="Invalid /v1/models response.")
    return {"status": "ok"}


@app.get("/v1/models")
def runtime_models() -> Any:
    _, payload = _runtime_json_request("GET", _runtime_base_url() + "/v1/models", _models_timeout_sec())
    return payload


@app.get("/v1/metrics")
def runtime_metrics() -> dict[str, Any]:
    _status, text = _runtime_text_request(_runtime_metrics_url(), _runtime_request_timeout_sec())
    max_chars = int(os.environ.get("RUNTIME_METRICS_MAX_CHARS", "256000"))
    max_lines = int(os.environ.get("RUNTIME_METRICS_HIGHLIGHT_LINES", "500"))
    lines = [line for line in text.splitlines() if "sglang" in line.lower()][:max_lines]
    return {
        "url": _runtime_metrics_url(),
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "highlightLines": lines,
        "rawPreview": text[:max_chars],
        "rawTruncated": len(text) > max_chars,
    }


@app.post("/v1/chat/completions")
def runtime_chat_completions(body: Any = Body(...)) -> Any:
    status, payload = _runtime_json_request(
        "POST",
        _runtime_base_url() + "/v1/chat/completions",
        _runtime_request_timeout_sec(),
        body=body,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=payload)
    return payload


@app.post("/v1/benchmark/load")
def runtime_load_benchmark(body: Any = Body(...)) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Expected JSON object body.")
    model = body.get("model")
    message = body.get("message")
    requests = body.get("requests")
    concurrency = body.get("concurrency")
    max_tokens = body.get("max_tokens")
    if not isinstance(model, str) or not model.strip():
        raise HTTPException(status_code=400, detail="model must be a non-empty string.")
    if not isinstance(message, str) or not message.strip():
        raise HTTPException(status_code=400, detail="message must be a non-empty string.")
    if not isinstance(requests, int) or requests < 1:
        raise HTTPException(status_code=400, detail="requests must be an integer >= 1.")
    if not isinstance(concurrency, int) or concurrency < 1:
        raise HTTPException(status_code=400, detail="concurrency must be an integer >= 1.")
    if max_tokens is not None and (not isinstance(max_tokens, int) or max_tokens < 1):
        raise HTTPException(status_code=400, detail="max_tokens must be a positive integer.")

    max_requests = int(os.environ.get("RUNTIME_BENCHMARK_MAX_REQUESTS", "300"))
    max_concurrency = int(os.environ.get("RUNTIME_BENCHMARK_MAX_CONCURRENCY", "64"))
    if requests > max_requests:
        raise HTTPException(status_code=400, detail=f"requests must be <= {max_requests}.")
    if concurrency > max_concurrency:
        raise HTTPException(status_code=400, detail=f"concurrency must be <= {max_concurrency}.")

    latencies_ms: list[int] = []
    errors: list[str] = []
    success = 0
    fail = 0
    sample_content: str | None = None

    def one_request(index: int) -> tuple[int, int, str | None, str | None]:
        started = time.perf_counter()
        try:
            _, payload = _runtime_json_request(
                "POST",
                _runtime_base_url() + "/v1/chat/completions",
                _runtime_request_timeout_sec(),
                body={
                    "model": model,
                    "messages": [{"role": "user", "content": message}],
                    "max_tokens": max_tokens,
                    "separate_reasoning": False,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
            latency = int((time.perf_counter() - started) * 1000)
            content = _assistant_from_completion_body(payload)
            if content is None:
                return index, latency, None, "Upstream completion response did not contain assistant text."
            return index, latency, content, None
        except HTTPException as exc:
            latency = int((time.perf_counter() - started) * 1000)
            return index, latency, None, str(exc.detail)

    started = time.perf_counter()
    workers = min(requests, concurrency)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one_request, i) for i in range(requests)]
        for fut in as_completed(futures):
            idx, latency, content, err = fut.result()
            latencies_ms.append(latency)
            if content is not None:
                success += 1
                if idx == 0:
                    sample_content = content
            else:
                fail += 1
                if err and len(errors) < 8:
                    errors.append(err)

    wall_ms = int((time.perf_counter() - started) * 1000)
    sorted_latencies = sorted(latencies_ms)

    def percentile(p: int) -> int:
        if not sorted_latencies:
            return 0
        idx = max(0, min(len(sorted_latencies) - 1, int((p / 100) * len(sorted_latencies)) - 1))
        return sorted_latencies[idx]

    throughput_rps = (success / (wall_ms / 1000)) if wall_ms > 0 else 0.0
    return {
        "model": model,
        "requests": requests,
        "concurrency": min(requests, concurrency),
        "successes": success,
        "failures": fail,
        "wallTimeMs": wall_ms,
        "p50": percentile(50),
        "p95": percentile(95),
        "p99": percentile(99),
        "throughputRps": throughput_rps,
        "errorSamples": errors,
        "sampleContent": sample_content,
    }


def _run_task_checker(text: str, checker: dict[str, Any]) -> tuple[bool, str]:
    checker_type = checker.get("type")
    if checker_type == "regex":
        pattern = checker.get("pattern")
        flags_text = checker.get("flags", "")
        if not isinstance(pattern, str):
            return False, "regex checker requires string pattern"
        flags = 0
        if isinstance(flags_text, str) and "i" in flags_text:
            flags |= re.IGNORECASE
        try:
            matched = re.search(pattern, text, flags=flags) is not None
        except re.error as exc:
            return False, f"invalid regex: {exc}"
        return (True, "regex ok") if matched else (False, "regex did not match")
    if checker_type == "contains":
        value = checker.get("value")
        if not isinstance(value, str):
            return False, "contains checker requires string value"
        case_insensitive = checker.get("case_insensitive") is True
        hay = text.lower() if case_insensitive else text
        needle = value.lower() if case_insensitive else value
        return (True, "contains ok") if needle in hay else (False, "missing substring")
    if checker_type == "contains_all":
        values = checker.get("values")
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            return False, "contains_all checker requires string values[]"
        case_insensitive = checker.get("case_insensitive") is True
        hay = text.lower() if case_insensitive else text
        for item in values:
            needle = item.lower() if case_insensitive else item
            if needle not in hay:
                return False, f"missing {needle}"
        return True, "contains_all ok"
    return False, "unknown checker type"


@app.post("/v1/benchmark/task")
def runtime_task_benchmark(body: Any = Body(...)) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Expected JSON object body.")
    model = body.get("model")
    tasks = body.get("tasks")
    temperature = body.get("temperature", 0.2)
    max_tokens = body.get("max_tokens", 1024)

    if not isinstance(model, str) or not model.strip():
        raise HTTPException(status_code=400, detail="model must be a non-empty string.")
    if not isinstance(tasks, list) or not tasks:
        raise HTTPException(status_code=400, detail="tasks must be a non-empty array.")
    if not isinstance(temperature, (float, int)):
        raise HTTPException(status_code=400, detail="temperature must be numeric.")
    if not isinstance(max_tokens, int) or max_tokens < 1:
        raise HTTPException(status_code=400, detail="max_tokens must be a positive integer.")

    by_category: dict[str, dict[str, int]] = {}
    results: list[dict[str, Any]] = []
    started = time.perf_counter()

    for task in tasks:
        if not isinstance(task, dict):
            raise HTTPException(status_code=400, detail="each task must be an object.")
        task_id = task.get("id")
        category = task.get("category")
        prompt = task.get("prompt")
        checker = task.get("checker")
        system = task.get("system")
        if not isinstance(task_id, str) or not isinstance(category, str) or not isinstance(prompt, str):
            raise HTTPException(status_code=400, detail="task requires string id/category/prompt.")
        if not isinstance(checker, dict):
            raise HTTPException(status_code=400, detail="task.checker must be an object.")
        if system is not None and not isinstance(system, str):
            raise HTTPException(status_code=400, detail="task.system must be a string when provided.")

        messages: list[dict[str, str]] = []
        if isinstance(system, str) and system.strip():
            messages.append({"role": "system", "content": system.strip()})
        messages.append({"role": "user", "content": prompt.strip()})

        task_started = time.perf_counter()
        try:
            _, payload = _runtime_json_request(
                "POST",
                _runtime_base_url() + "/v1/chat/completions",
                _runtime_request_timeout_sec(),
                body={
                    "model": model,
                    "messages": messages,
                    "temperature": float(temperature),
                    "max_tokens": max_tokens,
                    "separate_reasoning": False,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
            output = _assistant_from_completion_body(payload) or ""
            ok, reason = _run_task_checker(output, checker)
        except HTTPException as exc:
            ok = False
            reason = str(exc.detail)

        latency_ms = int((time.perf_counter() - task_started) * 1000)
        bucket = by_category.setdefault(category, {"pass": 0, "fail": 0})
        if ok:
            bucket["pass"] += 1
        else:
            bucket["fail"] += 1
        results.append(
            {
                "id": task_id,
                "category": category,
                "ok": ok,
                "reason": reason,
                "latencyMs": latency_ms,
            },
        )

    passed = sum(1 for r in results if r["ok"])
    total = len(results)
    return {
        "model": model,
        "cases": total,
        "passed": passed,
        "failed": total - passed,
        "passRate": round((passed / total), 4) if total else 0,
        "wallTimeMs": int((time.perf_counter() - started) * 1000),
        "byCategory": by_category,
        "results": results,
    }


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


def _tool_script_path(script_name: str) -> Path:
    return _REPO_ROOT / "stack-cli" / "tools" / script_name


def _to_cli_flag(name: str) -> str:
    return "--" + name.strip().replace("_", "-")


def _tool_arg_value(args: dict[str, Any], name: str) -> Any:
    normalized = name.strip().lstrip("-")
    underscored = normalized.replace("-", "_")
    dashed = normalized.replace("_", "-")
    for key in (
        normalized,
        underscored,
        dashed,
        _to_cli_flag(normalized),
        _to_cli_flag(underscored),
        _to_cli_flag(dashed),
    ):
        if key in args and args[key] is not None:
            return args[key]
    return None


_HF_ID_PART_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _infer_hf_repo_from_candidate(candidate: str) -> str:
    raw = (candidate or "").strip()
    if not raw:
        return ""
    base = os.path.basename(raw.rstrip("/")) or raw
    if "/" in base or "_" not in base:
        return ""
    org, repo = base.split("_", 1)
    if not org or not repo:
        return ""
    if not _HF_ID_PART_RE.fullmatch(org):
        return ""
    if not _HF_ID_PART_RE.fullmatch(repo):
        return ""
    return f"{org}/{repo}"


def _derive_benchmark_hf_model(args: dict[str, Any]) -> str:
    # Respect explicit user-provided tokenizer/hf_model first.
    if _tool_arg_value(args, "hf_model") or _tool_arg_value(args, "tokenizer"):
        return ""

    model_value = _tool_arg_value(args, "model")
    model = model_value.strip() if isinstance(model_value, str) else ""
    if not model:
        return ""
    if "/" in model:
        return model

    # Try direct conversion from model id/path basename, e.g. Qwen_Qwen3.6-27B -> Qwen/Qwen3.6-27B.
    guessed = _infer_hf_repo_from_candidate(model)
    if guessed:
        return guessed

    # If model is a preset key, attempt conversion from preset model_path basename.
    try:
        presets = load_presets(str(_resolve_presets_path("model_presets.json")))
    except Exception:
        presets = {}
    cfg = presets.get(model) if isinstance(presets, dict) else None
    if isinstance(cfg, dict):
        model_path = cfg.get("model_path")
        if isinstance(model_path, str):
            return _infer_hf_repo_from_candidate(model_path)
    return ""


def _run_tool_script(script_name: str, cli_args: list[str], timeout_sec: int = 900) -> dict[str, Any]:
    script_path = _tool_script_path(script_name)
    if not script_path.is_file():
        raise HTTPException(status_code=404, detail=f"Tool script not found: {script_path}")

    py_exec = _tool_python_executable(script_name)
    cmd = [py_exec, str(script_path), *cli_args]
    env = _tool_script_env(script_name)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=max(1, timeout_sec),
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail=f"Tool timed out after {timeout_sec}s: {script_name}") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to run tool script: {exc}") from exc

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    parsed_output: Any = stdout
    if stdout:
        try:
            parsed_output = json.loads(stdout)
        except json.JSONDecodeError:
            parsed_output = stdout

    if proc.returncode != 0:
        error_msg = f"{script_name} exited with code {proc.returncode}"
        if stderr:
            error_msg = f"{error_msg}: {stderr}"
        return {
            "ok": False,
            "error": error_msg,
            "output": {
                "exit_code": proc.returncode,
                "stdout": parsed_output,
                "stderr": stderr,
                "command": cmd,
            },
        }

    output: dict[str, Any] = {"result": parsed_output}
    if stderr:
        output["stderr"] = stderr
    return {"ok": True, "output": output}


def _tool_python_executable(script_name: str) -> str:
    if script_name not in {"benchmark_sglang.py", "task_benchmark.py"}:
        return sys.executable
    for env_key in ("STACK_UI_BENCHMARK_PYTHON", "BENCHMARK_PYTHON"):
        raw = os.environ.get(env_key, "").strip()
        if not raw:
            continue
        expanded = os.path.expanduser(raw)
        if os.path.isfile(expanded) and os.access(expanded, os.X_OK):
            return expanded
    default_bench = os.path.expanduser("~/.sglang/bin/python")
    if os.path.isfile(default_bench) and os.access(default_bench, os.X_OK):
        return default_bench
    return sys.executable


def _tool_script_env(script_name: str) -> dict[str, str]:
    env = os.environ.copy()
    if script_name not in {"benchmark_sglang.py", "task_benchmark.py"}:
        return env
    local_sglang_python = str(_REPO_ROOT / "sglang" / "python")
    old_pythonpath = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = (
        f"{local_sglang_python}:{old_pythonpath}" if old_pythonpath else local_sglang_python
    )
    return env


def _shell_quote_path_allow_home(path: str) -> str:
    if path == "~":
        return "$HOME"
    if path.startswith("~/"):
        return "$HOME/" + shlex.quote(path[2:])
    return shlex.quote(path)


_CLUSTER_HOST_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _validate_cluster_host(host: str) -> str:
    clean = host.strip()
    if not clean:
        raise HTTPException(status_code=400, detail="host is required.")
    if not _CLUSTER_HOST_RE.fullmatch(clean):
        raise HTTPException(status_code=400, detail="host contains invalid characters.")
    return clean


def _read_remote_cluster_log_tail(host: str, node_rank: int, tail_bytes: int, log_dir: str) -> dict[str, Any]:
    safe_host = _validate_cluster_host(host)
    if node_rank < 0:
        raise HTTPException(status_code=400, detail="node_rank must be >= 0.")
    log_dir_clean = (log_dir or "").strip() or _DEFAULT_CLUSTER_LOG_DIR
    remote_path = f"{log_dir_clean.rstrip('/')}/sglang_node{node_rank}.log"
    quoted_path = _shell_quote_path_allow_home(remote_path)
    tail_cmd = (
        f"if [ -f {quoted_path} ]; then "
        f"echo __STACK_UI_FILE_EXISTS__ && tail -c {tail_bytes} {quoted_path}; "
        "fi"
    )
    r = subprocess.run(
        ["ssh", safe_host, f"bash -lc {shlex.quote(tail_cmd)}"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if r.returncode != 0:
        stderr = (r.stderr or "").strip()
        return {
            "host": safe_host,
            "node_rank": node_rank,
            "path": remote_path,
            "exists": False,
            "tail_bytes": tail_bytes,
            "content": "",
            "error": stderr or f"ssh exited with code {r.returncode}",
        }
    marker = "__STACK_UI_FILE_EXISTS__"
    stdout = r.stdout or ""
    file_exists = marker in stdout
    content = stdout.replace(f"{marker}\n", "", 1) if file_exists else ""
    return {
        "host": safe_host,
        "node_rank": node_rank,
        "path": remote_path,
        "exists": file_exists,
        "tail_bytes": tail_bytes,
        "content": content,
    }


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


@app.get("/api/cluster-log")
def api_cluster_log(
    host: str = Query(..., description="Cluster host, e.g. spark1"),
    node_rank: int = Query(0, ge=0),
    tail_bytes: int = Query(
        131_072,
        ge=1,
        le=2_000_000,
        description="Return at most this many bytes from the end of remote node log",
    ),
    log_dir: str = Query(
        _DEFAULT_CLUSTER_LOG_DIR,
        description="Remote directory containing sglang_node{rank}.log",
    ),
) -> dict[str, Any]:
    return _read_remote_cluster_log_tail(host, node_rank, tail_bytes, log_dir)


@app.get("/api/cluster-log/stream")
async def api_cluster_log_stream(
    host: str = Query(..., description="Cluster host, e.g. spark1"),
    node_rank: int = Query(0, ge=0),
    tail_bytes: int = Query(
        131_072,
        ge=1,
        le=2_000_000,
        description="Return at most this many bytes from the end of remote node log on each event",
    ),
    log_dir: str = Query(
        _DEFAULT_CLUSTER_LOG_DIR,
        description="Remote directory containing sglang_node{rank}.log",
    ),
) -> StreamingResponse:
    safe_host = _validate_cluster_host(host)

    async def event_generator() -> AsyncIterator[str]:
        last_printed = json.dumps(_read_remote_cluster_log_tail(safe_host, node_rank, tail_bytes, log_dir))
        yield f"data: {last_printed}\n\n"
        since_ping = 0.0
        while True:
            await asyncio.sleep(LAUNCH_LOG_STREAM_POLL_SEC)
            since_ping += LAUNCH_LOG_STREAM_POLL_SEC
            cur_payload = json.dumps(_read_remote_cluster_log_tail(safe_host, node_rank, tail_bytes, log_dir))
            if cur_payload != last_printed:
                last_printed = cur_payload
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


@app.get("/api/tools/definitions")
def api_tools_definitions(
    definitions_file: str = Query(
        "definitions.json",
        description="Path to JSON tool definitions (relative to repo root unless absolute)",
    ),
) -> dict[str, Any]:
    tools = _load_tools_definitions(definitions_file)
    return {"tools": tools}


@app.post("/api/tools/run")
def api_tools_run(req: ToolRunRequest) -> dict[str, Any]:
    tool = req.tool.strip()
    args = req.args

    try:
        if tool == "health":
            body = healthz()
            return {"ok": True, "output": {"status": 200, "body": body}}

        if tool == "models":
            output = runtime_models()
            return {"ok": True, "output": output}

        if tool == "metrics_snapshot":
            output = runtime_metrics()
            lines = output.get("highlightLines")
            if isinstance(lines, list):
                output = {**output, "highlightLines": lines[:30]}
            return {"ok": True, "output": output}

        if tool == "chat_smoke":
            model = str(args.get("model", ""))
            prompt = str(args.get("prompt", "hello"))
            try:
                temperature = float(args.get("temperature", 0.2))
            except (TypeError, ValueError):
                temperature = 0.2
            try:
                max_tokens = int(args.get("max_tokens", 64))
            except (TypeError, ValueError):
                max_tokens = 64

            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            output = runtime_chat_completions(payload)
            return {"ok": True, "output": output}

        if tool == "benchmark_load":
            cli_args: list[str] = []
            raw_argv = args.get("argv")
            if isinstance(raw_argv, list) and all(isinstance(x, str) for x in raw_argv):
                cli_args.extend(raw_argv)
            else:
                for key in (
                    "base_url",
                    "backend",
                    "dataset_name",
                    "num_prompts",
                    "random_input_len",
                    "random_output_len",
                    "max_concurrency",
                    "model",
                    "hf_model",
                    "tokenizer",
                ):
                    value = _tool_arg_value(args, key)
                    if value is None:
                        continue
                    cli_args.extend([_to_cli_flag(key), str(value)])
                extra_request_body = _tool_arg_value(args, "extra_request_body")
                if isinstance(extra_request_body, dict):
                    cli_args.extend(["--extra-request-body", json.dumps(extra_request_body)])
                elif isinstance(extra_request_body, str) and extra_request_body.strip():
                    cli_args.extend(["--extra-request-body", extra_request_body.strip()])
                derived_hf = _derive_benchmark_hf_model(args)
                if derived_hf:
                    cli_args.extend(["--hf-model", derived_hf])
            return _run_tool_script("benchmark_sglang.py", cli_args)

        if tool == "benchmark_task":
            cli_args = []
            raw_argv = args.get("argv")
            if isinstance(raw_argv, list) and all(isinstance(x, str) for x in raw_argv):
                cli_args.extend(raw_argv)
            else:
                for key in ("input", "base_url", "model", "temperature", "max_tokens", "timeout"):
                    value = _tool_arg_value(args, key)
                    if value is None:
                        continue
                    cli_args.extend([_to_cli_flag(key), str(value)])
            return _run_tool_script("task_benchmark.py", cli_args)

        return {"ok": False, "error": f"Unknown tool '{tool}'."}
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail, default=str)
        return {"ok": False, "error": f"HTTP {exc.status_code}: {detail}", "output": exc.detail}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


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

    spark_py = _REPO_ROOT / "stack-cli" / "runtime" / "spark_runtime.py"
    if not spark_py.is_file():
        raise HTTPException(status_code=500, detail=f"Missing runtime script at {spark_py}")

    cmd: list[str] = [
        sys.executable,
        "-u",
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
