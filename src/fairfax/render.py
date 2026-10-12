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
    out = [f"fairfax check: {p.name or p.path}",
           f"{_context(p.tenant, p.azure)} | {len(p.features)} features | dataset of {r.features} features, "
           f"pages checked {r.checked}"]
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
            for item in f.roadmap:
                out.append(_wrap(item["says"]))
                out.append(f"    {item['url']}")
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
    out = [f"# fairfax check: {p.name or p.path}", "",
           "| Tenant | Azure | Features | Dataset |", "|---|---|---|---|",
           f"| {tenant} | {azure} | {len(p.features)} | {r.features} features, pages checked {r.checked} |", "",
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
            out += [f"### {head}{flag}", "", body, ""]
            out += [f"Roadmap: [{item['id']}]({item['url']}): {item['says'].split(': ', 1)[1]}" for item in f.roadmap]
            out += ([""] if f.roadmap else []) + [
                    f"Microsoft's {f.cite_kind}: `{f.cite}`", "",
                    f"Source: [{f.source_title}]({f.url}), page updated {f.page_updated}, checked {f.checked}"
                    + (f" ([archived copy]({f.archived}))" if f.archived else ""), ""]
    return "\n".join(out).rstrip() + "\n"


def check_json(r: Report) -> str:
    return json.dumps({
        "plan": asdict(r.plan),
        "dataset": {"facts": r.facts, "features": r.features, "checked": r.checked},
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
    out = [f"fairfax scan: {_context(tenant, azure)}"]
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
    out = [f"# fairfax scan: {_context(tenant, azure)}", "", _scan_summary(hits, files)]
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
def status_summary(fact, status: dict | None = None) -> str:
    status = status or fact.status
    items = [(k, v) for k, v in status.items() if v != "not-possible"]
    text = ", ".join(f"{k.replace('+', '/')} {v}" for k, v in items)
    if len(items) < len(status):
        text += " (other pairings not possible)"
    return text


def by_feature(facts) -> dict:
    """Feature key -> (its facts, statuses merged across them). Some features cite one page per cloud."""
    out: dict[str, list] = {}
    for f in facts:
        out.setdefault(f.feature, []).append(f)
    order = {"gcc": 0, "gcchigh": 1, "dod": 2}
    return {k: (v, dict(sorted(((sk, sv) for f in v for sk, sv in f.status.items()),
                               key=lambda kv: order.get(kv[0], 9)))) for k, v in out.items()}


def facts_text(facts, ds) -> str:
    grouped = by_feature(facts)
    width = max((len(k) for k in grouped), default=10)
    out = []
    for key, (items, status) in grouped.items():
        worst = next((f.confidence for f in items if f.confidence != "high"), None)
        out.append(f"{key:<{width}}  {status_summary(items[0], status)}" + (f"  [{worst}]" if worst else ""))
    out += ["", f"{len(grouped)} of {len(ds.features())} features shown. {len(ds.rules)} stack rules, "
                f"{len(ds.endpoints)} endpoint mappings and {len(ds.errors)} sign-in errors also loaded. "
                f"Pages checked {ds.checked}."]
    return "\n".join(out) + "\n"


def facts_json(facts) -> str:
    return json.dumps([{"feature": f.feature, "name": f.name, "by": f.by, "status": f.status, "url": f.url,
                        "row": f.row, "checked": f.source.checked, "archived": f.source.archived,
                        "confidence": f.confidence} for f in facts],
                      indent=2, ensure_ascii=False) + "\n"


def stale_text(stale, days) -> str:
    if not stale:
        return f"Every cited page was checked within the last {days} days.\n"
    out = [f"{len(stale)} cited page{'s' if len(stale) != 1 else ''} last checked more than {days} days ago:"]
    for s, n in stale:
        out += ["", f"  {s.title}", f"    {s.url}", f"    checked {s.checked}, cited by {n} entries"]
        out += [f"    archived copy: {s.archived}"] if s.archived else []
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- explain
def _hosts_lines(x) -> list:
    width = max((len(h) for h, _ in x.hosts), default=0)
    return [f"    {h:<{width}}  for {who}" for h, who in x.hosts]


def explain_text(result, ds) -> str:
    out = []
    for x in result.matches:
        e = x.error
        flag = "" if e.confidence == "high" else f"[{e.confidence}] "
        out += ["", f"{flag}{e.code}  {e.name}", _wrap(e.says), "", "  Fix", _wrap(e.fix)]
        out += _hosts_lines(x)
        out += ["", f"    source: {e.source.title}", f"            page updated {e.source.page_updated}, "
                f"checked {e.source.checked}", f"            {e.url}",
                textwrap.fill(f"{'quote:':<8}{e.row}", width=100, initial_indent="    ", subsequent_indent=" " * 12,
                              break_long_words=False)]
        for q in e.also:
            out.append(textwrap.fill(f"{'also:':<8}{q.quote}", width=100, initial_indent="    ",
                                     subsequent_indent=" " * 12, break_long_words=False))
            if q.url != e.url:
                out.append(f"            {q.url}")
    for code in result.unknown:
        out += ["", f"{code}: fairfax doesn't decode this one. It covers {len(ds.errors)} errors that cross-cloud "
                    "setups cause (`fairfax explain --list`).",
                _wrap(f"Microsoft's full list: {_errors_page(ds)}")]
    return "\n".join(out).lstrip("\n") + "\n"


def _errors_page(ds) -> str:
    src = ds.sources.get("entra-errors")
    return src.url if src else "https://learn.microsoft.com/en-us/entra/identity-platform/reference-error-codes"


def explain_md(result, ds) -> str:
    out = []
    for x in result.matches:
        e = x.error
        flag = "" if e.confidence == "high" else f" ({e.confidence})"
        out += [f"## {e.code} {e.name}{flag}", "", e.says, "", f"**Fix:** {e.fix}", ""]
        out += [f"- `{h}` for {who}" for h, who in x.hosts] + ([""] if x.hosts else [])
        out += [f"Microsoft: `{e.row}`", "", f"Source: [{e.source.title}]({e.url}), page updated "
                f"{e.source.page_updated}, checked {e.source.checked}"
                + (f" ([archived copy]({e.source.archived}))" if e.source.archived else ""), ""]
        out += [f"- [{q.source.title}]({q.url}): `{q.quote}`" for q in e.also] + ([""] if e.also else [])
    for code in result.unknown:
        out += [f"**{code}:** fairfax doesn't decode this one. Microsoft's full list: {_errors_page(ds)}", ""]
    return "\n".join(out).rstrip() + "\n"


def explain_json(result, ds) -> str:
    def one(x):
        e = x.error
        return {"code": e.code, "name": e.name, "says": e.says, "fix": e.fix, "confidence": e.confidence,
                "hosts": [{"host": h, "for": who} for h, who in x.hosts],
                "source": {"title": e.source.title, "url": e.url, "page_updated": e.source.page_updated,
                           "checked": e.source.checked, "archived": e.source.archived},
                "row": e.row, "also": [{"quote": q.quote, "url": q.url, "title": q.source.title} for q in e.also]}
    return json.dumps({"matches": [one(x) for x in result.matches], "unknown": result.unknown},
                      indent=2, ensure_ascii=False) + "\n"


def errors_list(ds) -> str:
    width = max(len(e.code) for e in ds.errors)
    out = [f"{e.code:<{width}}  {e.name}" + ("" if e.confidence == "high" else f"  [{e.confidence}]")
           for e in sorted(ds.errors, key=lambda e: int(e.code[6:]))]
    return "\n".join(out) + f"\n\n{len(ds.errors)} sign-in errors that cross-cloud setups cause.\n"


# ---------------------------------------------------------------- verify
STATE_LABEL = {"ok": "ok", "changed": "CHANGED", "gone": "GONE", "unreachable": "UNREACHABLE"}


def _verify_summary(results) -> str:
    changed = [r for r in results if r.state == "changed"]
    lost = sum(len(r.missing) for r in changed)
    gone = sum(r.state == "gone" for r in results)
    down = sum(r.state == "unreachable" for r in results)
    ok = sum(r.state == "ok" for r in results)
    parts = [f"{ok} of {len(results)} page{'s match' if len(results) != 1 else ' matches'}"]
    if changed:
        parts.append(f"{len(changed)} changed ({lost} cited item{'s' if lost != 1 else ''} no longer found)")
    if gone:
        parts.append(f"{gone} gone")
    if down:
        parts.append(f"{down} couldn't be fetched")
    return "; ".join(parts) + "."


def verify_text(results) -> str:
    total = sum(len(r.citations) for r in results)
    pages = f"{len(results)} Microsoft page" + ("s" if len(results) != 1 else "")
    out = [f"fairfax verify: {pages}, {total} cited rows and quotes", ""]
    width = max((len(r.source.title) for r in results), default=10)
    for r in results:
        n = len(r.citations)
        line = f"{STATE_LABEL[r.state]:<12}{r.source.title:<{width}}  {n - len(r.missing)} of {n}"
        if r.page_updated and r.page_updated != r.source.page_updated:
            line += f"  (page updated {r.page_updated}, fairfax has {r.source.page_updated})"
        out.append(line)
        if r.state in ("gone", "unreachable"):
            out.append(f"{'':12}{r.error}")
            continue
        for c in r.missing:
            out.append(f"{'':12}{c.id}  #{c.anchor}" if c.anchor else f"{'':12}{c.id}")
            out.append(textwrap.fill(f"{'cited:':<9}{c.text}", width=110, initial_indent=" " * 14,
                                     subsequent_indent=" " * 23, break_long_words=False))
            if c.nearest:
                out.append(textwrap.fill(f"{'closest:':<9}{c.nearest}", width=110, initial_indent=" " * 14,
                                         subsequent_indent=" " * 23, break_long_words=False))
        if r.state == "changed" and r.error:
            out.append(f"{'':12}{r.error}")
    out += ["", _verify_summary(results)]
    return "\n".join(out) + "\n"


def verify_md(results) -> str:
    out = ["# fairfax verify", "", _verify_summary(results), "", "| Page | Result | Cited items found |", "|---|---|---|"]
    for r in results:
        n = len(r.citations)
        out.append(f"| [{r.source.title}]({r.source.url}) | {STATE_LABEL[r.state]} | {n - len(r.missing)} of {n} |")
    for r in results:
        if r.state == "ok":
            continue
        out += ["", f"## {r.source.title}", "", r.error] if r.state in ("gone", "unreachable") else ["", f"## {r.source.title}", ""]
        if r.state == "gone":
            continue
        for c in r.missing:
            out += [f"- `{c.id}` under `#{c.anchor}`", f"  - cited: `{c.text}`"]
            if c.nearest:
                out.append(f"  - closest on the page now: `{c.nearest}`")
    return "\n".join(out).rstrip() + "\n"


def verify_json(results) -> str:
    return json.dumps([{"source": r.source.key, "title": r.source.title, "url": r.source.url,
                        "archived": r.source.archived, "state": r.state,
                        "page_updated": r.page_updated, "fairfax_page_updated": r.source.page_updated,
                        "cited": len(r.citations), "error": r.error,
                        "missing": [{"id": c.id, "anchor": c.anchor, "text": c.text, "nearest": c.nearest}
                                    for c in r.missing]} for r in results], indent=2, ensure_ascii=False) + "\n"
