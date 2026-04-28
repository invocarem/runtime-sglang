"""Unit tests for spark_runtime operational subcommands."""

from __future__ import annotations

import argparse
import subprocess
import unittest
from unittest import mock

import spark_runtime as sr


def _cp(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _launch_args(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "mode": "solo",
        "host": "",
        "hosts": None,
        "venv": None,
        "model_path": None,
        "tp": None,
        "port": None,
        "dist_addr": "spark-01:20000",
        "log_dir": "~/runtime-sglang/logs",
        "log_file": "sglang_solo.log",
        "preset": "",
        "presets_file": "model_presets.json",
        "list_presets": False,
        "sglang_args": "",
        "command": "",
        "env_file": "",
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class TestLaunch(unittest.TestCase):
    @mock.patch.object(sr, "load_presets")
    @mock.patch.object(sr, "load_env_from_args")
    def test_list_presets_mode(self, m_env: mock.Mock, m_load_presets: mock.Mock) -> None:
        m_env.return_value = {}
        m_load_presets.return_value = {"a": {}, "b": {}}

        rc = sr.launch(_launch_args(list_presets=True))

        self.assertEqual(rc, 0)
        m_load_presets.assert_called_once_with("model_presets.json")

    @mock.patch.object(sr, "run_shell")
    @mock.patch.object(sr, "load_env_from_args")
    def test_solo_local_launch_uses_run_shell(self, m_env: mock.Mock, m_run_shell: mock.Mock) -> None:
        m_env.return_value = {
            "MODEL_PATH": "/models/qwen",
            "VENV_PATH": "/venv/sg",
            "SERVER_PORT": "30000",
        }
        m_run_shell.return_value = _cp(returncode=0, stdout="ok")

        rc = sr.launch(_launch_args(mode="solo"))

        self.assertEqual(rc, 0)
        self.assertEqual(m_run_shell.call_count, 1)
        shell_cmd = m_run_shell.call_args.args[0]
        self.assertIn("source /venv/sg/bin/activate", shell_cmd)
        self.assertIn("--model-path /models/qwen", shell_cmd)
        self.assertIn("--tp 1", shell_cmd)
        self.assertIn("--port 30000", shell_cmd)

    @mock.patch.object(sr, "run_remote")
    @mock.patch.object(sr, "load_env_from_args")
    def test_solo_remote_launch_uses_run_remote(self, m_env: mock.Mock, m_run_remote: mock.Mock) -> None:
        m_env.return_value = {"MODEL_PATH": "/models/qwen", "VENV_PATH": "/venv/sg"}
        m_run_remote.return_value = _cp(returncode=0)

        rc = sr.launch(_launch_args(mode="solo", host="spark2"))

        self.assertEqual(rc, 0)
        self.assertEqual(m_run_remote.call_count, 1)
        self.assertEqual(m_run_remote.call_args.args[0], "spark2")

    @mock.patch.object(sr, "load_env_from_args")
    def test_cluster_requires_hosts_or_env(self, m_env: mock.Mock) -> None:
        m_env.return_value = {}
        self.assertEqual(sr.launch(_launch_args(mode="cluster", hosts=None)), 2)

    @mock.patch.object(sr, "run_remote")
    @mock.patch.object(sr, "load_env_from_args")
    def test_cluster_launch_assigns_node_ranks(self, m_env: mock.Mock, m_run_remote: mock.Mock) -> None:
        m_env.return_value = {
            "MODEL_PATH": "/models/qwen",
            "VENV_PATH": "/venv/sg",
            "DIST_ADDR": "spark1:20000",
        }
        m_run_remote.side_effect = [_cp(returncode=0), _cp(returncode=0)]

        rc = sr.launch(_launch_args(mode="cluster", hosts=["spark1", "spark2"]))

        self.assertEqual(rc, 0)
        self.assertEqual(m_run_remote.call_count, 2)
        cmd0 = m_run_remote.call_args_list[0].args[1]
        cmd1 = m_run_remote.call_args_list[1].args[1]
        self.assertIn("--node-rank 0", cmd0)
        self.assertIn("--node-rank 1", cmd1)
        self.assertIn("--nnodes 2", cmd0)
        self.assertIn("--dist-init-addr spark1:20000", cmd0)


class TestBenchmarkSubcommand(unittest.TestCase):
    @mock.patch.object(sr, "run_benchmark")
    def test_benchmark_returns_error_when_all_fail(self, m_run_benchmark: mock.Mock) -> None:
        m_run_benchmark.return_value = None
        args = argparse.Namespace(
            base_url="http://127.0.0.1:30000",
            api_key="EMPTY",
            model="default",
            prompt="p",
            max_tokens=4,
            requests=2,
            timeout_sec=5,
        )
        self.assertEqual(sr.benchmark(args), 1)

    @mock.patch.object(sr, "run_benchmark")
    def test_benchmark_returns_success(self, m_run_benchmark: mock.Mock) -> None:
        m_run_benchmark.return_value = {"successful_requests": 2}
        args = argparse.Namespace(
            base_url="http://127.0.0.1:30000",
            api_key="EMPTY",
            model="default",
            prompt="p",
            max_tokens=4,
            requests=2,
            timeout_sec=5,
        )
        self.assertEqual(sr.benchmark(args), 0)


class TestMeasure(unittest.TestCase):
    @mock.patch.object(sr, "run_shell")
    @mock.patch.object(sr, "load_env_from_args")
    def test_measure_defaults_to_local(self, m_env: mock.Mock, m_run_shell: mock.Mock) -> None:
        m_env.return_value = {}
        m_run_shell.return_value = _cp(returncode=0, stdout="gpu\nsys")

        rc = sr.measure(argparse.Namespace(hosts=None, env_file=""))

        self.assertEqual(rc, 0)
        m_run_shell.assert_called_once()

    @mock.patch.object(sr, "run_remote")
    @mock.patch.object(sr, "load_env_from_args")
    def test_measure_remote_hosts(self, m_env: mock.Mock, m_run_remote: mock.Mock) -> None:
        m_env.return_value = {}
        m_run_remote.side_effect = [_cp(returncode=0), _cp(returncode=0)]

        rc = sr.measure(argparse.Namespace(hosts=["spark1", "spark2"], env_file=""))

        self.assertEqual(rc, 0)
        self.assertEqual(m_run_remote.call_count, 2)


class TestMain(unittest.TestCase):
    @mock.patch.object(sr, "build_parser")
    def test_main_sets_verbose_and_runs_handler(self, m_build_parser: mock.Mock) -> None:
        fake_func = mock.Mock(return_value=123)
        fake_args = argparse.Namespace(verbose=True, func=fake_func)
        parser = mock.Mock()
        parser.parse_args.return_value = fake_args
        m_build_parser.return_value = parser

        rc = sr.main()

        self.assertEqual(rc, 123)
        self.assertTrue(sr.VERBOSE)
        fake_func.assert_called_once_with(fake_args)


if __name__ == "__main__":
    unittest.main()
