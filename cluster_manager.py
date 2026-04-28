from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

from .config import settings


class ClusterManager:
    def __init__(self) -> None:
        self.scripts_dir = Path(settings.scripts_dir)
        self.master_node = settings.master_node
        self.worker_node = settings.worker_node
        self.cx7_iface = settings.cx7_iface
        self.model_path = settings.model_path
        self.editable_source_root = Path(settings.editable_source_root).expanduser()

    def _run(self, cmd: list[str], timeout: int | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            cmd,
            cwd=str(self.scripts_dir),
            check=True,
            text=True,
            capture_output=True,
            timeout=timeout,
        )

    @staticmethod
    def _print_output(result: subprocess.CompletedProcess[str]) -> None:
        if result.stdout:
            print(result.stdout.rstrip())
        if result.stderr:
            print(result.stderr.rstrip())

    def check_ssh(self, node: str) -> bool:
        print(f"Testing SSH connection to {node}...")
        try:
            result = self._run(["ssh", "-o", "ConnectTimeout=5", node, "echo", "OK"], timeout=10)
            ok = "OK" in result.stdout
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            ok = False
        if ok:
            print("SSH connection successful")
        else:
            print(f"Cannot connect to {node}")
        return ok

    def sync_venv(self, node: str) -> None:
        print(f"Syncing virtual environment to {node}...")
        self._run(
            [
                "rsync",
                "-avz",
                "--delete",
                "--progress",
                "--exclude=__pycache__",
                "--exclude=*.pyc",
                "--exclude=lib/python3.12/site-packages/*.dist-info/RECORD",
                "--exclude=lib/python3.12/site-packages/torch/lib/*.a",
                "--exclude=lib/python3.12/site-packages/torch/include",
                "--exclude=share",
                str(Path.home() / ".sglang") + "/",
                f"{node}:~/.sglang/",
            ]
        )
        print("Virtual environment synced")

    def sync_model(self, node: str) -> None:
        if not Path(self.model_path).is_dir():
            print(f"Model not found at {self.model_path}, skipping...")
            return

        print(f"Checking model on {node}...")
        check_cmd = f"test -d {shlex.quote(self.model_path)}"
        result = subprocess.run(
            ["ssh", node, check_cmd],
            cwd=str(self.scripts_dir),
            check=False,
            text=True,
            capture_output=True,
        )
        if result.returncode == 0:
            print(f"Model already exists on {node}")
            return

        print(f"Syncing model to {node} (this may take a while)...")
        self._run(["rsync", "-avz", "--progress", f"{self.model_path}/", f"{node}:{self.model_path}/"])

    def sync_scripts(self, node: str) -> None:
        print(f"Syncing cluster scripts to {node}...")
        self._run(["ssh", node, "mkdir -p ~/sglang-cluster"])
        copy_cmd = [
            "scp",
            str(self.scripts_dir / "config.sh"),
            str(self.scripts_dir / "run_server.sh"),
            str(self.scripts_dir / "cx7_optimize.sh"),
            f"{node}:~/sglang-cluster/",
        ]
        subprocess.run(copy_cmd, cwd=str(self.scripts_dir), check=False, text=True, capture_output=True)
        self._run(["ssh", node, "chmod +x ~/sglang-cluster/*.sh 2>/dev/null || true"])
        print("Scripts synced")

    def sync_python_runtime(self, node: str) -> None:
        print(f"Syncing backend runtime files to {node}...")
        remote_root = "~/sglang-cluster/backend/app/"
        self._run(["ssh", node, "mkdir -p ~/sglang-cluster/backend/app"])
        self._run(
            [
                "rsync",
                "-avz",
                str(self.scripts_dir / "backend/app/__init__.py"),
                str(self.scripts_dir / "backend/app/config.py"),
                str(self.scripts_dir / "backend/app/server_cli.py"),
                str(self.scripts_dir / "backend/app/server_launcher.py"),
                f"{node}:{remote_root}",
            ]
        )
        print("Backend runtime files synced")

    def sync_editable_sources(self, node: str) -> None:
        if not self.editable_source_root.is_dir():
            print(f"Editable source root not found at {self.editable_source_root}, skipping...")
            return

        remote_parent = str(self.editable_source_root.parent)
        remote_root = str(self.editable_source_root)
        print(f"Syncing editable source tree to {node}: {remote_root}")
        self._run(["ssh", node, f"mkdir -p {shlex.quote(remote_parent)}"])
        self._run(
            [
                "rsync",
                "-avz",
                "--delete",
                "--exclude=.git",
                "--exclude=__pycache__",
                "--exclude=*.pyc",
                f"{remote_root}/",
                f"{node}:{remote_root}/",
            ]
        )
        print("Editable source tree synced")

    def deploy(self) -> None:
        print(f"=== Deploying to worker: {self.worker_node} ===")
        if not self.check_ssh(self.worker_node):
            raise RuntimeError(f"Cannot connect to {self.worker_node}")
        self._run(["ssh", self.worker_node, "mkdir -p ~/.sglang ~/sglang-cluster"])
        self.sync_venv(self.worker_node)
        self.sync_model(self.worker_node)
        self.sync_scripts(self.worker_node)
        self.sync_python_runtime(self.worker_node)
        self.sync_editable_sources(self.worker_node)
        print("Deployment complete")

    def optimize(self) -> None:
        print("=== Optimizing CX7 network ===")
        print("Optimizing master node...")
        subprocess.run(["sudo", "bash", str(self.scripts_dir / "cx7_optimize.sh")], check=False)
        print("Optimizing worker node...")
        subprocess.run(
            ["ssh", self.worker_node, "cd ~/sglang-cluster && sudo bash cx7_optimize.sh"],
            cwd=str(self.scripts_dir),
            check=False,
        )
        print("Optimization complete")

    def _get_master_ip(self) -> str:
        result = subprocess.run(
            ["ip", "-4", "addr", "show", self.cx7_iface],
            check=False,
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            return self.master_node
        match = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", result.stdout)
        return match.group(1) if match else self.master_node

    def launch(self) -> None:
        print("=== Launching distributed SGLang ===")
        master_ip = self._get_master_ip()
        print(f"Master IP: {master_ip}")
        self.sync_python_runtime(self.master_node)
        self.sync_python_runtime(self.worker_node)
        print(f"Starting master on {self.master_node}...")
        self._run(
            [
                "ssh",
                self.master_node,
                (
                    "cd ~/sglang-cluster && "
                    "export PYTHONPATH=~/sglang-cluster:${PYTHONPATH} && "
                    f"export MASTER_ADDR={master_ip} && "
                    "nohup ~/.sglang/bin/python -m backend.app.server_cli master > server.log 2>&1 &"
                ),
            ]
        )
        print(f"Starting worker on {self.worker_node}...")
        self._run(
            [
                "ssh",
                self.worker_node,
                (
                    "cd ~/sglang-cluster && "
                    "export PYTHONPATH=~/sglang-cluster:${PYTHONPATH} && "
                    f"export MASTER_ADDR={master_ip} && "
                    "nohup ~/.sglang/bin/python -m backend.app.server_cli worker > server.log 2>&1 &"
                ),
            ]
        )
        print("Cluster launching... Check status with: python -m backend.app.cluster_cli status")

    def status(self) -> None:
        print("=== Cluster Status ===")
        print(f"Master ({self.master_node}):")
        master = subprocess.run(
            [
                "ssh",
                self.master_node,
                "ps aux | grep -E 'sglang|python.*launch_server' | grep -v grep || echo 'Not running'",
            ],
            cwd=str(self.scripts_dir),
            check=False,
            text=True,
            capture_output=True,
        )
        self._print_output(master)
        print(f"Worker ({self.worker_node}):")
        worker = subprocess.run(
            [
                "ssh",
                self.worker_node,
                "ps aux | grep -E 'sglang|python.*launch_server' | grep -v grep || echo 'Not running'",
            ],
            cwd=str(self.scripts_dir),
            check=False,
            text=True,
            capture_output=True,
        )
        self._print_output(worker)

    def stop(self) -> None:
        print("Stopping all servers...")
        subprocess.run(
            ["ssh", self.master_node, "pkill -f 'sglang|launch_server' || true"],
            cwd=str(self.scripts_dir),
            check=False,
        )
        subprocess.run(
            ["ssh", self.worker_node, "pkill -f 'sglang|launch_server' || true"],
            cwd=str(self.scripts_dir),
            check=False,
        )
        print("Servers stopped")

    def run_action(self, action: str) -> None:
        if action == "deploy":
            self.deploy()
            return
        if action == "optimize":
            self.optimize()
            return
        if action == "launch":
            self.deploy()
            self.optimize()
            self.launch()
            return
        if action == "status":
            self.status()
            return
        if action == "stop":
            self.stop()
            return
        raise ValueError(f"Unsupported action: {action}")


def build_cluster_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("MASTER_NODE", settings.master_node)
    env.setdefault("WORKER_NODE", settings.worker_node)
    env.setdefault("MASTER_PORT", str(settings.master_port))
    env.setdefault("SERVER_PORT", str(settings.server_port))
    env.setdefault("MODEL_PATH", settings.model_path)
    env.setdefault("TP_SIZE", str(settings.tp_size))
    env.setdefault("CX7_IFACE", settings.cx7_iface)
    return env
