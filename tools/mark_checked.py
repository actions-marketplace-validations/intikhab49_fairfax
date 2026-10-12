"""After a clean `fairfax verify`, record that every cited page was re-confirmed today.

Runs verify against the live pages. For each page where every cited row and quote still matches,
it sets `checked` to today and `page_updated` to the page's own date. Pages that changed or
couldn't be fetched are left alone, so their old dates keep showing their real age.

It also keeps a copy of each page on the Wayback Machine, so a citation outlives the page it
quotes. A page gets a new snapshot when it has none yet or Microsoft has updated it since the last
one. The snapshot is only recorded (as `archived`) once the same checks pass against it, so every
recorded copy is known to hold the rows it backs. Saving takes about a minute per page.

Usage: python tools/mark_checked.py [--dry-run] [--no-archive]
"""
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


def archive(results, dry: bool) -> dict:
    """Source key -> new snapshot link, for re-confirmed pages that need one."""
    cited = verify.citations(dataset.load())
    out = {}
    for r in results:
        s, page_now = r.source, r.page_updated or r.source.page_updated
        if r.state != "ok" or (s.archived and page_now <= s.page_updated):
            continue
        if dry:
            print(f"would archive {s.key}")
            continue
        try:
            link = save_snapshot(s.url)
        except Exception as e:  # one page the Wayback Machine won't take shouldn't stop the others
            print(f"not archived: {s.key} ({type(e).__name__}: {e})")
            continue
        check = verify.check_archived(replace(s, archived=link), cited.get(s.key, []))
        if check.state == "ok":
            out[s.key] = link
            print(f"archived {s.key}: {link}")
        else:
            print(f"not archived: {s.key} (the snapshot is {check.state}: {check.error or 'rows missing'})")
    return out


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


def main():
    dry = "--dry-run" in sys.argv
    today = dt.date.today().isoformat()
    results = verify.verify(dataset.load())
    updates = {r.source.key: {"checked": today, "page_updated": r.page_updated or r.source.page_updated}
               for r in results if r.state == "ok"}
    for r in results:
        if r.state != "ok":
            print(f"left alone: {r.source.key} ({r.state})")
    if "--no-archive" not in sys.argv:
        for key, link in archive(results, dry).items():
            updates[key]["archived"] = f'"{link}"'
    for path in sorted(DATA.glob("*.yaml")):
        lines, changed = apply(path.read_text(encoding="utf-8").splitlines(), updates)
        if changed:
            print(f"{'would update' if dry else 'updated'} {path.name}")
            if not dry:
                path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(updates)} of {len(results)} pages re-confirmed on {today}.")
    return 0 if len(updates) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
