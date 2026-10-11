"""Text, Markdown and JSON output for check, scan and facts."""

from __future__ import annotations

import json
import textwrap
from dataclasses import asdict

from .check import CLOUD_LABEL, GROUP_ORDER, TENANT_LABEL, Report

HEADINGS = {"blocked": "Blocked", "cross-cloud": "Cross-cloud", "retiring": "Retiring", "note": "Notes", "ok": "OK"}


def _wrap(text: str, indent: int = 4, width: int = 100) -> str:
    pad = " " * indent
    return textwrap.fill(text, width=width, initial_indent=pad, subsequent_indent=pad,
                         break_long_words=False, break_on_hyphens=False)


def _context(tenant, azure) -> str:
    parts = [f"tenant {TENANT_LABEL[tenant]}" if tenant else "no tenant given"]
    parts.append(CLOUD_LABEL[azure] if azure else "no Azure cloud given")
    return ", ".join(parts)


def _summary(counts: dict) -> str:
    return ", ".join(f"{counts[g]} {g}" + ("s" if g == "note" and counts[g] != 1 else "") for g in GROUP_ORDER)


# ---------------------------------------------------------------- check
def check_text(r: Report) -> str:
    p = r.plan
    out = [f"govgap check: {p.name or p.path}",
           f"{_context(p.tenant, p.azure)} | {len(p.features)} features | {r.facts} facts, pages checked {r.checked}"]
    for group, items in r.groups().items():
        if not items:
            continue
        out += ["", f"{HEADINGS[group].upper()} ({len(items)})"]
        if group == "ok":
            for f in items:
                out.append(f"  {f.feature}  {f.verdict}")
                if f.note:
                    out.append(_wrap(f.note, 6))
            continue
        for f in items:
            flag = "" if f.confidence == "high" else f"[{f.confidence}] "
            out += ["", f"  {flag}{f.feature or f.title}"]
            out.append(_wrap(f.says))
            for extra in (f.elsewhere, f.note):
                if extra:
                    out.append(_wrap(extra))
            out.append(f"    source: {f.source_title}")
            out.append(f"            page updated {f.page_updated}, checked {f.checked}")
            out.append(f"            {f.url}")
            out.append(textwrap.fill(f"{f.cite_kind + ':':<8}{f.cite}", width=100, initial_indent="    ",
                                     subsequent_indent=" " * 12, break_long_words=False))
    out += ["", _summary(r.counts())]
    return "\n".join(out) + "\n"


def check_md(r: Report) -> str:
    p = r.plan
    tenant = TENANT_LABEL[p.tenant]
    azure = CLOUD_LABEL[p.azure] if p.azure else "not given"
    out = [f"# govgap check: {p.name or p.path}", "",
           "| Tenant | Azure | Features | Dataset |", "|---|---|---|---|",
           f"| {tenant} | {azure} | {len(p.features)} | {r.facts} facts, pages checked {r.checked} |", "",
           f"**{_summary(r.counts())}**"]
    for group, items in r.groups().items():
        if not items:
            continue
        out += ["", f"## {HEADINGS[group]} ({len(items)})", ""]
        if group == "ok":
            out += [f"- `{f.feature}`: {f.verdict}" + (f". {f.note}" if f.note else "") for f in items]
            continue
        for f in items:
            flag = "" if f.confidence == "high" else f" ({f.confidence})"
            head = f"`{f.feature}`" if f.feature else f.title
            body = " ".join(x for x in (f.says, f.elsewhere, f.note) if x)
            out += [f"### {head}{flag}", "", body, "",
                    f"Microsoft's {f.cite_kind}: `{f.cite}`", "",
                    f"Source: [{f.source_title}]({f.url}), page updated {f.page_updated}, checked {f.checked}", ""]
    return "\n".join(out).rstrip() + "\n"


def check_json(r: Report) -> str:
    return json.dumps({
        "plan": asdict(r.plan),
        "dataset": {"facts": r.facts, "checked": r.checked},
        "summary": r.counts(),
        "unknown": r.unknown,
        "findings": [asdict(f) for f in r.findings],
    }, indent=2, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------- scan
def _scan_summary(hits, files) -> str:
    wrong = sum(h.kind == "wrong" for h in hits)
    check = len(hits) - wrong
    touched = len({h.path for h in hits})
    return (f"{wrong} wrong-cloud endpoint{'s' if wrong != 1 else ''} and {check} to check "
            f"in {touched} of {files} files scanned.")


def scan_text(hits, files, tenant, azure) -> str:
    out = [f"govgap scan: {_context(tenant, azure)}"]
    current = None
    for h in hits:
        if h.path != current:
            current = h.path
            out += ["", h.path]
        tag = "" if h.kind == "wrong" else "CHECK  "
        out.append(f"  {h.line}:{h.col}  {tag}{h.found}  ->  {' or '.join(h.expected)}")
        out.append(_wrap(h.why, 6))
        out.append(f"      {h.url}")
    out += ["", _scan_summary(hits, files)]
    return "\n".join(out) + "\n"


def scan_md(hits, files, tenant, azure) -> str:
    out = [f"# govgap scan: {_context(tenant, azure)}", "", _scan_summary(hits, files)]
    if hits:
        out += ["", "| Where | Found | Use | Why |", "|---|---|---|---|"]
        for h in hits:
            use = " or ".join(f"`{x}`" for x in h.expected)
            kind = "" if h.kind == "wrong" else "**check:** "
            out.append(f"| `{h.path}:{h.line}` | `{h.found}` | {use} | {kind}{h.why} [source]({h.url}) |")
    return "\n".join(out) + "\n"


def scan_json(hits, files, tenant, azure) -> str:
    return json.dumps({"tenant": tenant, "azure": azure, "files": files,
                       "hits": [asdict(h) for h in hits]}, indent=2, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------- facts
def status_summary(fact) -> str:
    items = [(k, v) for k, v in fact.status.items() if v != "not-possible"]
    text = ", ".join(f"{k.replace('+', '/')} {v}" for k, v in items)
    if len(items) < len(fact.status):
        text += " (other pairings not possible)"
    return text


def facts_text(facts, ds) -> str:
    width = max((len(f.feature) for f in facts), default=10)
    out = [f"{f.feature:<{width}}  {status_summary(f)}" + ("" if f.confidence == "high" else f"  [{f.confidence}]")
           for f in facts]
    out += ["", f"{len(facts)} of {len(ds.facts)} features shown. {len(ds.rules)} stack rules and "
                f"{len(ds.endpoints)} endpoint mappings also loaded. Pages checked {ds.checked}."]
    return "\n".join(out) + "\n"


def facts_json(facts) -> str:
    return json.dumps([{"feature": f.feature, "name": f.name, "by": f.by, "status": f.status, "url": f.url,
                        "row": f.row, "checked": f.source.checked, "confidence": f.confidence} for f in facts],
                      indent=2, ensure_ascii=False) + "\n"


def stale_text(stale, days) -> str:
    if not stale:
        return f"Every cited page was checked within the last {days} days.\n"
    out = [f"{len(stale)} cited page{'s' if len(stale) != 1 else ''} last checked more than {days} days ago:"]
    for s, n in stale:
        out += ["", f"  {s.title}", f"    {s.url}", f"    checked {s.checked}, cited by {n} entries"]
    return "\n".join(out) + "\n"
