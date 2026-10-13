"""Run scripts/install-model-agents.sh against a fake HOME, uv and launchctl.

launchd only exists on macOS, so the test puts stand-in `uv` and `launchctl` programs first
on PATH, then checks the generated plists parse and say exactly what the guide intends.
"""

import os
import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "install-model-agents.sh"
QUALITY = "mlx-community/Qwen3.8-27B-8bit"
FAST = "lmstudio-community/Qwen3.6-35B-A3B-MLX-4bit"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _fake_bin(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "launchctl-calls"
    (bin_dir / "launchctl").write_text(f'#!/bin/sh\necho "$*" >> "{calls}"\n')
    (bin_dir / "uv").write_text("#!/bin/sh\nexit 0\n")
    for tool in bin_dir.iterdir():
        tool.chmod(0o755)
    return bin_dir


def _run(tmp_path: Path, **extra_env: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "PATH": f"{_fake_bin(tmp_path)}{os.pathsep}{os.environ['PATH']}",
        **extra_env,
    }
    return subprocess.run(  # noqa: S603 - fixed script path from this repo
        [str(SCRIPT)], env=env, capture_output=True, text=True, check=False
    )


def test_writes_and_loads_both_agents(tmp_path: Path) -> None:
    result = _run(tmp_path, QUALITY_MODEL=QUALITY, FAST_MODEL=FAST)
    assert result.returncode == 0, result.stderr

    agents = tmp_path / "home" / "Library" / "LaunchAgents"
    logs = tmp_path / "home" / "Library" / "Logs" / "rag-platform"
    assert logs.is_dir()

    expected = {
        "qwen-quality": (QUALITY, "8081", "{}"),
        "qwen-fast": (FAST, "8082", '{"enable_thinking": false}'),
    }
    for name, (model, port, template_args) in expected.items():
        with (agents / f"com.rag-platform.{name}.plist").open("rb") as fh:
            plist = plistlib.load(fh)
        args = plist["ProgramArguments"]
        assert plist["Label"] == f"com.rag-platform.{name}"
        assert args[0] == str(tmp_path / "bin" / "uv")
        assert args[1:5] == ["run", "--project", f"{REPO}/infra/model-serving", "mlx_lm.server"]
        assert args[args.index("--model") + 1] == model
        assert args[args.index("--host") + 1] == "127.0.0.1"  # never 0.0.0.0
        assert args[args.index("--port") + 1] == port
        assert args[args.index("--allowed-origins") + 1] == "http://localhost"
        assert args[args.index("--chat-template-args") + 1] == template_args
        assert plist["EnvironmentVariables"] == {"HF_HUB_OFFLINE": "1"}
        assert plist["RunAtLoad"] is True
        assert plist["KeepAlive"] is True
        assert plist["ThrottleInterval"] == 30
        assert plist["StandardOutPath"] == str(logs / f"{name}.log")
        assert plist["StandardErrorPath"] == plist["StandardOutPath"]

    calls = (tmp_path / "launchctl-calls").read_text().splitlines()
    uid = os.getuid()
    assert calls == [
        f"bootout gui/{uid}/com.rag-platform.qwen-quality",
        f"bootstrap gui/{uid} {agents}/com.rag-platform.qwen-quality.plist",
        f"bootout gui/{uid}/com.rag-platform.qwen-fast",
        f"bootstrap gui/{uid} {agents}/com.rag-platform.qwen-fast.plist",
    ]


def test_refuses_to_run_without_model_names(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.returncode != 0
    assert "set QUALITY_MODEL" in result.stderr


def test_reference_plists_match_the_script_output() -> None:
    """The copies under bootstrap/home/ must stay in step with what the script generates."""
    ref = REPO / "bootstrap" / "home" / "Library" / "LaunchAgents"
    for name in ("qwen-quality", "qwen-fast"):
        with (ref / f"com.rag-platform.{name}.plist").open("rb") as fh:
            plist = plistlib.load(fh)
        assert plist["Label"] == f"com.rag-platform.{name}"
        assert plist["ProgramArguments"][4] == "mlx_lm.server"
        assert plist["EnvironmentVariables"] == {"HF_HUB_OFFLINE": "1"}
