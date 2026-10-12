"""Read a Microsoft Learn page the way fairfax cites it: section anchors, table rows and text blocks.

The same reader builds the dataset and checks it against the live pages, so a row fairfax cites is
compared with what Microsoft's page says today, cell for cell.
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser

from . import __version__

KEEP_META = {"ms.date", "updated_at", "title"}
ICON = re.compile(r"([A-Za-z0-9_-]+)\.(?:svg|png|gif)$")
USER_AGENT = f"fairfax/{__version__} (+https://github.com/intikhab49/fairfax)"


def cells(c) -> str:
    """One table row as fairfax stores it: cells joined by ' | ', outer blanks and bars trimmed."""
    return " | ".join(c).strip(" |")


@dataclass
class Page:
    url: str
    meta: dict = field(default_factory=dict)
    title: str = ""
    rows: list = field(default_factory=list)  # (section, [cell, ...])
    text: list = field(default_factory=list)  # (section, text of a paragraph or list item)

    @property
    def updated(self) -> str:
        return self.meta.get("updated_at", "")[:10]

    def section_rows(self, section: str) -> list:
        return [c for s, c in self.rows if s == section]

    def find(self, section: str, cited: str) -> bool:
        """Is a cited row still on the page, under the same section?

        A citation is Microsoft's text in pieces joined by ' ; '. Each piece is a table row, a run of
        a row's cells, or part of a paragraph, list item or long cell. 'Label: a ; b' means rows a and
        b sit in the group that the row starting with Label opens: the rest of that row, then the rows
        below it that are nested under it (an empty first cell, or one that starts with '- ').
        """
        label, sep, rest = cited.partition(": ")
        if sep:
            rows = self.section_rows(section)
            heads = [i for i, c in enumerate(rows) if c and c[0] in (label, "- " + label)]
            if heads:
                return any(_in_order(rest.split(" ; "), _group(rows, i)) for i in heads)
        return all(self._piece(section, p) for p in cited.split(" ; "))

    def _piece(self, section: str, piece: str) -> bool:
        rows = self.section_rows(section)
        return (any(piece in _runs(c) for c in rows)
                or (len(piece) >= 25 and any(piece in cell for c in rows for cell in c))
                or self.find_quote(section, piece))

    def find_quote(self, section: str, quote: str) -> bool:
        return any(s == section and quote in t for s, t in self.text)

    def nearest(self, section: str, cited: str) -> str | None:
        import difflib
        piece = cited.split(" ; ")[0]
        candidates = [cells(c) for c in self.section_rows(section)] + [t for s, t in self.text if s == section]
        best = difflib.get_close_matches(piece, candidates, n=1, cutoff=0.5)
        return best[0] if best else None


def _group(rows: list, i: int) -> list:
    """The rest of row i, then the rows nested under it."""
    out = [rows[i][1:]]
    for r in rows[i + 1:]:
        if r and r[0] and not r[0].startswith("- "):
            break
        out.append(r)
    return out


def _in_order(parts: list, group: list) -> bool:
    k = 0
    for p in parts:
        while k < len(group) and p not in _runs(group[k]):
            k += 1
        if k == len(group):
            return False
        k += 1
    return True


def _runs(c: list) -> set:
    """Every run of consecutive cells in a row, as fairfax stores it ('- ' list markers optional)."""
    out = set()
    for v in (c, [c[0][2:], *c[1:]] if c and c[0].startswith("- ") else None):
        if v:
            out.update(cells(v[a:b]) for a in range(len(v)) for b in range(a + 1, len(v) + 1))
    return out


class _Reader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta, self.rows, self.text, self.title = {}, [], [], ""
        self.in_main = 0
        self.section = "top"
        self.h = self.buf = self.kind = self.row = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and a.get("name") in KEEP_META:
            self.meta[a["name"]] = a.get("content", "")
        if tag == "main":
            self.in_main += 1
        if not self.in_main:
            return
        if tag in ("h1", "h2", "h3", "h4"):
            self.h = (tag, a.get("id", ""))
            self.buf, self.kind = [], "H"
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.buf, self.kind = [], "C"
        elif tag in ("p", "li") and self.row is None and self.kind is None:
            self.buf, self.kind = [], tag.upper()
        elif tag == "br" and self.buf is not None:
            self.buf.append(" / ")
        elif tag == "img" and self.kind == "C":
            # Availability tables often use tick and cross images; keep the image's own name.
            m = ICON.search(a.get("src") or "")
            if m:
                self.buf.append(f" [{m.group(1)}] ")

    def _text(self) -> str:
        return " ".join("".join(self.buf).split())

    def handle_endtag(self, tag):
        if tag == "main":
            self.in_main -= 1
            return
        if not self.in_main:
            return
        if self.kind == "H" and self.h and tag == self.h[0]:
            t = self._text()
            self.section = self.h[1] or t
            if self.h[0] == "h1" and not self.title:
                self.title = t
            self.h, self.buf, self.kind = None, None, None
        elif self.kind == "C" and tag in ("td", "th"):
            if self.row is not None:
                self.row.append(self._text())
            self.buf, self.kind = None, None
        elif tag == "tr" and self.row is not None:
            self.rows.append((self.section, self.row))
            self.row = None
        elif self.kind in ("P", "LI") and tag.upper() == self.kind:
            t = self._text()
            if t:
                self.text.append((self.section, t))
            self.buf, self.kind = None, None

    def handle_data(self, d):
        if self.buf is not None:
            self.buf.append(d)


def parse(html: str, url: str = "") -> Page:
    r = _Reader()
    r.feed(html)
    return Page(url, r.meta, r.title, r.rows, r.text)


def fetch(url: str, timeout: int = 60, tries: int = 3) -> bytes:
    """GET a public page. Retries on rate limits and server errors, never on 404."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == tries - 1:
                raise
        time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")


def read(url: str) -> Page:
    return parse(fetch(url).decode("utf-8", errors="replace"), url)
