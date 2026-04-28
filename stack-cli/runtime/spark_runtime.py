#!/usr/bin/env python3
"""Manage custom sglang runtime across DGX Spark nodes.

This tool provides practical operations:
- deploy: sync source/runtime files to one or more remote nodes
- launch: start sglang server locally or remotely
- stop: stop launched sglang server locally or remotely
- benchmark: run simple latency/throughput benchmark via OpenAI-compatible API
- measure: capture GPU/CPU/memory snapshots (local or remote)
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from statistics import mean

VERBOSE = False


def debug_log(message: str) -> None:
    if VERBOSE:
        print(f"[verbose] {message}", file=sys.stderr)


def format_command(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def run_cmd(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    debug_log(f"running command: {format_command(command)}")
    result = subprocess.run(command, text=True, check=check, capture_output=True)
    debug_log(f"command exit code: {result.returncode}")
    if result.stdout.strip():
        debug_log(f"stdout:\n{result.stdout.strip()}")
    if result.stderr.strip():
        debug_log(f"stderr:\n{result.stderr.strip()}")
    return result


def run_shell(command: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run_cmd(["bash", "-lc", command], check=check)


def run_remote(host: str, remote_command: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    quoted = shlex.quote(remote_command)
    return run_cmd(["ssh", host, f"bash -lc {quoted}"], check=check)


def load_dotenv(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip("'").strip('"')
            if key:
                values[key] = val
    return values


def load_env_from_args(args: argparse.Namespace) -> dict[str, str]:
    loaded: dict[str, str] = {}
    env_file = getattr(args, "env_file", "")
    if env_file:
        loaded.update(load_dotenv(env_file))
        return loaded

    default_env_file = ".env"
    if os.path.isfile(default_env_file):
        loaded.update(load_dotenv(default_env_file))
    return loaded


def env_get(env: dict[str, str], key: str, default: str) -> str:
    return env.get(key, os.environ.get(key, default))


def env_lookup(env: dict[str, str], key: str) -> str | None:
    value = env.get(key, os.environ.get(key))
    if value is None or value == "":
        return None
    return value


def load_presets(path: str) -> dict[str, dict[str, object]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("presets file must be a JSON object keyed by preset name")
    normalized: dict[str, dict[str, object]] = {}
    for name, config in data.items():
        if not isinstance(name, str):
            raise ValueError("preset names must be strings")
        if not isinstance(config, dict):
            raise ValueError(f"preset '{name}' must map to an object")
        normalized[name] = config
    return normalized


def get_preset_string(preset: dict[str, object], key: str) -> str | None:
    value = preset.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"preset key '{key}' must be a string")
    return value


def get_preset_int(preset: dict[str, object], key: str) -> int | None:
    value = preset.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"preset key '{key}' must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise ValueError(f"preset key '{key}' must be an integer")


def get_preset_sglang_args(preset: dict[str, object]) -> list[str]:
    value = preset.get("sglang_args")
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("preset key 'sglang_args' must be a list")
    args: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("preset key 'sglang_args' must contain strings only")
        args.append(item)
    return args


def get_preset_csv_or_list(preset: dict[str, object], key: str) -> str | None:
    value = preset.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError(f"preset key '{key}' list must contain strings only")
            items.append(item)
        return ",".join(items)
    raise ValueError(f"preset key '{key}' must be a string or list of strings")


def parse_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def normalize_local_sources(items: list[str]) -> list[str]:
    normalized: list[str] = []
    for item in items:
        expanded = os.path.expandvars(os.path.expanduser(item))
        normalized.append(expanded)
    return normalized


def resolve_value(
    cli_value: str | int | None,
    env_value: str | None,
    preset_value: str | int | None,
    default_value: str | int,
) -> str | int:
    if cli_value is not None:
        return cli_value
    if env_value is not None:
        return env_value
    if preset_value is not None:
        return preset_value
    return default_value


def resolve_tp(
    args_tp: int | None,
    env: dict[str, str],
    preset: dict[str, object],
    preset_name: str,
) -> int:
    """Pick tensor-parallel width for **cluster** launch.

    Solo mode ignores preset/env here: see ``launch()`` (solo uses ``tp=1`` unless
    ``--tp`` is passed). With ``--preset``, the preset's ``tp`` overrides ``TP_SIZE``
    unless ``--tp`` is passed explicitly.
    """
    if args_tp is not None:
        return int(args_tp)
    preset_tp = get_preset_int(preset, "tp")
    env_tp = env_lookup(env, "TP_SIZE")
    if preset_name.strip():
        if preset_tp is not None:
            return int(preset_tp)
        if env_tp is not None:
            return int(env_tp)
        return 1
    if env_tp is not None:
        return int(env_tp)
    if preset_tp is not None:
        return int(preset_tp)
    return 1


def build_export_prefix(env: dict[str, str], keys: list[str]) -> str:
    pairs = []
    for key in keys:
        if key in env:
            pairs.append(f"export {key}={shlex.quote(env[key])}")
    if not pairs:
        return ""
    return " && ".join(pairs) + " && "


def shell_quote_path_allow_home(path: str) -> str:
    """Quote shell path while preserving remote HOME expansion for ~/."""
    if path == "~":
        return "$HOME"
    if path.startswith("~/"):
        return "$HOME/" + shlex.quote(path[2:])
    return shlex.quote(path)


def deploy(args: argparse.Namespace) -> int:
    env = load_env_from_args(args)
    deploy_set_name = args.set or env_lookup(env, "DEPLOY_SET") or ""
    deploy_sets_file = env_lookup(env, "DEPLOY_SETS_FILE") or args.deploy_sets_file
    deploy_set: dict[str, object] = {}
    deploy_sets: dict[str, dict[str, object]] = {}

    if args.list_sets:
        try:
            deploy_sets = load_presets(deploy_sets_file)
        except FileNotFoundError:
            print(f"Deploy sets file not found: {deploy_sets_file}", file=sys.stderr)
            return 2
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"Failed to parse deploy sets file '{deploy_sets_file}': {exc}", file=sys.stderr)
            return 2
        for name in sorted(deploy_sets):
            print(name)
        return 0

    if deploy_set_name:
        try:
            deploy_sets = load_presets(deploy_sets_file)
        except FileNotFoundError:
            print(f"Deploy sets file not found: {deploy_sets_file}", file=sys.stderr)
            return 2
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"Failed to parse deploy sets file '{deploy_sets_file}': {exc}", file=sys.stderr)
            return 2
        if deploy_set_name not in deploy_sets:
            print(
                f"Deploy set '{deploy_set_name}' not found in {deploy_sets_file}. "
                f"Available: {', '.join(sorted(deploy_sets)) or '(none)'}",
                file=sys.stderr,
            )
            return 2
        deploy_set = deploy_sets[deploy_set_name]

    remote_dir = str(resolve_value(
        args.remote_dir,
        env_lookup(env, "REMOTE_DIR"),
        get_preset_string(deploy_set, "remote_dir"),
        "~/runtime-sglang",
    ))
    default_hosts = [h for h in [env.get("MASTER_NODE"), env.get("WORKER_NODE")] if h]
    hosts = args.hosts or default_hosts
    if not hosts:
        print("No hosts provided. Use --hosts or MASTER_NODE/WORKER_NODE in config.", file=sys.stderr)
        return 2

    sources_raw = str(resolve_value(
        args.sources,
        env_lookup(env, "DEPLOY_SOURCES"),
        get_preset_csv_or_list(deploy_set, "sources"),
        "run.sh,build_wheel.sh,README.md,sglang,vision,pytorch",
    ))
    sources = normalize_local_sources(parse_csv(sources_raw))
    if not sources:
        print("No sources specified.", file=sys.stderr)
        return 2

    ssh_extra: list[str] = []
    if args.ssh_key:
        ssh_extra.extend(["-i", args.ssh_key])
    if args.ssh_port:
        ssh_extra.extend(["-p", str(args.ssh_port)])

    exclude_raw = str(resolve_value(
        args.exclude,
        env_lookup(env, "DEPLOY_EXCLUDE"),
        get_preset_csv_or_list(deploy_set, "exclude"),
        ".git,.venv,__pycache__,*.o,*.a,*.so,*.pt,*.bin",
    ))
    excludes = parse_csv(exclude_raw)
    for host in hosts:
        print(f"[deploy] preparing {host}:{remote_dir}")
        mkdir_cmd = f"mkdir -p {shlex.quote(remote_dir)}"
        result = run_cmd(["ssh", *ssh_extra, host, f"bash -lc {shlex.quote(mkdir_cmd)}"], check=False)
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
            return result.returncode

        rsync_cmd = ["rsync", "-az", "--delete"]
        for item in excludes:
            rsync_cmd.extend(["--exclude", item])
        if ssh_extra:
            rsync_cmd.extend(["-e", "ssh " + " ".join(shlex.quote(part) for part in ssh_extra)])
        rsync_cmd.extend(sources)
        rsync_cmd.append(f"{host}:{remote_dir}/")
        print(f"[deploy] syncing to {host}")
        result = run_cmd(rsync_cmd, check=False)
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
            return result.returncode
    print("[deploy] complete")
    return 0


def launch(args: argparse.Namespace) -> int:
    env = load_env_from_args(args)
    presets_file = env_lookup(env, "MODEL_PRESETS_FILE") or args.presets_file
    preset_name = args.preset or env_lookup(env, "MODEL_PRESET") or ""
    preset: dict[str, object] = {}
    presets: dict[str, dict[str, object]] = {}

    if args.list_presets:
        try:
            presets = load_presets(presets_file)
        except FileNotFoundError:
            print(f"Presets file not found: {presets_file}", file=sys.stderr)
            return 2
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"Failed to parse presets file '{presets_file}': {exc}", file=sys.stderr)
            return 2
        for name in sorted(presets):
            print(name)
        return 0

    if preset_name:
        try:
            presets = load_presets(presets_file)
        except FileNotFoundError:
            print(f"Presets file not found: {presets_file}", file=sys.stderr)
            return 2
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"Failed to parse presets file '{presets_file}': {exc}", file=sys.stderr)
            return 2
        if preset_name not in presets:
            print(
                f"Preset '{preset_name}' not found in {presets_file}. "
                f"Available: {', '.join(sorted(presets)) or '(none)'}",
                file=sys.stderr,
            )
            return 2
        preset = presets[preset_name]

    model_path = str(resolve_value(
        args.model_path,
        env_lookup(env, "MODEL_PATH"),
        get_preset_string(preset, "model_path"),
        "~/huggingface/Qwen_Qwen3.5-2B",
    ))
    venv_path = str(resolve_value(
        args.venv,
        env_lookup(env, "VENV_PATH"),
        get_preset_string(preset, "venv_path"),
        "~/.sglang",
    ))
    if args.mode == "solo":
        # Solo: single-process local or single-node SSH launch — default to one GPU shard.
        tp = int(args.tp) if args.tp is not None else 1
    else:
        tp = resolve_tp(args.tp, env, preset, preset_name)
    server_port = int(resolve_value(
        args.port,
        env_lookup(env, "SERVER_PORT"),
        get_preset_int(preset, "port"),
        30000,
    ))
    master_node = env_get(env, "MASTER_NODE", "")
    master_port = env_get(env, "MASTER_PORT", "20000")
    default_dist_addr = f"{master_node}:{master_port}" if master_node else args.dist_addr
    dist_addr = env_get(env, "DIST_ADDR", default_dist_addr)
    extra_sglang_args = [
        *get_preset_sglang_args(preset),
        *shlex.split(env_lookup(env, "SGLANG_EXTRA_ARGS") or ""),
        *shlex.split(args.sglang_args or ""),
    ]
    if preset_name and "--served-model-name" not in extra_sglang_args:
        extra_sglang_args.extend(["--served-model-name", preset_name])

    nccl_prefix = build_export_prefix(
        env,
        [
            "NCCL_IB_DISABLE",
            "NCCL_IB_GID_INDEX",
            "NCCL_IB_TIMEOUT",
            "NCCL_IB_RETRY_CNT",
            "NCCL_IB_SL",
            "NCCL_IB_TC",
            "NCCL_IB_QPS_PER_CONNECTION",
            "NCCL_IB_CUDA_SUPPORT",
            "NCCL_NET_GDR_LEVEL",
            "NCCL_NET_GDR_READ",
            "NCCL_P2P_DISABLE",
            "NCCL_IB_HCA",
            "NCCL_PROTO",
            "NCCL_ALGO",
            "NCCL_SOCKET_IFNAME",
            "NCCL_IB_IFNAME",
            "NCCL_DEBUG",
            "CUDA_GRAPHS",
            "SGLANG_DISABLE_TORCHVISION",
        ],
    )

    launch_cmd = args.command
    if not launch_cmd:
        venv_activate = f"{shell_quote_path_allow_home(venv_path)}/bin/activate"
        model_path_arg = shell_quote_path_allow_home(model_path)
        extra_sglang = " ".join(shlex.quote(arg) for arg in extra_sglang_args)
        launch_cmd = (
            f"{nccl_prefix}if [ ! -f {venv_activate} ]; then "
            f"echo 'Missing venv activate script at {venv_activate}. "
            f"Pass --venv or set VENV_PATH in .env.' >&2; exit 2; fi && "
            f"source {venv_activate} && "
            f"python -m sglang.launch_server --model-path {model_path_arg} "
            f"--tp {tp} --host 0.0.0.0 --port {server_port}"
        )
        if extra_sglang:
            launch_cmd = f"{launch_cmd} {extra_sglang}"

    if args.mode == "solo":
        if VERBOSE:
            print(f"[launch] command: {launch_cmd}")
        if args.host:
            print(f"[launch] remote solo launch on {args.host}")
            result = run_remote(args.host, launch_cmd, check=False)
            if result.stdout:
                print(result.stdout.strip())
            if result.stderr:
                print(result.stderr.strip(), file=sys.stderr)
            return result.returncode
        print("[launch] local solo launch")
        solo_cmd = launch_cmd
        if args.log_file:
            log_path = shell_quote_path_allow_home(args.log_file)
            print(f"[launch] writing local logs to {args.log_file}")
            # Brace group (not subshell): avoids edge cases where `launch_cmd` could
            # interact badly with `(...)` parsing; trailing `;` required before `}`.
            # pipefail keeps sglang's exit code through tee.
            solo_cmd = f"set -o pipefail && {{ {launch_cmd}; }} 2>&1 | tee -a {log_path}"
        proc = run_shell(solo_cmd, check=False)
        if proc.stdout:
            print(proc.stdout.strip())
        if proc.stderr:
            print(proc.stderr.strip(), file=sys.stderr)
        return proc.returncode

    if not args.hosts:
        hosts = [h for h in [master_node, env_get(env, "WORKER_NODE", "")] if h]
        if not hosts:
            print("Cluster mode requires --hosts or MASTER_NODE/WORKER_NODE in config.", file=sys.stderr)
            return 2
    else:
        hosts = args.hosts

    rc = 0
    for idx, host in enumerate(hosts):
        node_cmd = (
            f"{launch_cmd} "
            f"--dist-init-addr {dist_addr} "
            f"--nnodes {len(hosts)} --node-rank {idx}"
        )
        print(f"[launch] cluster node {idx} on {host}")
        # Run the full command in a shell so builtins like `export`/`source` work under nohup.
        node_cmd_quoted = shlex.quote(node_cmd)
        result = run_remote(
            host,
            f"nohup bash -lc {node_cmd_quoted} > {args.log_dir}/sglang_node{idx}.log 2>&1 &",
            check=False,
        )
        if result.returncode != 0:
            rc = result.returncode
            if result.stderr:
                print(result.stderr.strip(), file=sys.stderr)
    return rc


def stop(args: argparse.Namespace) -> int:
    env = load_env_from_args(args)
    presets_file = env_lookup(env, "MODEL_PRESETS_FILE") or args.presets_file
    preset_name = args.preset or env_lookup(env, "MODEL_PRESET") or ""
    preset: dict[str, object] = {}
    presets: dict[str, dict[str, object]] = {}

    if preset_name:
        try:
            presets = load_presets(presets_file)
        except FileNotFoundError:
            print(f"Presets file not found: {presets_file}", file=sys.stderr)
            return 2
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"Failed to parse presets file '{presets_file}': {exc}", file=sys.stderr)
            return 2
        if preset_name not in presets:
            print(
                f"Preset '{preset_name}' not found in {presets_file}. "
                f"Available: {', '.join(sorted(presets)) or '(none)'}",
                file=sys.stderr,
            )
            return 2
        preset = presets[preset_name]

    server_port = int(resolve_value(
        args.port,
        env_lookup(env, "SERVER_PORT"),
        get_preset_int(preset, "port"),
        30000,
    ))

    if args.mode == "solo":
        targets = [args.host] if args.host else ["local"]
    else:
        if args.hosts:
            targets = args.hosts
        else:
            targets = [h for h in [env_get(env, "MASTER_NODE", ""), env_get(env, "WORKER_NODE", "")] if h]
            if not targets:
                print(
                    "Cluster mode stop requires --hosts or MASTER_NODE/WORKER_NODE in config.",
                    file=sys.stderr,
                )
                return 2

    stop_cmd = (
        f"pids=$(lsof -tiTCP:{server_port} -sTCP:LISTEN 2>/dev/null || true); "
        "if [ -n \"$pids\" ]; then "
        "echo \"[stop] port pid(s): $pids\"; "
        "kill $pids 2>/dev/null || true; "
        f"sleep {args.grace_sec}; "
        "remaining=\"\"; "
        "for pid in $pids; do if kill -0 \"$pid\" 2>/dev/null; then remaining=\"$remaining $pid\"; fi; done; "
        "if [ -n \"$remaining\" ]; then "
        "echo \"[stop] force-killing pid(s):$remaining\"; "
        "kill -9 $remaining 2>/dev/null || true; "
        "fi; "
        "else "
        "echo \"[stop] no listener found on target port\"; "
        "fi; "
        "pkill -f 'python -m sglang.launch_server' >/dev/null 2>&1 || true"
    )

    rc = 0
    for target in targets:
        label = target
        if target == "local":
            print(f"[stop] local stop on port {server_port}")
            result = run_shell(stop_cmd, check=False)
        else:
            print(f"[stop] remote stop on {target} port {server_port}")
            result = run_remote(target, stop_cmd, check=False)
        if result.stdout:
            print(result.stdout.strip())
        if result.stderr:
            print(f"[{label}] {result.stderr.strip()}", file=sys.stderr)
        if result.returncode != 0:
            rc = result.returncode
    return rc


def benchmark(args: argparse.Namespace) -> int:
    result = run_benchmark(
        base_url=args.base_url,
        api_key=args.api_key,
        model=args.model,
        prompt=args.prompt,
        max_tokens=args.max_tokens,
        requests=args.requests,
        timeout_sec=args.timeout_sec,
    )
    if result is None:
        print("No successful benchmark requests.", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


def run_benchmark(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int,
    requests: int,
    timeout_sec: int,
) -> dict[str, float | int] | None:
    url = base_url.rstrip("/") + "/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }

    latencies = []
    failures = 0
    for i in range(requests):
        start = time.perf_counter()
        req = urllib.request.Request(
            url=url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as response:
                response.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            failures += 1
            print(f"[benchmark] request {i + 1} failed: {exc}", file=sys.stderr)
            continue
        latencies.append(time.perf_counter() - start)

    if not latencies:
        print("No successful benchmark requests.", file=sys.stderr)
        return None

    total_time = sum(latencies)
    rps = len(latencies) / total_time if total_time > 0 else 0.0
    sorted_lat = sorted(latencies)

    def pct(p: float) -> float:
        idx = min(len(sorted_lat) - 1, int((p / 100.0) * len(sorted_lat)))
        return sorted_lat[idx]

    return {
        "successful_requests": len(latencies),
        "failed_requests": failures,
        "avg_latency_sec": round(mean(latencies), 4),
        "p50_latency_sec": round(pct(50), 4),
        "p95_latency_sec": round(pct(95), 4),
        "throughput_rps": round(rps, 3),
    }


def measure(args: argparse.Namespace) -> int:
    env = load_env_from_args(args)
    gpu_cmd = (
        "nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total,power.draw "
        "--format=csv,noheader,nounits"
    )
    sys_cmd = (
        "python - <<'PY'\n"
        "import json, os\n"
        "load = os.getloadavg()\n"
        "print(json.dumps({'load_1m': load[0], 'load_5m': load[1], 'load_15m': load[2]}))\n"
        "PY"
    )
    command = f"{gpu_cmd} && {sys_cmd}"

    if args.hosts:
        targets = args.hosts
    else:
        config_targets = [h for h in [env.get("MASTER_NODE"), env.get("WORKER_NODE")] if h]
        targets = config_targets if config_targets else ["local"]
    output: dict[str, dict[str, str]] = {}
    for host in targets:
        if host == "local":
            result = run_shell(command, check=False)
        else:
            result = run_remote(host, command, check=False)
        output[host] = {
            "exit_code": str(result.returncode),
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    print(json.dumps(output, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DGX Spark runtime operations for custom sglang stack")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose debug output")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_deploy = sub.add_parser("deploy", help="Deploy runtime to remote host(s)")
    p_deploy.add_argument("--hosts", nargs="+", help="Remote hosts, e.g. spark-02")
    p_deploy.add_argument("--set", default="", help="Named deploy set from deploy sets file")
    p_deploy.add_argument(
        "--deploy-sets-file",
        default="deploy_sets.json",
        help="Path to JSON deploy sets file",
    )
    p_deploy.add_argument("--list-sets", action="store_true", help="List deploy sets and exit")
    p_deploy.add_argument(
        "--sources",
        default=None,
        help="Comma-separated local paths to sync",
    )
    p_deploy.add_argument("--remote-dir", default=None, help="Remote destination directory")
    p_deploy.add_argument(
        "--exclude",
        default=None,
        help="Comma-separated rsync exclude patterns",
    )
    p_deploy.add_argument("--ssh-key", default="", help="Optional SSH private key path")
    p_deploy.add_argument("--ssh-port", type=int, default=22, help="SSH port")
    p_deploy.add_argument("--env-file", default="", help="Optional path to .env")
    p_deploy.set_defaults(func=deploy)

    p_launch = sub.add_parser("launch", help="Launch sglang runtime")
    p_launch.add_argument("--mode", choices=["solo", "cluster"], default="solo")
    p_launch.add_argument("--host", default="", help="Remote host for solo mode")
    p_launch.add_argument("--hosts", nargs="*", help="Remote hosts for cluster mode")
    p_launch.add_argument("--venv", default=None, help="Python virtual env path")
    p_launch.add_argument("--model-path", default=None)
    p_launch.add_argument("--tp", type=int, default=None)
    p_launch.add_argument("--port", type=int, default=None)
    p_launch.add_argument("--dist-addr", default="spark-01:20000", help="Master addr:port for cluster")
    p_launch.add_argument("--log-dir", default="~/runtime-sglang/logs", help="Remote log directory")
    p_launch.add_argument("--log-file", default="sglang_solo.log", help="Local log file for solo mode")
    p_launch.add_argument("--preset", default="", help="Preset name from presets file")
    p_launch.add_argument("--presets-file", default="model_presets.json", help="Path to JSON presets file")
    p_launch.add_argument("--list-presets", action="store_true", help="List available presets and exit")
    p_launch.add_argument(
        "--sglang-args",
        default="",
        help="Extra arguments appended to sglang.launch_server, e.g. '--enable-metrics --context-length 32768'",
    )
    p_launch.add_argument("--command", default="", help="Optional full launch command override")
    p_launch.add_argument("--env-file", default="", help="Optional path to .env")
    p_launch.set_defaults(func=launch)

    p_stop = sub.add_parser("stop", help="Stop launched sglang runtime")
    p_stop.add_argument("--mode", choices=["solo", "cluster"], default="solo")
    p_stop.add_argument("--host", default="", help="Remote host for solo mode")
    p_stop.add_argument("--hosts", nargs="*", help="Remote hosts for cluster mode")
    p_stop.add_argument("--port", type=int, default=None, help="Server port to stop (default from config/preset)")
    p_stop.add_argument(
        "--grace-sec",
        type=int,
        default=5,
        help="Grace period before force-kill for processes found on target port",
    )
    p_stop.add_argument("--preset", default="", help="Preset name from presets file")
    p_stop.add_argument("--presets-file", default="model_presets.json", help="Path to JSON presets file")
    p_stop.add_argument("--env-file", default="", help="Optional path to .env")
    p_stop.set_defaults(func=stop)

    p_bench = sub.add_parser("benchmark", help="Run API benchmark")
    p_bench.add_argument("--base-url", default="http://127.0.0.1:30000")
    p_bench.add_argument("--api-key", default="EMPTY")
    p_bench.add_argument("--model", default="default")
    p_bench.add_argument("--prompt", default="Write a short haiku about distributed inference.")
    p_bench.add_argument("--max-tokens", type=int, default=64)
    p_bench.add_argument("--requests", type=int, default=20)
    p_bench.add_argument("--timeout-sec", type=int, default=120)
    p_bench.set_defaults(func=benchmark)

    p_measure = sub.add_parser("measure", help="Capture utilization snapshots")
    p_measure.add_argument("--hosts", nargs="*", help="If omitted, measure local node only")
    p_measure.add_argument("--env-file", default="", help="Optional path to .env")
    p_measure.set_defaults(func=measure)

    return parser


def main() -> int:
    global VERBOSE
    parser = build_parser()
    args = parser.parse_args()
    VERBOSE = args.verbose
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
