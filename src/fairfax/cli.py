"""fairfax: check a Microsoft gov-cloud plan against Microsoft's own availability tables."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from . import __version__
from . import check as check_mod
from . import dataset as dataset_mod
from . import explain as explain_mod
from . import render
from . import sarif
from . import scan as scan_mod
from . import verify as verify_mod
from .dataset import CLOUDS, TENANTS


def _today(value: str | None) -> dt.date:
    return dt.date.fromisoformat(value) if value else dt.date.today()


def _emit(text: str, output: str | None) -> None:
    if output:
        with open(output, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)


def cmd_check(a) -> int:
    ds = dataset_mod.load()
    try:
        plan = check_mod.load_plan(a.plan)
    except check_mod.PlanError as e:
        print(f"fairfax: {e}", file=sys.stderr)
        return 2
    report = check_mod.check(ds, plan, _today(a.today))
    if report.unknown:
        for key, close in report.unknown.items():
            hint = f" Did you mean {', '.join(close)}?" if close else ""
            print(f"fairfax: unknown feature {key!r}.{hint}", file=sys.stderr)
        print("fairfax: list feature keys with `fairfax facts --grep <word>`.", file=sys.stderr)
        return 2
    fmt = {"text": render.check_text, "md": render.check_md, "json": render.check_json,
           "sarif": sarif.check_sarif}[a.format]
    _emit(fmt(report), a.output)
    return 1 if report.failed(a.strict) else 0


def cmd_scan(a) -> int:
    tenant, azure, rules, base = a.tenant, a.azure, [], None
    if a.plan:
        try:
            plan = check_mod.load_plan(a.plan)
        except check_mod.PlanError as e:
            print(f"fairfax: {e}", file=sys.stderr)
            return 2
        # --tenant/--azure replace the plan's own clouds; its `paths:` entries still apply on top
        tenant, azure = tenant or plan.tenant, azure or plan.azure
        rules, base = plan.paths, Path(a.plan).parent
    if not tenant and not azure:
        print("fairfax: say which clouds you target: --plan plan.yaml, or --tenant and/or --azure.", file=sys.stderr)
        return 2
    hits, files = scan_mod.scan(a.paths, dataset_mod.load(), tenant, azure, a.exclude or [], rules, base)
    fmt = {"text": render.scan_text, "md": render.scan_md, "json": render.scan_json, "sarif": sarif.scan_sarif}[a.format]
    _emit(fmt(hits, files, tenant, azure, rules), a.output)
    bad = {"wrong", "check"} if a.strict else {"wrong"}
    return 1 if any(h.kind in bad for h in hits) else 0


def _clouds(a) -> tuple:
    """Tenant and Azure cloud from --tenant/--azure, falling back to --plan."""
    tenant, azure = a.tenant, a.azure
    if a.plan:
        plan = check_mod.load_plan(a.plan)
        tenant, azure = tenant or plan.tenant, azure or plan.azure
    return tenant, azure


def cmd_explain(a) -> int:
    ds = dataset_mod.load()
    if a.list:
        sys.stdout.write(render.errors_list(ds))
        return 0
    text = " ".join(a.error)
    if not text.strip():
        print("fairfax: give an error code such as AADSTS900439, or paste the error message.", file=sys.stderr)
        return 2
    try:
        tenant, azure = _clouds(a)
    except check_mod.PlanError as e:
        print(f"fairfax: {e}", file=sys.stderr)
        return 2
    result = explain_mod.explain(ds, text, tenant, azure)
    if not result.matches and not result.unknown:
        print("fairfax: no AADSTS code or known error message found. Codes fairfax decodes: "
              "`fairfax explain --list`.", file=sys.stderr)
        return 2
    fmt = {"text": render.explain_text, "md": render.explain_md, "json": render.explain_json}[a.format]
    _emit(fmt(result, ds), a.output)
    return 0 if result.matches else 2


def cmd_verify(a) -> int:
    ds = dataset_mod.load()
    unknown = [k for k in a.source or [] if k not in ds.sources]
    if unknown:
        print(f"fairfax: unknown source {', '.join(unknown)}. Sources: {', '.join(sorted(ds.sources))}", file=sys.stderr)
        return 2
    results = verify_mod.verify(ds, a.source, archived=a.archived)
    fmt = {"text": render.verify_text, "md": render.verify_md, "json": render.verify_json}[a.format]
    _emit(fmt(results), a.output)
    return verify_mod.exit_code(results)


def cmd_mcp(a) -> int:
    from . import mcp
    return mcp.serve()


def cmd_facts(a) -> int:
    ds = dataset_mod.load()
    if a.stale is not None:
        cutoff = _today(a.today) - dt.timedelta(days=a.stale)
        cited: dict[str, int] = {}
        for item in [*ds.facts, *ds.rules, *ds.endpoints]:
            cited[item.source.key] = cited.get(item.source.key, 0) + 1
        stale = [(s, cited.get(k, 0)) for k, s in sorted(ds.sources.items())
                 if dt.date.fromisoformat(s.checked) < cutoff]
        sys.stdout.write(render.stale_text(stale, a.stale))
        return 1 if stale else 0
    facts = ds.facts
    if a.grep:
        needle = a.grep.lower()
        facts = [f for f in facts if needle in f.feature or needle in f.name.lower()]
    sys.stdout.write(render.facts_json(facts) if a.format == "json" else render.facts_text(facts, ds))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fairfax",
        description="Check a Microsoft gov-cloud plan (GCC, GCC High, DoD, Azure Government) against "
                    "Microsoft's own availability tables. Every finding cites the row it came from.")
    p.add_argument("--version", action="version", version=f"fairfax {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="check a plan file and report what is blocked, cross-cloud or retiring")
    c.add_argument("plan", help="plan YAML: tenant, azure and a list of feature keys")
    c.add_argument("--format", choices=["text", "md", "json", "sarif"], default="text")
    c.add_argument("-o", "--output", help="write the report to this file instead of stdout")
    c.add_argument("--strict", action="store_true", help="also exit 1 on cross-cloud and retiring findings")
    c.add_argument("--today", help=argparse.SUPPRESS)
    c.set_defaults(func=cmd_check)

    s = sub.add_parser("scan", help="find Microsoft endpoints in code that belong to the wrong cloud")
    s.add_argument("paths", nargs="+", help="files or folders to scan")
    s.add_argument("--plan", help="read tenant and azure from a plan file, with any per-path overrides under paths:")
    s.add_argument("--tenant", choices=TENANTS)
    s.add_argument("--azure", choices=CLOUDS)
    s.add_argument("--exclude", action="append", metavar="GLOB", help="skip paths matching this glob (repeatable)")
    s.add_argument("--format", choices=["text", "md", "json", "sarif"], default="text")
    s.add_argument("-o", "--output", help="write the report to this file instead of stdout")
    s.add_argument("--strict", action="store_true", help="also exit 1 on endpoints marked CHECK")
    s.set_defaults(func=cmd_scan)

    f = sub.add_parser("facts", help="list feature keys and their status, or find stale sources")
    f.add_argument("--grep", help="only show features whose key or name contains this text")
    f.add_argument("--stale", type=int, metavar="DAYS", help="list cited pages last checked more than DAYS ago")
    f.add_argument("--format", choices=["text", "json"], default="text")
    f.add_argument("--today", help=argparse.SUPPRESS)
    f.set_defaults(func=cmd_facts)

    e = sub.add_parser("explain", help="decode a cross-cloud sign-in error such as AADSTS900439")
    e.add_argument("error", nargs="*", help="an error code, or the whole error message")
    e.add_argument("--plan", help="read tenant and azure from a plan file, to name the right sign-in host")
    e.add_argument("--tenant", choices=TENANTS)
    e.add_argument("--azure", choices=CLOUDS)
    e.add_argument("--list", action="store_true", help="list the errors fairfax decodes")
    e.add_argument("--format", choices=["text", "md", "json"], default="text")
    e.add_argument("-o", "--output", help="write the result to this file instead of stdout")
    e.set_defaults(func=cmd_explain)

    v = sub.add_parser("verify", help="re-read Microsoft's pages and confirm every cited row is still there")
    v.add_argument("--source", action="append", metavar="KEY", help="only check this source (repeatable)")
    v.add_argument("--archived", action="store_true",
                   help="check the Wayback Machine copies the dataset records instead of the live pages")
    v.add_argument("--format", choices=["text", "md", "json"], default="text")
    v.add_argument("-o", "--output", help="write the report to this file instead of stdout")
    v.set_defaults(func=cmd_verify)

    m = sub.add_parser("mcp", help="run an MCP server on stdio so coding agents can ask fairfax")
    m.set_defaults(func=cmd_mcp)
    return p


def main(argv: list | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except dataset_mod.DatasetError as e:
        print(f"fairfax: dataset error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
