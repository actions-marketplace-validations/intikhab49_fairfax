"""Generate the README header SVG. Self-hosted on purpose.

capsule-render and friends time out through GitHub's camo proxy often enough to leave a broken
image on the front page, so the header is generated here and committed. The card on the right is
the real result of checking the bundled example plan. Regenerate with:  python docs/make_header.py

Validates as XML before writing: a bare '&' in SVG text is invalid XML and GitHub renders it as
"Invalid image source" with no other warning.
"""
import datetime as dt
import pathlib
import xml.dom.minidom
from html import escape

from fairfax import dataset
from fairfax.check import check, load_plan

ROOT = pathlib.Path(__file__).resolve().parents[1]
W, H = 1200, 340
BG = "#0A0A14"
AMBER, CORAL, PINK = "#FFB020", "#FF6B4A", "#FF4E88"
LIME, BLUE, DIM = "#A3E635", "#5B9BFF", "#8B8BA7"
MONO = "ui-monospace,SFMono-Regular,Menlo,monospace"
SANS = "-apple-system,Segoe UI,Helvetica,sans-serif"


def card(x0, y0):
    """Terminal-style card with the example plan's real blocked findings."""
    ds = dataset.load()
    report = check(ds, load_plan(ROOT / "examples" / "field-inspections" / "plan.yaml"), dt.date(2026, 10, 11))
    counts = report.counts()
    blocked = [f.feature for f in report.groups()["blocked"]]
    lines = [(f"$ fairfax check plan.yaml", "#E8E8F0", "400"),
             (f"BLOCKED ({len(blocked)})", CORAL, "700")]
    lines += [(f"x {b}", "#E8E8F0", "400") for b in blocked]
    lines.append((f"{counts['blocked']} blocked &#183; {counts['ok']} ok &#183; every line cited", LIME, "400"))
    out = [f'<rect x="{x0}" y="{y0}" width="404" height="{30 + 22 * len(lines)}" rx="10" fill="#12121F" '
           f'stroke="{DIM}" stroke-opacity="0.35"/>']
    for i, (text, colour, weight) in enumerate(lines):
        text = text if "&#" in text else escape(text)
        out.append(f'<text x="{x0 + 18}" y="{y0 + 30 + 22 * i}" font-family="{MONO}" font-size="12.5" '
                   f'fill="{colour}" font-weight="{weight}">{text}</text>')
    return "\n    ".join(out), len(ds.features()), len(ds.endpoints), len(ds.sources)


def pills(x0, y0, items):
    out, x = [], x0
    for text, colour in items:
        w = 26 + 8.1 * len(text)
        out.append(f'<rect x="{x:.0f}" y="{y0}" width="{w:.0f}" height="28" rx="14" fill="none" '
                   f'stroke="{colour}" stroke-opacity="0.55"/>')
        out.append(f'<text x="{x + w / 2:.0f}" y="{y0 + 19}" fill="{colour}" text-anchor="middle">{text}</text>')
        x += w + 12
    return "\n    ".join(out)


def build():
    card_svg, n_facts, n_endpoints, n_sources = card(750, 64)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}"
     viewBox="0 0 {W} {H}" role="img"
     aria-label="fairfax: check a GCC, GCC High or Azure Government plan before you build it.
     {n_facts} features from Microsoft's own tables, every finding cited and re-checked every week.">
  <defs>
    <linearGradient id="grad" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="{AMBER}"/>
      <stop offset="55%" stop-color="{CORAL}"/>
      <stop offset="100%" stop-color="{PINK}"/>
    </linearGradient>
    <linearGradient id="fade" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{CORAL}" stop-opacity="0.22"/>
      <stop offset="100%" stop-color="{BG}" stop-opacity="0"/>
    </linearGradient>
    <pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse">
      <path d="M28 0 L0 0 0 28" fill="none" stroke="#FFFFFF" stroke-opacity="0.04" stroke-width="1"/>
    </pattern>
  </defs>

  <rect width="{W}" height="{H}" fill="{BG}"/>
  <rect width="{W}" height="{H}" fill="url(#grid)"/>
  <circle cx="{W - 160}" cy="70" r="240" fill="url(#fade)"/>

  <text x="64" y="86" font-family="{MONO}" font-size="13" letter-spacing="3.5" fill="{LIME}">MICROSOFT GOV CLOUD
        &#183; AVAILABILITY CHECK</text>

  <text x="60" y="164" font-family="Georgia,'Times New Roman',serif" font-size="68" font-weight="700"
        fill="url(#grad)">fairfax</text>

  <text x="64" y="204" font-family="{SANS}" font-size="19" fill="#E8E8F0">Check a GCC, GCC High or Azure
        Government plan before you build it.</text>
  <text x="64" y="232" font-family="{SANS}" font-size="19" fill="{DIM}">Every finding cites the Microsoft
        row it came from.</text>

  <g font-family="{MONO}" font-size="12">
    {pills(64, 262, [(f"{n_facts} FEATURES", AMBER), (f"{n_endpoints} ENDPOINTS", LIME),
                     (f"{n_sources} MICROSOFT PAGES", BLUE), ("VERIFIED WEEKLY", LIME), ("MIT", PINK)])}
  </g>

  <g>
    {card_svg}
  </g>
</svg>
"""


if __name__ == "__main__":
    svg = build()
    out = pathlib.Path(__file__).parent / "header.svg"
    xml.dom.minidom.parseString(svg)          # fails loudly on a bare '&'
    out.write_text(svg, encoding="utf-8", newline="\n")
    print(f"wrote {out} ({len(svg)} bytes, valid XML)")
