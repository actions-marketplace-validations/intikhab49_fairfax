"""`fairfax mcp`: a Model Context Protocol server on stdio, so coding agents can ask fairfax instead of guessing.

It speaks JSON-RPC 2.0, one message per line, and exposes four read-only tools over the bundled
dataset. No network calls and no dependencies beyond the standard library and PyYAML.
"""

from __future__ import annotations

import datetime as dt
import json
import sys

from . import __version__
from . import check as check_mod
from . import dataset as dataset_mod
from . import explain as explain_mod
from . import render
from .dataset import CLOUDS, TENANTS
from .scan import HostIndex, scan, scan_text

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = (
    "fairfax answers whether Microsoft features and endpoints work in the US government clouds (GCC, GCC High, "
    "DoD and Azure Government), from Microsoft's own availability tables. Every answer quotes the Microsoft row "
    "it comes from, with the page and dates. Use find_features to get feature keys, check_plan to check a "
    "planned stack, scan_code to find hosts from the wrong cloud, and explain_error for AADSTS sign-in errors. "
    "If fairfax doesn't list a feature, that says nothing about whether it works: say so rather than guess.")
CLOUD_PROPS = {
    "tenant": {"type": "string", "enum": list(TENANTS),
               "description": "Microsoft 365 tenant type: gcc, gcchigh or dod"},
    "azure": {"type": "string", "enum": list(CLOUDS),
              "description": "Azure cloud of the subscription: commercial or government"},
}
READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
TOOLS = [
    {"name": "find_features", "title": "Find fairfax feature keys",
     "description": "Search the dataset for feature keys by product or feature name (for example 'sentinel', "
                    "'copilot researcher', 'shared channels') and show each one's status per cloud.",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
     "annotations": READ_ONLY},
    {"name": "check_plan", "title": "Check a gov-cloud plan",
     "description": "Check a planned stack (tenant type, Azure cloud and feature keys) against Microsoft's "
                    "availability tables. Returns what is blocked, cross-cloud, retiring or fine, each with the "
                    "Microsoft row and page it comes from.",
     "inputSchema": {"type": "object", "properties": {
         **CLOUD_PROPS, "features": {"type": "array", "items": {"type": "string"},
                                     "description": "feature keys from find_features"}},
         "required": ["tenant", "features"]},
     "annotations": READ_ONLY},
    {"name": "scan_code", "title": "Scan code for wrong-cloud endpoints",
     "description": "Find Microsoft hosts that belong to the wrong cloud (for example login.microsoftonline.com "
                    "in a GCC High app) in code or config. Pass the text itself, or local file and folder paths.",
     "inputSchema": {"type": "object", "properties": {
         **CLOUD_PROPS, "text": {"type": "string", "description": "code or config to scan"},
         "filename": {"type": "string", "description": "name to report for text, such as settings.py"},
         "paths": {"type": "array", "items": {"type": "string"}, "description": "files or folders to scan"}}},
     "annotations": READ_ONLY},
    {"name": "explain_error", "title": "Explain a cross-cloud sign-in error",
     "description": "Decode an AADSTS sign-in error caused by mixing clouds (such as AADSTS900439), from a code or "
                    "the whole message: cause, fix and the right sign-in host for the given clouds.",
     "inputSchema": {"type": "object", "properties": {
         **CLOUD_PROPS, "error": {"type": "string", "description": "an AADSTS code or the error message"}},
         "required": ["error"]},
     "annotations": READ_ONLY},
]


class ToolError(Exception):
    """A tool ran but can't answer: reported to the agent as a tool result with isError set."""


def _clouds(args: dict) -> tuple:
    tenant, azure = args.get("tenant"), args.get("azure")
    if tenant is not None and tenant not in TENANTS:
        raise ToolError(f"tenant must be one of {', '.join(TENANTS)}")
    if azure is not None and azure not in CLOUDS:
        raise ToolError(f"azure must be one of {', '.join(CLOUDS)}")
    return tenant, azure


class Server:
    def __init__(self, ds=None, today: dt.date | None = None):
        self.ds = ds or dataset_mod.load()
        self.today = today

    # ------------------------------------------------------------ tools
    def find_features(self, args: dict) -> str:
        words = str(args.get("query", "")).lower().split()
        if not words:
            raise ToolError("query is empty")
        facts = [f for f in self.ds.facts if all(w in f.feature or w in f.name.lower() for w in words)]
        if not facts:
            raise ToolError(f"No feature matches {args['query']!r}. Try one product word, such as 'teams' or "
                            "'purview'. fairfax doesn't cover every Microsoft feature.")
        keys = list(dict.fromkeys(f.feature for f in facts))
        first = set(keys[:60])
        text = render.facts_text([f for f in facts if f.feature in first], self.ds)
        if len(keys) > 60:
            text += f"\nShowing 60 of {len(keys)} matching features; add words to narrow the search.\n"
        return text

    def check_plan(self, args: dict) -> str:
        tenant, azure = _clouds(args)
        if tenant is None:
            raise ToolError("tenant is required: gcc, gcchigh or dod")
        features = args.get("features")
        if not isinstance(features, list) or not features or not all(isinstance(f, str) for f in features):
            raise ToolError("features must be a non-empty list of feature keys (see find_features)")
        plan = check_mod.Plan(tenant, azure, list(dict.fromkeys(features)), "plan from an agent")
        report = check_mod.check(self.ds, plan, self.today)
        text = render.check_md(report)
        if report.unknown:
            hints = [f"- `{k}`" + (f": did you mean {', '.join(f'`{c}`' for c in v)}?" if v else "")
                     for k, v in report.unknown.items()]
            text += "\n## Unknown feature keys\n\n" + "\n".join(hints) + "\n"
            if len(report.unknown) == len(plan.features):
                raise ToolError(text)
        return text

    def scan_code(self, args: dict) -> str:
        tenant, azure = _clouds(args)
        if not tenant and not azure:
            raise ToolError("say which clouds you target: tenant and/or azure")
        if args.get("paths"):
            hits, files = scan([str(p) for p in args["paths"]], self.ds, tenant, azure)
        elif isinstance(args.get("text"), str):
            hits = scan_text(args["text"], str(args.get("filename") or "input"), HostIndex(self.ds.endpoints),
                             tenant, azure)
            files = 1
        else:
            raise ToolError("pass text to scan, or paths")
        return render.scan_md(hits, files, tenant, azure)

    def explain_error(self, args: dict) -> str:
        tenant, azure = _clouds(args)
        result = explain_mod.explain(self.ds, str(args.get("error", "")), tenant, azure)
        if not result.matches and not result.unknown:
            raise ToolError("No AADSTS code or known error message found. fairfax decodes: " +
                            ", ".join(e.code for e in self.ds.errors))
        return render.explain_md(result, self.ds)

    # ------------------------------------------------------------ JSON-RPC
    def handle(self, msg):
        """One JSON-RPC message in, one response out (None for notifications)."""
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
            return _error(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid Request")
        method, params, mid = msg["method"], msg.get("params") or {}, msg.get("id")
        if "id" not in msg:
            return None  # notifications/initialized, cancellations and the like need no answer
        if method == "initialize":
            asked = params.get("protocolVersion")
            return _result(mid, {"protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                                 "capabilities": {"tools": {"listChanged": False}},
                                 "serverInfo": {"name": "fairfax", "title": "fairfax", "version": __version__},
                                 "instructions": INSTRUCTIONS})
        if method == "ping":
            return _result(mid, {})
        if method == "tools/list":
            return _result(mid, {"tools": TOOLS})
        if method == "tools/call":
            name, args = params.get("name"), params.get("arguments") or {}
            tool = {t["name"]: getattr(self, t["name"]) for t in TOOLS}.get(name)
            if tool is None:
                return _error(mid, -32602, f"Unknown tool: {name}")
            if not isinstance(args, dict):
                return _error(mid, -32602, "arguments must be an object")
            try:
                return _result(mid, {"content": [{"type": "text", "text": tool(args)}], "isError": False})
            except ToolError as e:
                return _result(mid, {"content": [{"type": "text", "text": str(e)}], "isError": True})
        return _error(mid, -32601, f"Method not found: {method}")


def _result(mid, result) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid, code, message) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def serve(stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    server = Server()
    for raw in stdin:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply = _error(None, -32700, "Parse error")
        else:
            if isinstance(msg, list):  # a batch (2025-03-26)
                reply = [r for r in (server.handle(m) for m in msg) if r is not None] or None
            else:
                reply = server.handle(msg)
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")
            stdout.flush()
    return 0
