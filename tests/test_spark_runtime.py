"""Unit tests for spark_runtime helpers (no SSH/rsync integration)."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import tempfile
import unittest
import urllib.error
from unittest import mock

import spark_runtime as sr


def _mk_env_file() -> tuple[int, str]:
    return tempfile.mkstemp(suffix=".env")


class TestFormatCommand(unittest.TestCase):
    def test_quotes_spaces(self) -> None:
        self.assertEqual(sr.format_command(["echo", "a b"]), "echo 'a b'")


class TestLoadDotenv(unittest.TestCase):
    def setUp(self) -> None:
        self._fd, self.path = _mk_env_file()

    def tearDown(self) -> None:
        os.close(self._fd)
        os.unlink(self.path)

    def test_skips_comments_and_blank(self) -> None:
        content = """
# comment
FOO=bar

BAZ='quoted'
"""
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(content)
        env = sr.load_dotenv(self.path)
        self.assertEqual(env["FOO"], "bar")
        self.assertEqual(env["BAZ"], "quoted")

    def test_skips_lines_without_equals(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("not_a_var\nX=1\n")
        self.assertEqual(sr.load_dotenv(self.path), {"X": "1"})


class TestLoadEnvFromArgs(unittest.TestCase):
    def test_explicit_env_file(self) -> None:
        fd, path = _mk_env_file()
        try:
            os.write(fd, b"A=1\n")
            os.close(fd)
            fd = -1
            ns = argparse.Namespace(env_file=path)
            self.assertEqual(sr.load_env_from_args(ns), {"A": "1"})
        finally:
            if fd >= 0:
                os.close(fd)
            os.unlink(path)

    @mock.patch.object(sr.os.path, "isfile", return_value=False)
    def test_no_default_env_when_missing(self, _m: mock.Mock) -> None:
        ns = argparse.Namespace(env_file="")
        self.assertEqual(sr.load_env_from_args(ns), {})


class TestEnvHelpers(unittest.TestCase):
    def test_env_get_prefers_mapping_then_os(self) -> None:
        with mock.patch.dict(os.environ, {"K": "from_os"}, clear=False):
            self.assertEqual(sr.env_get({"K": "from_map"}, "K", "def"), "from_map")
            self.assertEqual(sr.env_get({}, "K", "def"), "from_os")
            self.assertEqual(sr.env_get({}, "MISSING", "def"), "def")

    def test_env_lookup_empty_is_none(self) -> None:
        with mock.patch.dict(os.environ, {"EMPTY": ""}, clear=False):
            self.assertIsNone(sr.env_lookup({}, "EMPTY"))
        self.assertIsNone(sr.env_lookup({}, "NO_SUCH_KEY"))


class TestLoadPresets(unittest.TestCase):
    def setUp(self) -> None:
        self._fd, self.path = _mk_env_file()

    def tearDown(self) -> None:
        os.close(self._fd)
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def test_valid_object(self) -> None:
        data = {"p1": {"tp": 2, "model_path": "/m"}}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        presets = sr.load_presets(self.path)
        self.assertEqual(presets["p1"]["tp"], 2)

    def test_rejects_non_object_root(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("[1,2]")
        with self.assertRaises(ValueError):
            sr.load_presets(self.path)


class TestPresetAccessors(unittest.TestCase):
    def test_get_preset_string(self) -> None:
        self.assertIsNone(sr.get_preset_string({}, "x"))
        self.assertEqual(sr.get_preset_string({"x": "a"}, "x"), "a")
        with self.assertRaises(ValueError):
            sr.get_preset_string({"x": 1}, "x")

    def test_get_preset_int(self) -> None:
        self.assertIsNone(sr.get_preset_int({}, "x"))
        self.assertEqual(sr.get_preset_int({"x": 3}, "x"), 3)
        self.assertEqual(sr.get_preset_int({"x": "42"}, "x"), 42)
        with self.assertRaises(ValueError):
            sr.get_preset_int({"x": True}, "x")
        with self.assertRaises(ValueError):
            sr.get_preset_int({"x": "nope"}, "x")

    def test_get_preset_sglang_args(self) -> None:
        self.assertEqual(sr.get_preset_sglang_args({}), [])
        self.assertEqual(sr.get_preset_sglang_args({"sglang_args": ["--a"]}), ["--a"])
        with self.assertRaises(ValueError):
            sr.get_preset_sglang_args({"sglang_args": "bad"})


class TestResolveValue(unittest.TestCase):
    def test_precedence(self) -> None:
        self.assertEqual(sr.resolve_value("cli", "e", "p", "d"), "cli")
        self.assertEqual(sr.resolve_value(None, "e", "p", "d"), "e")
        self.assertEqual(sr.resolve_value(None, None, "p", "d"), "p")
        self.assertEqual(sr.resolve_value(None, None, None, "d"), "d")


class TestResolveTp(unittest.TestCase):
    def test_args_win(self) -> None:
        self.assertEqual(sr.resolve_tp(8, {}, {}, ""), 8)

    def test_preset_name_branch_uses_preset_then_env(self) -> None:
        env = {"TP_SIZE": "4"}
        preset = {"tp": 2}
        self.assertEqual(sr.resolve_tp(None, env, preset, "my"), 2)
        self.assertEqual(sr.resolve_tp(None, env, {}, "my"), 4)
        self.assertEqual(sr.resolve_tp(None, {}, {}, "my"), 1)

    def test_no_preset_name_env_before_preset(self) -> None:
        env = {"TP_SIZE": "3"}
        preset = {"tp": 7}
        self.assertEqual(sr.resolve_tp(None, env, preset, ""), 3)
        self.assertEqual(sr.resolve_tp(None, {}, preset, ""), 7)
        self.assertEqual(sr.resolve_tp(None, {}, {}, ""), 1)


class TestBuildExportPrefix(unittest.TestCase):
    def test_empty_when_no_keys_in_env(self) -> None:
        self.assertEqual(sr.build_export_prefix({}, ["A"]), "")

    def test_joins_exports(self) -> None:
        env = {"A": "1 2", "B": "x"}
        out = sr.build_export_prefix(env, ["A", "B"])
        self.assertEqual(
            out,
            f"export A={shlex.quote('1 2')} && export B={shlex.quote('x')} && ",
        )


class TestShellQuotePathAllowHome(unittest.TestCase):
    def test_tilde_rules(self) -> None:
        self.assertEqual(sr.shell_quote_path_allow_home("~"), "$HOME")
        self.assertEqual(sr.shell_quote_path_allow_home("~/a b"), "$HOME/" + shlex.quote("a b"))
        self.assertEqual(sr.shell_quote_path_allow_home("/usr/bin"), shlex.quote("/usr/bin"))


class TestRunBenchmark(unittest.TestCase):
    def test_no_success_returns_none(self) -> None:
        with mock.patch.object(
            sr.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError("fail"),
        ):
            self.assertIsNone(
                sr.run_benchmark(
                    base_url="http://127.0.0.1:9",
                    api_key="k",
                    model="m",
                    prompt="p",
                    max_tokens=1,
                    requests=2,
                    timeout_sec=1,
                )
            )

    def test_success_metrics(self) -> None:
        fake_resp = mock.Mock()
        fake_resp.read.return_value = b"{}"
        fake_ctx = mock.Mock()
        fake_ctx.__enter__ = mock.Mock(return_value=fake_resp)
        fake_ctx.__exit__ = mock.Mock(return_value=False)

        with mock.patch.object(sr.urllib.request, "urlopen", return_value=fake_ctx):
            out = sr.run_benchmark(
                base_url="http://127.0.0.1:9",
                api_key="k",
                model="m",
                prompt="p",
                max_tokens=1,
                requests=2,
                timeout_sec=1,
            )
        assert out is not None
        self.assertEqual(out["successful_requests"], 2)
        self.assertEqual(out["failed_requests"], 0)
        self.assertIn("avg_latency_sec", out)
        self.assertIn("throughput_rps", out)


class TestBuildParser(unittest.TestCase):
    def test_subcommands_required(self) -> None:
        parser = sr.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([])


if __name__ == "__main__":
    unittest.main()
