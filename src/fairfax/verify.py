"""Re-read every Microsoft page the dataset cites and confirm each cited row and quote is still there.

fairfax is only as good as its citations, so this is the check that keeps them honest. It fetches
the live pages, so it is the one command that needs a network connection.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import learn
from .dataset import Dataset, Source


@dataclass
class Citation:
    kind: str  # "row", "summary" or "quote"
    id: str
    anchor: str
    text: str
    found: bool = False
    nearest: str | None = None


@dataclass
class PageResult:
    source: Source
    state: str  # "ok", "changed", "gone" (404/410, or no archived copy) or "unreachable" (may be temporary)
    citations: list = field(default_factory=list)
    page_updated: str = ""
    error: str = ""

    @property
    def missing(self) -> list:
        return [c for c in self.citations if not c.found]


def citations(ds: Dataset) -> dict:
    """Source key -> every row and quote the dataset cites from that page."""
    out: dict[str, list] = {}

    def add(source, kind, item_id, anchor, text):
        out.setdefault(source.key, []).append(Citation(kind, item_id, anchor, text))

    for f in ds.facts:
        add(f.source, f.cite, f.id, f.anchor, f.row)
        if f.retires:
            add(f.retires_source, "quote", f.id + ".retires", "", f.retires_quote)
    for r in ds.rules:
        add(r.source, "quote", r.id, r.anchor, r.quote)
    for e in ds.endpoints:
        add(e.source, "row", e.id, e.anchor, e.row)
        for q in e.also:
            add(q.source, "quote", e.id, q.anchor, q.quote)
    for e in ds.errors:
        add(e.source, "row", e.id, e.anchor, e.row)
        for q in e.also:
            add(q.source, "quote", e.id, q.anchor, q.quote)
    for r in ds.roadmap:
        add(r.source, "roadmap", f"roadmap.{r.id}", "", roadmap_text(r.id, r.title, r.status, r.clouds, r.ga))
    return out


def roadmap_text(rid, title, status, clouds, ga) -> str:
    return f"{rid} | {title.strip()} | {status} | {', '.join(clouds)} | {ga}"


def _check_roadmap(body: bytes, cites: list) -> str:
    """Compare linked roadmap items with Microsoft's live API. Returns the newest modified date."""
    items = {i["id"]: i for i in json.loads(body)["value"]}
    newest = ""
    for c in cites:
        now = items.get(int(c.id.split(".", 1)[1]))
        if now is None:
            c.found, c.nearest = False, "no longer on the roadmap"
            continue
        clouds = [x for x in now["cloudInstances"] if x in ("GCC", "GCC High", "DoD")]
        text = roadmap_text(now["id"], now["title"], now["status"], clouds, now["generalAvailabilityDate"])
        c.found = text == c.text
        c.nearest = None if c.found else text
        newest = max(newest, now["modified"][:10])
    return newest


# ---------------------------------------------------------------- summaries
# A few rows sum up a table instead of copying one row, because Microsoft lays the table out the
# other way round (models as columns) or because the finding is that a table has no US Gov row.
# Each source with summaries gets the function that re-derives them from the live page.
AOAI_TABLES = (
    ("data-zone-standard-model-availability", "Data Zone Standard"),
    ("data-zone-provisioned-managed-model-availability", "Data Zone Provisioned"),
    ("standard-deployment-model-availability", "Standard"),
    ("provisioned-deployment-model-availability", "Provisioned"),
)


def _aoai_summary(page: learn.Page, c: Citation) -> bool:
    model = c.text.split(": ", 1)[0]
    parts = []
    for section, label in AOAI_TABLES:
        rows = page.section_rows(section)
        if not rows:
            continue
        models = [h.split(",")[0].strip() for h in rows[0][1:]]
        regions = sorted(r[0] for r in rows[1:] if model in models and models.index(model) + 1 < len(r)
                         and "✅" in r[models.index(model) + 1])
        if regions:
            parts.append(f"{label} ({' and '.join(regions)})")
    return c.text == f"{model}: " + "; ".join(parts)


def _no_gov_region(page: learn.Page, c: Citation) -> bool:
    rows = page.section_rows(c.anchor)
    return len(rows) > 5 and not any(r and r[0].lower().startswith("usgov") for r in rows)


SUMMARIES = {"aoai-gov": _aoai_summary, "lang-regions": _no_gov_region}


# ---------------------------------------------------------------- checking
PDF_CHANGED = ("the file differs from the copy the dataset was built from: Microsoft published a new version. "
               "Compare its table with the rows that cite it, update them, then set sha256 to the new file's hash")


def check_page(source: Source, cites: list, fetch=None, url: str | None = None) -> PageResult:
    try:
        body = (fetch or learn.fetch)(url or source.url)
    except urllib.error.HTTPError as e:
        if e.code not in (404, 410):
            return PageResult(source, "unreachable", cites, error=f"HTTP {e.code} {e.reason}")
        kept = f"; archived copy: {source.archived}" if source.archived and not url else ""
        return PageResult(source, "gone", cites, error=f"HTTP {e.code}: the page is no longer there{kept}")
    except Exception as e:  # reported, not raised: one unreachable page shouldn't stop the run
        return PageResult(source, "unreachable", cites, error=f"{type(e).__name__}: {e}")
    if cites and all(c.kind == "roadmap" for c in cites):
        try:
            newest = _check_roadmap(body, cites)
        except (ValueError, KeyError, TypeError) as e:
            return PageResult(source, "unreachable", cites, error=f"the roadmap API answered in an unexpected shape: {e}")
        return PageResult(source, "ok" if all(c.found for c in cites) else "changed", cites, newest)
    if source.sha256:
        same = hashlib.sha256(body).hexdigest() == source.sha256
        for c in cites:
            c.found = same
        return PageResult(source, "ok" if same else "changed", cites, error="" if same else PDF_CHANGED)
    page = learn.parse(body.decode("utf-8", errors="replace"), source.url)
    for c in cites:
        if c.kind == "summary":
            c.found = SUMMARIES[source.key](page, c) if source.key in SUMMARIES else False
        elif c.anchor:
            c.found = page.find(c.anchor, c.text)
        else:
            c.found = any(c.text in t for _, t in page.text)
        if not c.found and c.kind != "summary":
            c.nearest = page.nearest(c.anchor, c.text)
    return PageResult(source, "ok" if all(c.found for c in cites) else "changed", cites, page.updated)


def check_archived(source: Source, cites: list, fetch=None) -> PageResult:
    """The same checks, run against the source's Wayback Machine snapshot instead of the live page."""
    if not source.archived_raw:
        return PageResult(source, "gone", cites, error="no archived copy recorded (tools/mark_checked.py saves one)")
    return check_page(source, cites, fetch, url=source.archived_raw)


def verify(ds: Dataset, keys: list | None = None, fetch=None, workers: int | None = None, archived: bool = False) -> list:
    """Check every cited page. The Wayback Machine refuses parallel downloads, so snapshots are read one at a time."""
    workers = workers or (1 if archived else 4)
    cited = citations(ds)
    todo = [(ds.sources[k], cited.get(k, [])) for k in sorted(ds.sources) if not keys or k in keys]
    one = check_archived if archived else check_page
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda t: one(t[0], t[1], fetch), todo))


def exit_code(results: list) -> int:
    """1 when a cited row changed or its page is gone for good, 2 when a page couldn't be fetched this time."""
    if any(r.state in ("changed", "gone") for r in results):
        return 1
    if any(r.state == "unreachable" for r in results):
        return 2
    return 0
