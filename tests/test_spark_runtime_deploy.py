"""Unit tests for spark_runtime.deploy behavior."""

from __future__ import annotations

import argparse
import subprocess
import unittest
from unittest import mock

import spark_runtime as sr


def _cp(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _deploy_args(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "hosts": None,
        "set": "",
        "deploy_sets_file": "deploy_sets.json",
        "list_sets": False,
        "sources": None,
        "remote_dir": None,
        "exclude": None,
        "ssh_key": "",
        "ssh_port": 22,
        "env_file": "",
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class TestDeploy(unittest.TestCase):
    @mock.patch.object(sr, "run_cmd")
    @mock.patch.object(sr, "load_env_from_args")
    def test_uses_env_hosts_and_default_source_set(self, m_env: mock.Mock, m_run_cmd: mock.Mock) -> None:
        m_env.return_value = {"MASTER_NODE": "spark1", "WORKER_NODE": "spark2"}
        m_run_cmd.side_effect = [_cp(), _cp(), _cp(), _cp()]

        rc = sr.deploy(_deploy_args())

        self.assertEqual(rc, 0)
        self.assertEqual(m_run_cmd.call_count, 4)

        mkdir1 = m_run_cmd.call_args_list[0].args[0]
        rsync1 = m_run_cmd.call_args_list[1].args[0]
        mkdir2 = m_run_cmd.call_args_list[2].args[0]
        rsync2 = m_run_cmd.call_args_list[3].args[0]

        self.assertEqual(mkdir1[0], "ssh")
        self.assertIn("spark1", mkdir1)
        self.assertIn("mkdir -p", mkdir1[-1])
        self.assertEqual(rsync1[-1], "spark1:~/runtime-sglang/")

        self.assertIn("spark2", mkdir2)
        self.assertEqual(rsync2[-1], "spark2:~/runtime-sglang/")
        self.assertIn("run.sh", rsync1)
        self.assertIn("pytorch", rsync1)

    @mock.patch.object(sr, "run_cmd")
    @mock.patch.object(sr, "load_presets")
    @mock.patch.object(sr, "load_env_from_args")
    def test_uses_deploy_set_from_env(self, m_env: mock.Mock, m_load_presets: mock.Mock, m_run_cmd: mock.Mock) -> None:
        m_env.return_value = {
            "MASTER_NODE": "spark1",
            "WORKER_NODE": "spark2",
            "DEPLOY_SET": "minimal",
        }
        m_load_presets.return_value = {
            "minimal": {
                "sources": ["spark_runtime.py", "tests"],
                "exclude": [".git", "__pycache__"],
                "remote_dir": "/remote/runtime",
            }
        }
        m_run_cmd.side_effect = [_cp(), _cp(), _cp(), _cp()]

        rc = sr.deploy(_deploy_args())

        self.assertEqual(rc, 0)
        rsync1 = m_run_cmd.call_args_list[1].args[0]
        self.assertIn("spark_runtime.py", rsync1)
        self.assertIn("tests", rsync1)
        self.assertIn("--exclude", rsync1)
        self.assertEqual(rsync1[-1], "spark1:/remote/runtime/")
        m_load_presets.assert_called_once_with("deploy_sets.json")

    @mock.patch.object(sr, "run_cmd")
    @mock.patch.object(sr, "load_presets")
    @mock.patch.object(sr, "load_env_from_args")
    @mock.patch.object(sr.os.path, "expanduser", return_value="/home/chenchen/.sglang")
    def test_expands_tilde_source_path(
        self,
        m_expanduser: mock.Mock,
        m_env: mock.Mock,
        m_load_presets: mock.Mock,
        m_run_cmd: mock.Mock,
    ) -> None:
        m_env.return_value = {"MASTER_NODE": "spark1", "DEPLOY_SET": "venv"}
        m_load_presets.return_value = {"venv": {"sources": ["~/.sglang"]}}
        m_run_cmd.side_effect = [_cp(), _cp()]

        rc = sr.deploy(_deploy_args())

        self.assertEqual(rc, 0)
        rsync_cmd = m_run_cmd.call_args_list[1].args[0]
        self.assertIn("/home/chenchen/.sglang", rsync_cmd)
        m_expanduser.assert_called_with("~/.sglang")

    @mock.patch.object(sr, "run_cmd")
    @mock.patch.object(sr, "load_env_from_args")
    def test_returns_error_when_prepare_fails(self, m_env: mock.Mock, m_run_cmd: mock.Mock) -> None:
        m_env.return_value = {"MASTER_NODE": "spark1"}
        m_run_cmd.side_effect = [_cp(returncode=5, stderr="ssh failed")]

        rc = sr.deploy(_deploy_args())

        self.assertEqual(rc, 5)
        self.assertEqual(m_run_cmd.call_count, 1)

    @mock.patch.object(sr, "run_cmd")
    @mock.patch.object(sr, "load_env_from_args")
    def test_returns_error_when_rsync_fails(self, m_env: mock.Mock, m_run_cmd: mock.Mock) -> None:
        m_env.return_value = {"MASTER_NODE": "spark1"}
        m_run_cmd.side_effect = [_cp(), _cp(returncode=23, stderr="rsync failed")]

        rc = sr.deploy(_deploy_args())

        self.assertEqual(rc, 23)
        self.assertEqual(m_run_cmd.call_count, 2)

    @mock.patch.object(sr, "load_env_from_args")
    def test_returns_2_when_no_hosts(self, m_env: mock.Mock) -> None:
        m_env.return_value = {}
        self.assertEqual(sr.deploy(_deploy_args()), 2)

    @mock.patch.object(sr, "load_presets")
    @mock.patch.object(sr, "load_env_from_args")
    def test_list_sets_mode(self, m_env: mock.Mock, m_load_presets: mock.Mock) -> None:
        m_env.return_value = {}
        m_load_presets.return_value = {"a": {}, "b": {}}

        rc = sr.deploy(_deploy_args(list_sets=True))

        self.assertEqual(rc, 0)
        m_load_presets.assert_called_once_with("deploy_sets.json")


if __name__ == "__main__":
    unittest.main()
