"""After a clean `fairfax verify`, record that every cited page was re-confirmed today.

Runs verify against the live pages. For each page where every cited row and quote still matches,
it sets `checked` to today and `page_updated` to the page's own date. Pages that changed or
couldn't be fetched are left alone, so their old dates keep showing their real age.

Usage: python tools/mark_checked.py [--dry-run]
"""
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fairfax import dataset, verify  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "src" / "fairfax" / "data"


def main():
    dry = "--dry-run" in sys.argv
    today = dt.date.today().isoformat()
    results = verify.verify(dataset.load())
    ok = {r.source.key: r.page_updated or r.source.page_updated for r in results if r.state == "ok"}
    for r in results:
        if r.state != "ok":
            print(f"left alone: {r.source.key} ({r.state})")
    for path in sorted(DATA.glob("*.yaml")):
        lines, key, changed = path.read_text(encoding="utf-8").splitlines(), None, False
        in_sources = False
        for i, line in enumerate(lines):
            if re.match(r"^\S", line):
                in_sources = line.startswith("sources:")
                key = None
                continue
            m = re.match(r"^  ([a-z0-9-]+):\s*$", line)
            if in_sources and m:
                key = m.group(1)
                continue
            if in_sources and key in ok:
                for field, value in (("checked", today), ("page_updated", ok[key])):
                    if re.match(rf"^    {field}: ", line) and line != f"    {field}: {value}":
                        lines[i], changed = f"    {field}: {value}", True
        if changed:
            print(f"{'would update' if dry else 'updated'} {path.name}")
            if not dry:
                path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(ok)} of {len(results)} pages re-confirmed on {today}.")
    return 0 if len(ok) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
