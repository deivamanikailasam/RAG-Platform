"""Tests for the Step 8 shell scripts: model-path.sh, run-tei.sh and install-tei-agents.sh.

TEI, SOPS and launchd are not available here, so each test puts small stand-in programs
(`sops`, `text-embeddings-router`, `launchctl`) first on PATH and checks what the scripts
would have run: the exact flags, and that the API key travels only as an environment variable.
"""

import os
import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MODEL_PATH = REPO / "scripts" / "model-path.sh"
RUN_TEI = REPO / "scripts" / "run-tei.sh"
INSTALL = REPO / "scripts" / "install-tei-agents.sh"
FAKE_KEY = "not-a-real-key-just-for-tests"  # low-entropy stand-in, never a real secret

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _write_tool(bin_dir: Path, name: str, body: str) -> None:
    tool = bin_dir / name
    tool.write_text("#!/bin/sh\n" + body)
    tool.chmod(0o755)


def _run(script: Path, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed script path from this repo
        [str(script), *args], env=env, capture_output=True, text=True, check=False
    )


# ---------------------------------------------------------------- model-path.sh


def _snapshot(hf_home: Path, repo: str, sha: str) -> Path:
    folder = hf_home / "hub" / f"models--{repo.replace('/', '--')}" / "snapshots" / sha
    folder.mkdir(parents=True)
    return folder


def test_model_path_prints_the_snapshot_folder(tmp_path: Path) -> None:
    hf_home = tmp_path / "hf"
    folder = _snapshot(hf_home, "Qwen/Qwen3-Embedding-0.6B", "a" * 40)
    result = _run(
        MODEL_PATH, ["Qwen/Qwen3-Embedding-0.6B"], {**os.environ, "HF_HOME": str(hf_home)}
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(folder)  # no trailing slash


def test_model_path_picks_an_exact_revision(tmp_path: Path) -> None:
    hf_home = tmp_path / "hf"
    _snapshot(hf_home, "BAAI/bge-reranker-v2-m3", "a" * 40)
    wanted = _snapshot(hf_home, "BAAI/bge-reranker-v2-m3", "b" * 40)
    env = {**os.environ, "HF_HOME": str(hf_home)}
    result = _run(MODEL_PATH, ["BAAI/bge-reranker-v2-m3", "b" * 40], env)
    assert result.stdout.strip() == str(wanted)


def test_model_path_defaults_to_the_home_cache(tmp_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if k != "HF_HOME"}
    env["HOME"] = str(tmp_path)
    folder = _snapshot(tmp_path / ".cache" / "huggingface", "BAAI/bge-reranker-v2-m3", "c" * 40)
    result = _run(MODEL_PATH, ["BAAI/bge-reranker-v2-m3"], env)
    assert result.stdout.strip() == str(folder)


@pytest.mark.parametrize("rev", [[], ["d" * 40]])
def test_model_path_fails_clearly_when_not_downloaded(tmp_path: Path, rev: list[str]) -> None:
    hf_home = tmp_path / "hf"
    if rev:  # the model exists, but not at this revision
        _snapshot(hf_home, "Qwen/Qwen3-Embedding-0.6B", "a" * 40)
    env = {**os.environ, "HF_HOME": str(hf_home)}
    result = _run(MODEL_PATH, ["Qwen/Qwen3-Embedding-0.6B", *rev], env)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "not downloaded: Qwen/Qwen3-Embedding-0.6B" in result.stderr


# ---------------------------------------------------------------- run-tei.sh


def test_run_tei_passes_the_key_by_environment_only(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "record"
    # Stand-in for `sops exec-env FILE CMD`: decrypt (pretend) and run CMD with the secrets set.
    _write_tool(
        bin_dir,
        "sops",
        f'[ "$1" = exec-env ] || exit 9\necho "file=$2" > "{record}.sops"\n'
        f'echo "age=$SOPS_AGE_KEY_FILE" >> "{record}.sops"\n'
        f'TEI_API_KEY="{FAKE_KEY}" exec sh -c "$3"\n',
    )
    _write_tool(
        bin_dir,
        "text-embeddings-router",
        f'echo "API_KEY=$API_KEY" > "{record}"\nfor a in "$@"; do echo "$a" >> "{record}"; done\n',
    )
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
    }
    env.pop("SOPS_AGE_KEY_FILE", None)
    model_dir = tmp_path / "snap shot" / ("e" * 40)  # a space in the path must survive quoting
    result = _run(RUN_TEI, [str(model_dir), "8083", "9083", "qwen3-embedding-0.6b"], env)
    assert result.returncode == 0, result.stderr

    lines = record.read_text().splitlines()
    assert lines[0] == f"API_KEY={FAKE_KEY}"
    args = lines[1:]
    assert args == [
        "--model-id", str(model_dir),
        "--hostname", "127.0.0.1",  # never TEI's default 0.0.0.0
        "--port", "8083",
        "--prometheus-port", "9083",  # not the shared default 9000
        "--served-model-name", "qwen3-embedding-0.6b",
        "--json-output",
    ]  # fmt: skip
    assert FAKE_KEY not in args  # the key is never a command-line argument
    assert "--api-key" not in args
    sops_record = (tmp_path / "record.sops").read_text().splitlines()
    assert sops_record == [
        "file=secrets/dev.enc.env",
        f"age={tmp_path / 'home' / '.config' / 'sops' / 'age' / 'keys.txt'}",
    ]


# ---------------------------------------------------------------- install-tei-agents.sh


def _install(tmp_path: Path, **extra_env: str) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_tool(bin_dir, "launchctl", f'echo "$*" >> "{tmp_path / "launchctl-calls"}"\n')
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        **extra_env,
    }
    return _run(INSTALL, [], env)


def test_install_writes_and_loads_both_agents(tmp_path: Path) -> None:
    embed_dir, rerank_dir = "/snapshots/embed", "/snapshots/rerank"
    result = _install(tmp_path, EMBED_DIR=embed_dir, RERANK_DIR=rerank_dir)
    assert result.returncode == 0, result.stderr

    home = tmp_path / "home"
    agents = home / "Library" / "LaunchAgents"
    logs = home / "Library" / "Logs" / "rag-platform"
    assert logs.is_dir()
    expected = {
        "embedder": [embed_dir, "8083", "9083", "qwen3-embedding-0.6b"],
        "reranker": [rerank_dir, "8084", "9084", "bge-reranker-v2-m3"],
    }
    for name, tei_args in expected.items():
        with (agents / f"com.rag-platform.{name}.plist").open("rb") as fh:
            plist = plistlib.load(fh)
        assert plist["Label"] == f"com.rag-platform.{name}"
        assert plist["ProgramArguments"] == [
            "/bin/bash",
            f"{REPO}/scripts/run-tei.sh",
            *tei_args,
        ]
        assert plist["EnvironmentVariables"] == {
            "PATH": "/opt/homebrew/bin:/usr/bin:/bin",
            "SOPS_AGE_KEY_FILE": f"{home}/.config/sops/age/keys.txt",
        }
        assert plist["RunAtLoad"] is True
        assert plist["KeepAlive"] is True
        assert plist["ThrottleInterval"] == 30
        assert plist["StandardOutPath"] == str(logs / f"{name}.log")
        assert plist["StandardErrorPath"] == plist["StandardOutPath"]
        assert "loaded com.rag-platform." + name in result.stdout

    uid = os.getuid()
    assert (tmp_path / "launchctl-calls").read_text().splitlines() == [
        f"bootout gui/{uid}/com.rag-platform.embedder",
        f"bootstrap gui/{uid} {agents}/com.rag-platform.embedder.plist",
        f"bootout gui/{uid}/com.rag-platform.reranker",
        f"bootstrap gui/{uid} {agents}/com.rag-platform.reranker.plist",
    ]


def test_install_refuses_without_snapshot_folders(tmp_path: Path) -> None:
    result = _install(tmp_path, RERANK_DIR="/snapshots/rerank")
    assert result.returncode != 0
    assert "EMBED_DIR" in result.stderr
    assert not (tmp_path / "launchctl-calls").exists()


def test_reference_plists_match_the_script_output() -> None:
    """The copies under bootstrap/home/ must stay in step with what the script generates."""
    ref = REPO / "bootstrap" / "home" / "Library" / "LaunchAgents"
    ports = {"embedder": ("8083", "9083"), "reranker": ("8084", "9084")}
    for name, (port, metrics) in ports.items():
        with (ref / f"com.rag-platform.{name}.plist").open("rb") as fh:
            plist = plistlib.load(fh)
        args = plist["ProgramArguments"]
        assert plist["Label"] == f"com.rag-platform.{name}"
        assert args[0] == "/bin/bash"
        assert args[1].endswith("/scripts/run-tei.sh")
        assert args[3:5] == [port, metrics]
        assert set(plist["EnvironmentVariables"]) == {"PATH", "SOPS_AGE_KEY_FILE"}
        assert plist["KeepAlive"] is True
