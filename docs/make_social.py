"""Generate the social preview card (1280x640, GitHub's recommended size).

  python docs/make_social.py

Writes docs/social.svg and, with Chrome installed, renders docs/social.png. Upload the PNG in GitHub:
Settings → General → Social preview. The website's og:image is the same file. It reuses the header's
colours and its terminal card, so the counts and findings come from the dataset.
"""
import pathlib
import shutil
import subprocess
import sys
import xml.dom.minidom

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "src"))

import make_header as h  # noqa: E402

W, H = 1280, 640


def pills(x0, y0, items):
    out, x = [], x0
    for text, colour in items:
        w = 34 + 10.4 * len(text)
        out.append(f'<rect x="{x:.0f}" y="{y0}" width="{w:.0f}" height="38" rx="19" fill="none" '
                   f'stroke="{colour}" stroke-opacity="0.6"/>')
        out.append(f'<text x="{x + w / 2:.0f}" y="{y0 + 25}" fill="{colour}" text-anchor="middle">{text}</text>')
        x += w + 14
    return "\n    ".join(out)


def build():
    card_svg, n_facts, n_endpoints, n_sources = h.card(0, 0)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img"
     aria-label="fairfax: check a GCC, GCC High or Azure Government plan before you build it. {n_facts} facts
     from Microsoft's own tables, every finding cited.">
  <defs>
    <linearGradient id="grad" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="{h.AMBER}"/>
      <stop offset="55%" stop-color="{h.CORAL}"/>
      <stop offset="100%" stop-color="{h.PINK}"/>
    </linearGradient>
    <linearGradient id="fade" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{h.CORAL}" stop-opacity="0.22"/>
      <stop offset="100%" stop-color="{h.BG}" stop-opacity="0"/>
    </linearGradient>
    <pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse">
      <path d="M28 0 L0 0 0 28" fill="none" stroke="#FFFFFF" stroke-opacity="0.04" stroke-width="1"/>
    </pattern>
  </defs>
  <rect width="{W}" height="{H}" fill="{h.BG}"/>
  <rect width="{W}" height="{H}" fill="url(#grid)"/>
  <circle cx="{W - 170}" cy="90" r="330" fill="url(#fade)"/>

  <text x="72" y="112" font-family="{h.MONO}" font-size="18" letter-spacing="4" fill="{h.LIME}">MICROSOFT GOV CLOUD
        &#183; AVAILABILITY CHECK</text>
  <text x="66" y="232" font-family="Georgia,'Times New Roman',serif" font-size="112" font-weight="700"
        fill="url(#grad)">fairfax</text>
  <text x="72" y="300" font-family="{h.SANS}" font-size="30" fill="#E8E8F0">Is it available in GCC High?</text>
  <text x="72" y="342" font-family="{h.SANS}" font-size="24" fill="{h.DIM}">Check a GCC, GCC High or Azure Government</text>
  <text x="72" y="374" font-family="{h.SANS}" font-size="24" fill="{h.DIM}">plan before you build it. Every finding cited.</text>

  <g font-family="{h.MONO}" font-size="16">
    {pills(72, 418, [(f"{n_facts} FACTS", h.AMBER), (f"{n_endpoints} ENDPOINTS", h.LIME),
                     (f"{n_sources} MICROSOFT SOURCES", h.BLUE)])}
  </g>

  <text x="72" y="560" font-family="{h.MONO}" font-size="24" fill="#E8E8F0">$ pip install fairfax</text>
  <text x="72" y="596" font-family="{h.MONO}" font-size="17" fill="{h.DIM}">github.com/intikhab49/fairfax &#183; MIT</text>

  <g transform="translate(726 196) scale(1.24)">
    {card_svg}
  </g>
</svg>
"""


if __name__ == "__main__":
    svg = build()
    xml.dom.minidom.parseString(svg)          # fails loudly on a bare '&'
    (HERE / "social.svg").write_text(svg, encoding="utf-8", newline="\n")
    chrome = shutil.which("chrome") or r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if pathlib.Path(chrome).exists():
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={W},{H}",
                        f"--screenshot={HERE / 'social.png'}", (HERE / "social.svg").resolve().as_uri()],
                       check=False, capture_output=True)
    print("wrote docs/social.svg" + (" and docs/social.png" if (HERE / "social.png").exists() else ""))
