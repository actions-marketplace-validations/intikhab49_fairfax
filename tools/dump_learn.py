"""Dump a saved Learn page to text: meta dates, headings with anchor ids, table rows and paragraphs,
each tagged with the section anchor it sits under. Usage: dump_learn.py <in.html> <out.txt>"""
import sys
from html.parser import HTMLParser

KEEP_META = {"ms.date", "updated_at", "title", "git_commit_id", "original_content_git_url"}
BLOCKS = {"p", "li", "td", "th", "h1", "h2", "h3", "h4", "div"}


class Dump(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta, self.lines = {}, []
        self.in_main = 0
        self.section = "top"
        self.h = None
        self.buf = None
        self.kind = None
        self.row = None

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
        elif tag == "a" and self.buf is not None and self.kind in ("P", "LI", "C"):
            pass

    def _text(self):
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
            self.lines.append(f"\n## [{self.h[0]}#{self.h[1]}] {t}")
            self.h, self.buf, self.kind = None, None, None
        elif self.kind == "C" and tag in ("td", "th"):
            if self.row is not None:
                self.row.append(self._text())
            self.buf, self.kind = None, None
        elif tag == "tr" and self.row is not None:
            self.lines.append(f"  ROW[{self.section}] " + " | ".join(self.row))
            self.row = None
        elif self.kind in ("P", "LI") and tag.upper() == self.kind:
            t = self._text()
            if t:
                self.lines.append(f"  {self.kind}[{self.section}] {t}")
            self.buf, self.kind = None, None

    def handle_data(self, d):
        if self.buf is not None:
            self.buf.append(d)


def main():
    src, dst = sys.argv[1], sys.argv[2]
    d = Dump()
    with open(src, encoding="utf-8", errors="replace") as fh:
        d.feed(fh.read())
    with open(dst, "w", encoding="utf-8") as fh:
        for k in sorted(d.meta):
            fh.write(f"META {k} = {d.meta[k]}\n")
        fh.write("\n".join(d.lines) + "\n")
    print(f"{src}: {len(d.lines)} lines, ms.date={d.meta.get('ms.date')}, updated_at={d.meta.get('updated_at')}")


if __name__ == "__main__":
    main()
