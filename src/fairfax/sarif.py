"""SARIF 2.1.0 output, so GitHub code scanning shows fairfax findings on the lines they're about.

`scan` results point at the line with the wrong-cloud host. `check` results point at the line in
the plan file that names the feature (or at tenant/azure for stack-level rules).
"""

from __future__ import annotations

import json
from pathlib import Path

from . import __version__

SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
INFO = "https://intikhab49.github.io/fairfax/"
LEVEL = {"blocked": "error", "cross-cloud": "warning", "retiring": "warning", "note": "note",
         "wrong": "error", "check": "warning"}


def _uri(path: str) -> str:
    p = Path(path)
    if p.is_absolute():
        try:
            p = p.relative_to(Path.cwd())
        except ValueError:
            return p.as_uri()
    return p.as_posix()


def _log(rules: dict, results: list) -> str:
    run = {"tool": {"driver": {"name": "fairfax", "version": __version__, "informationUri": INFO,
                               "rules": list(rules.values())}},
           "results": results}
    return json.dumps({"$schema": SCHEMA, "version": "2.1.0", "runs": [run]}, indent=2, ensure_ascii=False) + "\n"


def _location(path: str, line: int, col: int = 1, end_col: int | None = None) -> dict:
    region = {"startLine": line, "startColumn": col}
    if end_col:
        region["endColumn"] = end_col
    return {"physicalLocation": {"artifactLocation": {"uri": _uri(path), "uriBaseId": "%SRCROOT%"}, "region": region}}


def scan_sarif(hits, files, tenant, azure) -> str:
    rules, results = {}, []
    for h in hits:
        rules.setdefault(h.id, {
            "id": h.id, "name": h.service,
            "shortDescription": {"text": f"{h.service}: host for the wrong Microsoft cloud"},
            "helpUri": h.url, "properties": {"tags": ["fairfax", "gov-cloud"]}})
        verb = "belongs to the wrong cloud" if h.kind == "wrong" else "may be right or wrong for this line"
        results.append({
            "ruleId": h.id, "level": LEVEL[h.kind],
            "message": {"text": f"{h.found} {verb}: use {' or '.join(h.expected)}. {h.why}"},
            "locations": [_location(h.path, h.line, h.col, h.col + len(h.found))]})
    return _log(rules, results)


def _plan_line(lines: list, needle: str, default: int = 1) -> int:
    for n, text in enumerate(lines, 1):
        stripped = text.split("#", 1)[0]
        if needle in stripped:
            return n
    return default


def check_sarif(report) -> str:
    path = report.plan.path or "plan.yaml"
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    rules, results = {}, []
    for f in report.findings:
        if f.group == "ok":
            continue
        rule_id = f.feature or f.id
        rules.setdefault(rule_id, {
            "id": rule_id, "name": f.title, "shortDescription": {"text": f.title}, "helpUri": f.url,
            "properties": {"tags": ["fairfax", "gov-cloud", f.group]}})
        line = (_plan_line(lines, f.feature) if f.feature
                else _plan_line(lines, "azure:", _plan_line(lines, "tenant:")))
        text = " ".join(x for x in (f.says, f.elsewhere) if x)
        text += f" Microsoft's {f.cite_kind}: {f.cite}"
        results.append({"ruleId": rule_id, "level": LEVEL[f.group], "message": {"text": text},
                        "locations": [_location(path, line)]})
    return _log(rules, results)

