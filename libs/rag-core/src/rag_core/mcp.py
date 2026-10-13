"""The platform's search and answer as MCP tools (extension 03): `rag mcp`.

An AI agent (Claude Desktop, Claude Code, an IDE, your own agent) starts `rag mcp` and talks to
it over stdin/stdout with the Model Context Protocol: `tools/list` shows two tools, `search` and
`answer`; `tools/call` runs them. This is a minimal, dependency-free implementation of the parts
of MCP a tool server needs (JSON-RPC 2.0, one message per line: initialize, ping, tools/list,
tools/call); the official `mcp` Python SDK is the reference for anything more (resources,
prompts, HTTP transport).

Trust model, in short (docs/extensions/03-more-rag-architectures.md has the full version):
  * WHO is asking is fixed when the server starts, by the person or system that launches it,
    never by the model: `--subject` (+ `--group`, `--classification`), or a verified OIDC access
    token re-read and re-verified on EVERY call (`--token-file`). No identity: it won't start.
  * Tools take no identity arguments: a prompt-injected agent can't ask "as the CFO".
  * Every search runs through the same access filter as rag-api; filters only narrow it.
  * Each call is logged to stderr as one JSON line (tool, subject, documents, outcome); the
    question and answer text are not logged.
  * stdio means "the user's own machine, the user's own permissions". To serve many people over
    a network, put MCP behind rag-api (its tokens, OPA policy and audit log), not this command.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, cast

from rag_core.types import Classification, Principal

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER = {"name": "rag-platform", "version": "1.0.0"}
LEVELS = ("public", "internal", "confidential", "restricted")
MAX_QUESTION = 2000

# JSON-RPC error codes
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602


class IdentityError(Exception):
    """No acceptable caller identity: the call (or the server) is refused."""


# ================================================================ identity


@dataclass(frozen=True)
class StaticIdentity:
    """The identity given at launch: the person running the agent on their own machine."""

    subject: str
    groups: tuple[str, ...]
    classifications: tuple[Classification, ...]
    tenant: str = "default"

    def principal(self) -> Principal:
        return Principal(self.subject, self.groups, self.classifications, self.tenant)


class TokenIdentity:
    """An OIDC access token in a file (refreshed by whatever logs the user in), verified on every
    call: issuer, audience, signature and expiry (rag_common.auth, as rag-api). The token's groups
    are used; classifications are capped by what the launcher allows."""

    def __init__(self, token_file: Path, verifier: Any, classifications: tuple[Classification, ...],
                 tenant: str = "default") -> None:  # fmt: skip
        self.token_file, self.verifier = token_file, verifier
        self.classifications, self.tenant = classifications, tenant

    def principal(self) -> Principal:
        try:
            token = self.token_file.read_text(encoding="utf-8").strip()
        except OSError as e:
            raise IdentityError(f"can't read the token file: {e.strerror}") from None
        if not token:
            raise IdentityError("the token file is empty")
        try:
            who = self.verifier.verify(token)
        except Exception as e:  # expired, wrong issuer/audience, bad signature, keys unreachable
            raise IdentityError(f"token rejected: {e}") from None
        return Principal(who.subject, tuple(sorted(who.groups)), self.classifications, self.tenant)


# ================================================================ tools


def _stderr(event: dict[str, Any]) -> None:
    """stdout carries the protocol: the call log goes to stderr, one JSON line per call."""
    sys.stderr.write(json.dumps(event, default=str) + "\n")
    sys.stderr.flush()


TOOLS: list[dict[str, Any]] = [
    {
        "name": "search",
        "title": "Search the knowledge base",
        "description": (
            "Search the company documents this user may see. Returns the best passages with their "
            "source document, title and section. Use it to find facts before answering."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "What to look for, in plain words."},
                "k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                "filter": {
                    "type": "object",
                    "description": 'Optional metadata filter, e.g. {"department": "hr"}.',
                },
            },
            "required": ["question"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "answer",
        "title": "Answer from the knowledge base",
        "description": (
            "Answer a question from the company documents this user may see, with [doc n] citations, "
            "or say the documents don't contain the answer. Guardrails apply."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "session_id": {
                    "type": "string",
                    "description": "Optional: follow-ups in one conversation.",
                },
                "filter": {"type": "object"},
            },
            "required": ["question"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
]


class RagTools:
    """The two tools, on a container built from rag.yaml, as the launch identity."""

    def __init__(self, container: Any, identity: StaticIdentity | TokenIdentity,
                 log: Callable[[dict[str, Any]], None] | None = None) -> None:  # fmt: skip
        from rag_core.answer import AnswerPipeline
        from rag_core.search import SearchPipeline

        self.identity = identity
        self.search_pipe = SearchPipeline(container)
        self.answer_pipe = AnswerPipeline(container)
        self.log = log or _stderr

    @staticmethod
    def _args(args: Mapping[str, Any], allowed: set[str]) -> tuple[str, dict[str, Any]]:
        extra = set(args) - allowed
        if extra:
            raise ValueError(f"unknown argument(s): {', '.join(sorted(extra))}")
        q = args.get("question")
        if not isinstance(q, str) or not q.strip():
            raise ValueError("question: a non-empty string is required")
        if len(q) > MAX_QUESTION:
            raise ValueError(f"question: at most {MAX_QUESTION} characters")
        f = args.get("filter") or {}
        if not isinstance(f, dict):
            raise ValueError("filter: an object is expected")
        return q.strip(), f

    def call(self, name: str, args: Mapping[str, Any]) -> dict[str, Any]:
        from rag_core import filters
        from rag_core.answer import answer_dict
        from rag_core.types import Query

        started = time.perf_counter()
        event: dict[str, Any] = {"event": "rag.mcp.call", "tool": name}
        try:
            who = self.identity.principal()  # every call: an expired token stops working at once
            event["subject"] = who.subject
            if name == "search":
                q, f = self._args(args, {"question", "k", "filter"})
                k = args.get("k", 5)
                if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= 20:
                    raise ValueError("k: an integer from 1 to 20")
                hits = self.search_pipe.search(Query(q, who, filters.validate(f), k=k)).hits
                rows = [{"n": i, "document": h.chunk.document_uri, "title": str(h.chunk.metadata.get("title", "")),
                         "section": str(h.chunk.metadata.get("section", "")), "score": round(h.score, 4),
                         "text": h.chunk.text[:1200]} for i, h in enumerate(hits, 1)]  # fmt: skip
                event["documents"] = sorted({r["document"] for r in rows})
                text = "\n\n".join(f"[{r['n']}] {r['title']} > {r['section']} ({r['document']})\n{r['text']}"
                                   for r in rows) or "No permitted documents match."  # fmt: skip
                result = {"hits": rows}
            elif name == "answer":
                q, f = self._args(args, {"question", "session_id", "filter"})
                session = args.get("session_id")
                if session is not None and (not isinstance(session, str) or len(session) > 128):
                    raise ValueError("session_id: a string of at most 128 characters")
                a = self.answer_pipe.answer(q, who, session_id=session, filters=filters.validate(f))
                result = answer_dict(a)
                event |= {"documents": sorted({str(c["document"]) for c in result["citations"]}),
                          "abstained": a.abstained, "blocked": bool(a.blocked)}  # fmt: skip
                sources = "\n".join(
                    f"[doc {c['n']}] {c['title']} ({c['document']})" for c in result["citations"]
                )
                text = a.text + (f"\n\nSources:\n{sources}" if sources else "")
            else:
                raise ValueError(f"unknown tool: {name}")
        except (IdentityError, ValueError) as e:
            event |= {
                "ok": False,
                "error": type(e).__name__,
                "ms": round((time.perf_counter() - started) * 1000, 1),
            }
            self.log(event)
            return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}
        event |= {"ok": True, "ms": round((time.perf_counter() - started) * 1000, 1)}
        self.log(event)
        return {
            "content": [{"type": "text", "text": text}],
            "structuredContent": result,
            "isError": False,
        }


# ================================================================ JSON-RPC over stdio


def _error(id_: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


class McpServer:
    def __init__(self, tools: Any) -> None:
        self.tools = tools

    def handle(self, msg: Any) -> dict[str, Any] | None:
        """One JSON-RPC message in, its response out (None for a notification)."""
        if (
            not isinstance(msg, dict)
            or msg.get("jsonrpc") != "2.0"
            or not isinstance(msg.get("method"), str)
        ):
            return _error(
                msg.get("id") if isinstance(msg, dict) else None, INVALID_REQUEST, "invalid request"
            )
        method, params, id_ = msg["method"], msg.get("params") or {}, msg.get("id")
        if "id" not in msg:  # notifications (initialized, cancelled): nothing to answer
            return None
        if not isinstance(params, dict):
            return _error(id_, INVALID_PARAMS, "params must be an object")
        if method == "initialize":
            asked = params.get("protocolVersion")
            version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            return {"jsonrpc": "2.0", "id": id_, "result": {
                "protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER,
                "instructions": "Search and answer from the company knowledge base, as the user who started this server."}}  # fmt: skip
        if method == "ping":
            return {"jsonrpc": "2.0", "id": id_, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": id_, "result": {"tools": TOOLS}}
        if method == "tools/call":
            name, args = params.get("name"), params.get("arguments") or {}
            if not isinstance(name, str) or name not in {t["name"] for t in TOOLS}:
                return _error(id_, INVALID_PARAMS, f"unknown tool: {name!r}")
            if not isinstance(args, dict):
                return _error(id_, INVALID_PARAMS, "arguments must be an object")
            return {"jsonrpc": "2.0", "id": id_, "result": self.tools.call(name, args)}
        return _error(id_, METHOD_NOT_FOUND, f"method not found: {method}")

    def serve(self, lines: Iterable[str], out: IO[str]) -> None:
        for line in lines:
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                reply: Any = _error(None, PARSE_ERROR, "parse error")
            else:
                if isinstance(msg, list):  # a batch (older protocol versions)
                    reply = [r for r in (self.handle(m) for m in msg) if r is not None] or None
                else:
                    reply = self.handle(msg)
            if reply is not None:
                out.write(json.dumps(reply, default=str) + "\n")
                out.flush()


def identity_from(args: Any) -> StaticIdentity | TokenIdentity:
    """The launch identity from `rag mcp` flags (or RAG_MCP_* environment variables)."""
    import os

    raw = args.classification or os.environ.get("RAG_MCP_CLASSIFICATIONS", "public,internal").split(
        ","
    )
    levels = tuple(c.strip() for c in raw if c.strip())
    bad = [c for c in levels if c not in LEVELS]
    if bad:
        raise IdentityError(f"unknown classification(s): {', '.join(bad)}")
    classes = cast(tuple[Classification, ...], levels)
    token_file = args.token_file or os.environ.get("RAG_MCP_TOKEN_FILE")
    if token_file:
        from rag_common.auth import OIDCSettings, TokenVerifier

        issuer = args.oidc_issuer or os.environ.get("RAG_MCP_OIDC_ISSUER")
        audience = args.oidc_audience or os.environ.get("RAG_MCP_OIDC_AUDIENCE")
        jwks = args.oidc_jwks_url or os.environ.get("RAG_MCP_OIDC_JWKS_URL")
        if not (issuer and audience and jwks):
            raise IdentityError(
                "--token-file needs --oidc-issuer, --oidc-audience and --oidc-jwks-url"
            )
        return TokenIdentity(Path(token_file), TokenVerifier(OIDCSettings(issuer, audience, jwks)), classes,
                             args.tenant)  # fmt: skip
    subject = args.subject or os.environ.get("RAG_MCP_SUBJECT")
    if not subject:
        raise IdentityError(
            "a caller identity is required: --subject (with --group), or --token-file"
        )
    groups = tuple(
        sorted(args.group or [g for g in os.environ.get("RAG_MCP_GROUPS", "").split(",") if g])
    )
    return StaticIdentity(subject, groups, classes, args.tenant)


__all__ = ["TOOLS", "IdentityError", "McpServer", "RagTools", "StaticIdentity", "TokenIdentity"]
