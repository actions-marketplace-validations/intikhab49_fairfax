"""After a clean `fairfax verify`, record that every cited page was re-confirmed today.

Runs verify against the live pages. For each page where every cited row and quote still matches,
it sets `checked` to today and `page_updated` to the page's own date. Pages that changed or
couldn't be fetched are left alone, so their old dates keep showing their real age.

It also keeps a copy of each page on the Wayback Machine, so a citation outlives the page it
quotes. A page gets a new snapshot when it has none yet or Microsoft has updated it since the last
one. The snapshot is only recorded (as `archived`) once the same checks pass against it, so every
recorded copy is known to hold the rows it backs. Saving takes about a minute per page. A page whose
snapshot couldn't be saved keeps its old `page_updated`, so the next run tries again.

The weekly workflow (.github/workflows/watch.yml) runs this after a clean verify and opens a pull
request with the result; --summary writes that pull request's description.

Usage: python tools/mark_checked.py [--dry-run] [--no-archive] [--summary FILE]
"""
import argparse
import datetime as dt
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fairfax import dataset, learn, verify  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "src" / "fairfax" / "data"
FIELDS = ("checked", "page_updated", "archived")
GIVE_UP = 3  # failed snapshots in a row before the rest are skipped: each try can take minutes


def save_snapshot(url: str, tries: int = 3) -> str:
    """Ask the Wayback Machine to capture `url` now. Returns the snapshot's link."""
    req = urllib.request.Request("https://web.archive.org/save/" + url, headers={"User-Agent": learn.USER_AGENT})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                link = resp.geturl()
            if not dataset.ARCHIVED.match(link):
                raise ValueError(f"the Wayback Machine answered with {link}")
            return link
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 520, 523) or attempt == tries - 1:
                raise
            time.sleep(60 * (attempt + 1))
    raise AssertionError("unreachable")


def archive(results, dry: bool) -> tuple:
    """New snapshots for re-confirmed pages that need one: (key -> link, key -> why none was recorded)."""
    cited = verify.citations(dataset.load())
    links, failed, in_a_row = {}, {}, 0
    for r in results:
        s, page_now = r.source, r.page_updated or r.source.page_updated
        if r.state != "ok" or (s.archived and page_now <= s.page_updated):
            continue
        if dry:
            print(f"would archive {s.key}")
            continue
        if in_a_row >= GIVE_UP:
            why = f"skipped after {in_a_row} failed snapshots in a row"
        else:
            try:
                link = save_snapshot(s.url)
                check = verify.check_archived(replace(s, archived=link), cited.get(s.key, []))
                why = "" if check.state == "ok" else f"the snapshot is {check.state}: {check.error or 'rows missing'}"
            except Exception as e:  # one page the Wayback Machine won't take shouldn't stop the others
                why = f"{type(e).__name__}: {e}"
            in_a_row = in_a_row + 1 if why else 0
        if why:
            failed[s.key] = why
            print(f"not archived: {s.key} ({why})")
        else:
            links[s.key] = link
            print(f"archived {s.key}: {link}")
    return links, failed


def updates_for(results, today: str, links: dict, failed: dict) -> dict:
    """Source key -> fields to write, for every re-confirmed page."""
    out = {}
    for r in results:
        if r.state != "ok":
            continue
        key = r.source.key
        out[key] = {"checked": today}
        if key not in failed:  # keep the old date, so the next run tries the snapshot again
            out[key]["page_updated"] = r.page_updated or r.source.page_updated
        if key in links:
            out[key]["archived"] = f'"{links[key]}"'
    return out


def summary(results, links: dict, failed: dict, today: str) -> str:
    """Markdown for the weekly pull request: which pages Microsoft updated, their new snapshots, what was left alone."""
    def cell(text):
        return str(text).replace("|", "\\|").replace("\n", " ")

    ok = [r for r in results if r.state == "ok"]
    out = [f"{len(ok)} of {len(results)} cited pages still hold every cited row; their checked date moves to {today}."]
    moved = [r for r in ok if r.source.key in links or r.source.key in failed
             or (r.page_updated and r.page_updated != r.source.page_updated)]
    if moved:
        out += ["", "| Page | Microsoft updated it | Wayback Machine copy |", "|---|---|---|"]
        for r in moved:
            s = r.source
            when = (f"{s.page_updated} → {r.page_updated}" if r.page_updated and r.page_updated != s.page_updated
                    else "no new date")
            if s.key in links:
                copy = f"[new snapshot]({links[s.key]}), checked to hold the cited rows"
            elif s.key in failed:
                copy = f"not saved ({cell(failed[s.key])}); the old copy stays and the next run tries again"
            else:
                copy = "not saved (--no-archive or --dry-run)"
            out.append(f"| [{cell(s.title)}]({s.url}) | {when} | {copy} |")
    else:
        out += ["", "Microsoft hasn't updated any of them since the last check, so no new snapshots were needed."]
    left = [r for r in results if r.state != "ok"]
    if left:
        out += ["", "Left alone, so their dates keep showing their real age:", ""]
        for r in left:
            out.append(f"- [{r.source.title}]({r.source.url}): {r.state}" + (f" ({r.error})" if r.error else ""))
    return "\n".join(out) + "\n"


def apply(lines: list, updates: dict) -> tuple:
    """Set fields of source entries in one YAML file's lines. Missing fields are added at the end of the entry."""
    out, key, in_sources, todo, last, changed = [], None, False, {}, 0, False

    def close():
        nonlocal changed
        add = [f"    {field}: {todo.pop(field)}" for field in FIELDS if field in todo]
        out[last + 1:last + 1] = add
        changed |= bool(add)

    for line in lines:
        top = re.match(r"^\S", line)
        entry = re.match(r"^  ([a-z0-9-]+):\s*$", line) if in_sources else None
        if top or entry:
            close()
            key, todo = (entry.group(1), dict(updates.get(entry.group(1), {}))) if entry else (None, {})
            in_sources = line.startswith("sources:") if top else in_sources
        elif key and (m := re.match(r"^    ([a-z0-9_]+): ", line)):
            if m.group(1) in todo:
                new = f"    {m.group(1)}: {todo.pop(m.group(1))}"
                changed |= new != line
                line = new
            last = len(out)
        out.append(line)
    close()
    return out, changed


def main(argv=None):
    p = argparse.ArgumentParser(description="Record that every cited page was re-confirmed today.")
    p.add_argument("--dry-run", action="store_true", help="print what would change and write nothing")
    p.add_argument("--no-archive", action="store_true", help="move the dates only, save no snapshots")
    p.add_argument("--summary", metavar="FILE", help="also write a Markdown summary for the weekly pull request")
    args = p.parse_args(argv)
    today = dt.date.today().isoformat()
    results = verify.verify(dataset.load())
    for r in results:
        if r.state != "ok":
            print(f"left alone: {r.source.key} ({r.state})")
    links, failed = ({}, {}) if args.no_archive else archive(results, args.dry_run)
    updates = updates_for(results, today, links, failed)
    for path in sorted(DATA.glob("*.yaml")):
        lines, changed = apply(path.read_text(encoding="utf-8").splitlines(), updates)
        if changed:
            print(f"{'would update' if args.dry_run else 'updated'} {path.name}")
            if not args.dry_run:
                path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(updates)} of {len(results)} pages re-confirmed on {today}.")
    if args.summary:
        Path(args.summary).write_text(summary(results, links, failed, today), encoding="utf-8")
    return 0 if len(updates) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
