"""Agents (extension 03): search and answer as MCP tools over stdio, with the launch identity."""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from rag_core import config as cfg
from rag_core import evaluate as ev
from rag_core.cli import main
from rag_core.mcp import (
    TOOLS,
    IdentityError,
    McpServer,
    RagTools,
    StaticIdentity,
    TokenIdentity,
    identity_from,
)
from rag_core.registry import Container

ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "examples/eval/handbook.yaml"
VALID = "good"  # a fake token for a fake verifier
ANN = StaticIdentity("ann", ("all-staff",), ("public", "internal"))


@pytest.fixture(scope="module")
def container() -> Container:
    config = cfg.resolve(yaml.safe_load((ROOT / "rag.yaml").read_text()), "offline", env={})
    c = Container(config, "test")
    ev.ingest_corpus(c, ev.load_dataset(DATASET), DATASET.parent)
    return c


def rpc(server: McpServer, method: str, params: dict[str, Any] | None = None, id_: int = 1) -> Any:
    return server.handle({"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}})


def rpc_raw(server: McpServer, msg: dict[str, Any]) -> Any:
    return server.handle(msg)


def test_initialize_list_and_ping(container: Container) -> None:
    s = McpServer(RagTools(container, ANN, log=lambda e: None))
    init = rpc(
        s,
        "initialize",
        {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}},
    )
    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert init["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert (
        rpc(s, "initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"]
        == "2025-06-18"
    )
    assert s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None  # no reply
    assert rpc(s, "ping")["result"] == {}
    tools = rpc(s, "tools/list")["result"]["tools"]
    assert [t["name"] for t in tools] == ["search", "answer"]
    for t in tools:  # no tool takes an identity: the model can't choose who it is
        assert not {"subject", "group", "groups", "principal", "classification"} & set(
            t["inputSchema"]["properties"]
        )
    assert rpc(s, "nope")["error"]["code"] == -32601
    assert rpc(s, "tools/call", {"name": "delete_everything"})["error"]["code"] == -32602
    assert rpc_raw(s, {"id": 3, "method": "ping"})["error"]["code"] == -32600  # not JSON-RPC 2.0


def test_tools_search_and_answer_as_the_launch_identity(container: Container) -> None:
    events: list[dict[str, Any]] = []
    s = McpServer(RagTools(container, ANN, log=events.append))
    r = rpc(
        s,
        "tools/call",
        {"name": "search", "arguments": {"question": "What does error E-1107 mean?", "k": 3}},
    )
    result = r["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["hits"][0]["document"].endswith("vpn-troubleshooting.md")
    assert "E-1107" in result["content"][0]["text"]
    a = rpc(
        s,
        "tools/call",
        {"name": "answer", "arguments": {"question": "How many days a week can I work from home?"}},
    )
    assert "three days" in a["result"]["structuredContent"]["text"]
    assert "Sources:" in a["result"]["content"][0]["text"]
    secret = rpc(
        s,
        "tools/call",
        {"name": "search", "arguments": {"question": "executive bonus pool", "k": 20}},
    )
    assert not any(
        h["document"].endswith("exec-compensation.md")
        for h in secret["result"]["structuredContent"]["hits"]
    )
    # every call is logged with who asked and which documents were used, never the question
    assert [e["tool"] for e in events] == ["search", "answer", "search"]
    assert all(e["subject"] == "ann" and e["ok"] for e in events)
    assert not any("E-1107" in json.dumps(e) for e in events)


def test_bad_arguments_are_tool_errors_not_crashes(container: Container) -> None:
    s = McpServer(RagTools(container, ANN, log=lambda e: None))
    for args in ({"question": ""}, {"question": "x", "subject": "ceo"}, {"question": "x", "k": 500},
                 {"question": "x", "filter": {"department": {"regex": ".*"}}}):  # fmt: skip
        r = rpc(s, "tools/call", {"name": "search", "arguments": args})["result"]
        assert r["isError"] is True, args


def test_identity_is_required_and_tokens_are_checked_on_every_call(
    tmp_path: Path, container: Container
) -> None:
    flags = SimpleNamespace(subject=None, group=[], classification=[], tenant="default", token_file=None,
                            oidc_issuer=None, oidc_audience=None, oidc_jwks_url=None)  # fmt: skip
    with pytest.raises(IdentityError, match="identity is required"):
        identity_from(flags)
    flags.subject, flags.group, flags.classification = "ann", ["all-staff"], ["internal"]
    assert identity_from(flags) == StaticIdentity("ann", ("all-staff",), ("internal",))
    flags.classification = ["top-secret"]
    with pytest.raises(IdentityError, match="unknown classification"):
        identity_from(flags)

    class Verifier:
        def verify(self, token: str) -> Any:
            if token != VALID:
                raise ValueError("token expired")
            return SimpleNamespace(subject="sub-123", groups=frozenset({"all-staff"}))

    token = tmp_path / "token"
    token.write_text("good")
    ident = TokenIdentity(token, Verifier(), ("public", "internal"))
    assert ident.principal().subject == "sub-123"
    s = McpServer(RagTools(container, ident, log=lambda e: None))
    ok = rpc(s, "tools/call", {"name": "search", "arguments": {"question": "VPN error E-4021"}})
    assert ok["result"]["isError"] is False
    token.write_text("stale")  # the token expired between two calls: refused at once
    bad = rpc(s, "tools/call", {"name": "search", "arguments": {"question": "VPN error E-4021"}})
    assert bad["result"]["isError"] is True
    assert "token rejected" in bad["result"]["content"][0]["text"]


def test_serve_over_stdio_lines(container: Container) -> None:
    s = McpServer(RagTools(container, ANN, log=lambda e: None))
    lines = [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}), "not json", "",
             json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})]  # fmt: skip
    out = io.StringIO()
    s.serve(lines, out)
    replies = [json.loads(x) for x in out.getvalue().splitlines()]
    assert [r.get("id") for r in replies] == [1, None]
    assert replies[1]["error"]["code"] == -32700
    assert len(TOOLS) == 2


def test_rag_mcp_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    base = ["mcp", "--file", str(ROOT / "rag.yaml"), "--profile", "offline"]
    monkeypatch.delenv("RAG_MCP_SUBJECT", raising=False)
    assert main(base) == 2  # no identity: refuses to start
    assert "identity is required" in capsys.readouterr().err
    call = {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": "answer", "arguments": {"question": "What does error E-1107 mean?"}}}  # fmt: skip
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(call) + "\n"))
    assert main([*base, "--subject", "ann", "--group", "all-staff", "--corpus", str(DATASET)]) == 0
    reply = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert reply["id"] == 7
    assert "MFA push timed out" in reply["result"]["structuredContent"]["text"]
