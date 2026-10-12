"""Generate the fairfax website from the bundled dataset. GitHub Pages serves docs/ from main.

  python docs/make_site.py

Writes the landing page, one availability page per service, the endpoints page, llms.txt,
llms-full.txt, sitemap.xml and favicon.svg. Every table, count and FAQ answer is computed from the
dataset, so after a change to a YAML file, re-run this script and commit what changed.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import sys
from html import escape

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fairfax import __version__, dataset  # noqa: E402
from fairfax.check import PERIOD_END, check, load_plan  # noqa: E402
from fairfax.render import by_feature, check_text  # noqa: E402

DOCS = ROOT / "docs"
SITE = "https://intikhab49.github.io/fairfax/"
REPO = "https://github.com/intikhab49/fairfax"
PYPI = "https://pypi.org/project/fairfax/"
RAW = "https://raw.githubusercontent.com/intikhab49/fairfax/main/src/fairfax/data/"
AUTHOR = {"@type": "Person", "@id": "https://github.com/intikhab49", "name": "Intikhab Azam",
          "url": "https://github.com/intikhab49"}
TODAY = dt.date.today()
BING_VERIFY = '<meta name="msvalidate.01" content="8696AEC33B172905558B45B0DB631DAD">\n'  # Bing Webmaster Tools, keep

TENANT = {"gcc": "GCC", "gcchigh": "GCC High", "dod": "DoD"}
CLOUD = {"commercial": "Commercial Azure", "government": "Azure Government"}
PAIRING = {f"{t}+{c}": f"{TENANT[t]} tenant, {where}" for t in TENANT
           for c, where in (("commercial", "commercial Azure"), ("government", "Azure Government"))}
LABEL = {"ga": "GA", "available": "Available", "preview": "Preview", "private-preview": "Private preview",
         "limited": "Limited", "rolling-out": "Rolling out", "planned": "Planned", "in-development": "In development",
         "backlog": "On engineering backlog", "not-available": "Not available", "no-plans": "No plans",
         "not-possible": "Not possible"}
KIND = {"ga": "ok", "available": "ok", "preview": "note", "private-preview": "note", "limited": "note",
        "rolling-out": "note", "planned": "no", "in-development": "no", "backlog": "no",
        "not-available": "no", "no-plans": "no", "not-possible": "no"}

SERVICES = [
    {"slug": "sentinel", "name": "Microsoft Sentinel", "prefixes": ("sentinel",), "grep": "sentinel",
     "title": "Microsoft Sentinel in Azure Government & GCC High: availability",
     "h1": "Microsoft Sentinel in Azure Government, GCC, GCC High and DoD",
     "desc": "Which Microsoft Sentinel features work in Azure Government, and which Microsoft 365 "
             "connectors work for GCC, GCC High and DoD. {n} entries, each cited."},
    {"slug": "defender-for-cloud", "name": "Microsoft Defender for Cloud", "prefixes": ("defender-for-cloud",),
     "grep": "defender-for-cloud",
     "title": "Defender for Cloud in Azure Government: feature availability",
     "h1": "Microsoft Defender for Cloud in Azure Government",
     "desc": "Which Defender for Cloud plans and features are available in Azure Government versus "
             "commercial Azure. {n} features from Microsoft's tables, each cited."},
    {"slug": "azure-machine-learning", "name": "Azure Machine Learning", "prefixes": ("azure-ml",),
     "grep": "azure-ml",
     "title": "Azure Machine Learning in Azure Government: feature availability",
     "h1": "Azure Machine Learning in Azure Government",
     "desc": "Which Azure Machine Learning features work in Azure Government versus commercial Azure, "
             "with region limits. {n} features, each cited."},
    {"slug": "azure-openai", "name": "Azure OpenAI", "prefixes": ("azure-openai",), "grep": "azure-openai",
     "title": "Azure OpenAI models in Azure Government (and deployment types)",
     "h1": "Azure OpenAI models in Azure Government",
     "desc": "Which Azure OpenAI models Microsoft sells in Azure Government and their deployment types "
             "in usgovarizona and usgovvirginia. {n} models, each cited."},
    {"slug": "azure-ai-language", "name": "Azure AI Language", "prefixes": ("ai-language",),
     "grep": "ai-language",
     "title": "Azure AI Language in Azure Government: US Gov region support",
     "h1": "Azure AI Language in Azure Government",
     "desc": "Which Azure AI Language features have a US Gov Virginia or US Gov Arizona region, and "
             "which one is retiring. {n} features, each cited."},
    {"slug": "power-platform", "name": "Power Platform",
     "prefixes": ("power-apps", "power-automate", "copilot-studio", "power-pages", "ai-builder", "dataverse",
                  "power-platform"),
     "grep": "power-",
     "title": "Power Apps & Power Automate in GCC, GCC High, DoD: availability",
     "h1": "Power Platform in GCC, GCC High and DoD",
     "desc": "Which Power Apps, Power Automate, Copilot Studio, Power Pages, AI Builder and Dataverse "
             "features work in GCC, GCC High and DoD. {n} features, each cited."},
    # Microsoft 365, added in 0.2.0. "group": "name" puts each product or area under its own heading.
    {"slug": "microsoft-365-copilot", "name": "Microsoft 365 Copilot", "prefixes": ("m365-copilot",),
     "grep": "m365-copilot", "group": "name",
     "title": "Microsoft 365 Copilot in GCC, GCC High & DoD: availability",
     "h1": "Microsoft 365 Copilot in GCC, GCC High and DoD",
     "desc": "Which Microsoft 365 Copilot features work in GCC, GCC High and DoD: Researcher, Create, agents, "
             "Copilot in Teams and more. {n} features, each cited."},
    {"slug": "teams", "name": "Microsoft Teams", "prefixes": ("teams",), "grep": "teams/", "group": "name",
     "title": "Microsoft Teams in GCC, GCC High & DoD: features and apps",
     "h1": "Microsoft Teams in GCC, GCC High and DoD",
     "desc": "Which Teams features and app capabilities work in GCC, GCC High and DoD: shared channels, "
             "webinars, third-party apps, workflows. {n} features, each cited."},
    {"slug": "exchange-online", "name": "Exchange Online", "prefixes": ("exchange",), "grep": "exchange",
     "group": "name",
     "title": "Exchange Online in GCC, GCC High & DoD: feature availability",
     "h1": "Exchange Online in GCC, GCC High and DoD",
     "desc": "Which Exchange Online features work in GCC, GCC High and DoD, with Microsoft's key "
             "considerations for each. {n} features, each cited."},
    {"slug": "sharepoint-onedrive", "name": "SharePoint and OneDrive", "prefixes": ("sharepoint", "onedrive"),
     "grep": "sharepoint", "group": "name",
     "title": "SharePoint & OneDrive in GCC High and DoD: what's missing",
     "h1": "SharePoint and OneDrive in GCC, GCC High and DoD",
     "desc": "SharePoint and OneDrive features Microsoft says are missing or limited in GCC, GCC High and DoD, "
             "quoted sentence by sentence. {n} features, each cited."},
    {"slug": "purview", "name": "Microsoft Purview", "prefixes": ("purview",), "grep": "purview", "group": "name",
     "title": "Microsoft Purview in GCC, GCC High & DoD: feature status",
     "h1": "Microsoft Purview in GCC, GCC High and DoD",
     "desc": "Status of Microsoft Purview features in GCC, GCC High and DoD (available, in development, on the "
             "engineering backlog) from Microsoft's three planning pages. {n} features."},
    {"slug": "intune", "name": "Microsoft Intune", "prefixes": ("intune",), "grep": "intune", "group": "name",
     "title": "Intune in GCC High and DoD: supported, planned, not available",
     "h1": "Microsoft Intune in GCC High and DoD",
     "desc": "Which Intune features Microsoft lists as not available or planned for GCC High and DoD, such as "
             "Windows Autopilot and Remediations. {n} features, each cited."},
    {"slug": "defender", "name": "Microsoft Defender",
     "prefixes": ("defender-endpoint", "defender-xdr", "defender-vulnerability-management"),
     "grep": "defender-", "group": "name",
     "title": "Defender for Endpoint & Defender XDR in GCC, GCC High, DoD",
     "h1": "Defender for Endpoint and Defender XDR in GCC, GCC High and DoD",
     "desc": "Feature parity of Defender for Endpoint, Defender XDR and Defender Vulnerability Management in GCC, "
             "GCC High and DoD, from Microsoft's tables. {n} features, each cited."},
]
PRODUCT = {"power-apps": "Power Apps", "power-automate": "Power Automate", "copilot-studio": "Copilot Studio",
           "power-pages": "Power Pages", "ai-builder": "AI Builder", "dataverse": "Dataverse",
           "power-platform": "Platform, admin and governance"}
CLOUD_PAGE = {"purview-gcc": "GCC", "purview-gcchigh": "GCC High", "purview-dod": "DoD"}

CSS = """
:root{--ink:#16202c;--muted:#5a6675;--blue:#2a78d6;--green:#1baf7a;--bg:#fbfcfd;--code:#0f1722;--line:#e3e8ee}
*{box-sizing:border-box}
body{margin:0;font:17px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:var(--ink);background:var(--bg)}
.top{border-bottom:1px solid var(--line);background:#fff}
.top div{max-width:980px;margin:0 auto;padding:12px 22px;display:flex;flex-wrap:wrap;gap:6px 22px;align-items:center}
.top a{color:var(--ink);text-decoration:none;font-size:.95rem}
.top a.brand{font-family:Georgia,serif;font-weight:700;font-size:1.2rem;margin-right:auto}
main{max-width:980px;margin:0 auto;padding:28px 22px 64px}
img{max-width:100%;height:auto}
h1{font-size:2rem;line-height:1.2;margin:22px 0 12px}
h2{font-size:1.35rem;margin:44px 0 10px}
h3{font-size:1.02rem;margin:22px 0 4px}
p.lead{font-size:1.12rem;color:var(--muted)}
a{color:var(--blue)}
.crumbs{font-size:.88rem;color:var(--muted)}
.crumbs a{color:var(--muted)}
.cta{display:inline-block;margin:8px 10px 0 0;padding:11px 18px;border-radius:8px;background:var(--blue);color:#fff;text-decoration:none;font-weight:600}
.cta.alt{background:transparent;color:var(--blue);border:1.5px solid var(--blue)}
pre{background:var(--code);color:#dfe7ef;padding:16px 18px;border-radius:8px;overflow-x:auto;font-size:.86rem;line-height:1.5}
code{font-family:ui-monospace,"Cascadia Code",Consolas,monospace}
p code,li code,td code{background:#eef2f6;padding:1px 5px;border-radius:4px;font-size:.84em}
.t{overflow-x:auto;margin:14px 0}
table{border-collapse:collapse;width:100%;font-size:.9rem;background:#fff}
th,td{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}
th{background:#f3f6f9;font-weight:600}
td.s{white-space:nowrap;font-weight:600}
td.ok{color:#0f7a55;background:#effaf5}
td.note{color:#8a5a00;background:#fff8e8}
td.no{color:#b3261e;background:#fdf0ef}
td .q,td .n{display:block;color:var(--muted);font-size:.84rem;margin-top:3px}
td .n{color:#8a5a00}
td.src{font-size:.84rem;min-width:128px;white-space:nowrap}
.dates{color:var(--muted)}
.stat{color:var(--green);font-weight:700}
ul{padding-left:22px}
footer{max-width:980px;margin:0 auto;padding:18px 22px 40px;border-top:1px solid var(--line);color:var(--muted);font-size:.88rem}
"""

FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#FFB020"/>
<stop offset=".55" stop-color="#FF6B4A"/><stop offset="1" stop-color="#FF4E88"/></linearGradient></defs>
<rect width="64" height="64" rx="14" fill="#0A0A14"/>
<text x="32" y="47" text-anchor="middle" font-family="Georgia,serif" font-size="44" font-weight="700" fill="url(#g)">f</text>
</svg>
"""


# ---------------------------------------------------------------- data helpers
def status(value: str) -> tuple[str, str]:
    """Display label and css class for a status value."""
    if value.startswith("planned:"):
        period = value.split(":", 1)[1]                        # CY2026-H1
        year, part = int(period[2:6]), period[7:]
        text = f"Planned {period.replace('-', ' ')}"
        if dt.date(year, *PERIOD_END[part]) < TODAY:
            text += " (date passed)"
        return text, "no"
    return LABEL[value], KIND[value]


def anchor(key: str) -> str:
    return re.sub(r"[^a-z0-9.-]+", "-", key.lower())


def cite(source, url: str) -> str:
    """Compact source cell: a link to the exact section, and the two dates. Full titles are listed below."""
    where = "Microsoft PDF" if source.url.startswith("https://aka.ms/") else "Microsoft Learn"
    return (f'<a href="{escape(url)}" title="{escape(source.title)}">{where}</a><br>'
            f'<span class="dates">updated {source.page_updated}<br>checked {source.checked}</span>')


def facts_for(ds, prefixes) -> list:
    return [f for f in ds.facts if f.feature.split("/")[0] in prefixes]


def unavailable(facts, key) -> int:
    return sum(1 for f in facts if key in f.status and status(f.status[key])[1] == "no")


def connector_pattern(facts) -> list | None:
    """The pairings Microsoft marks not possible, if every connector shares the same set."""
    sets = {tuple(sorted(k for k, v in f.status.items() if v == "not-possible")) for f in facts}
    return list(next(iter(sets))) if len(sets) == 1 else None


def jsonld(data) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False).replace("<", "\\u003c")


def md_code(text: str) -> str:
    """Escape text and turn `spans` into <code>."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", escape(text))


# ---------------------------------------------------------------- page shell
def page(path: str, title: str, desc: str, body: str, graph: list, crumbs: list | None = None) -> str:
    url = SITE + path
    trail = ""
    if crumbs:
        graph = graph + [{"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": name, "item": SITE + p}
            for i, (name, p) in enumerate(crumbs)]}]
        trail = '<p class="crumbs">' + " / ".join(
            f'<a href="{SITE + p}">{escape(name)}</a>' for name, p in crumbs[:-1]) + f" / {escape(crumbs[-1][0])}</p>"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(desc)}">
<link rel="canonical" href="{url}">
{BING_VERIFY if not path else ""}<link rel="icon" href="{SITE}favicon.svg" type="image/svg+xml">
<meta name="author" content="Intikhab Azam">
<meta property="og:type" content="website">
<meta property="og:site_name" content="fairfax">
<meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{SITE}social.png">
<meta property="og:image:width" content="1280">
<meta property="og:image:height" content="640">
<meta property="og:image:alt" content="fairfax: check a GCC, GCC High or Azure Government plan before you build it">
<meta name="twitter:card" content="summary_large_image">
<link rel="alternate" type="text/plain" href="{SITE}llms.txt" title="llms.txt">
<script type="application/ld+json">
{jsonld({"@context": "https://schema.org", "@graph": graph})}
</script>
<style>{CSS}</style>
</head>
<body>
<header class="top"><div><a class="brand" href="{SITE}">fairfax</a>
<a href="{SITE}availability/">Availability tables</a><a href="{SITE}endpoints/">Endpoints</a>
<a href="{SITE}errors/">Sign-in errors</a><a href="{REPO}">GitHub</a><a href="{PYPI}">PyPI</a></div></header>
<main>
{trail}
{body}
</main>
<footer>
fairfax {__version__} · MIT · by <a href="https://github.com/intikhab49">Intikhab Azam</a> ·
<a href="{REPO}">Source</a> · <a href="{SITE}llms.txt">llms.txt</a><br>
Statuses are quoted from Microsoft's own documentation and link to it. fairfax is an independent open source
project, not affiliated with Microsoft, and not compliance advice.
</footer>
</body>
</html>
"""


# ---------------------------------------------------------------- tables
def fact_table(facts, cols) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for _, h in cols)
    rows = []
    for key, (items, merged) in by_feature(facts).items():
        f = items[0]
        cells = []
        for k, _ in cols:
            if k in merged:
                text, kind = status(merged[k])
                cells.append(f'<td class="s {kind}">{escape(text)}</td>')
            else:
                cells.append('<td class="s">not listed</td>')
        if len(items) == 1:
            extra = [f'<span class="q">Microsoft: “{escape(f.row)}”</span>']
            source_cell = cite(f.source, f.url)
        else:  # one row on each cloud's own page: the statuses in the cells are Microsoft's words from each page
            extra = []
            source_cell = '<a href="#per-cloud-pages">' + " · ".join(
                escape(CLOUD_PAGE.get(i.source.key, i.source.key)) for i in items) + " pages</a>"
        for note in dict.fromkeys(i.note for i in items if i.note):
            extra.append(f'<span class="n">{escape(note)}</span>')
        if f.retires:
            extra.append(f'<span class="n">Retires {f.retires}. {escape(f.retires_quote or "")}</span>')
        if f.instead:
            extra.append(f'<span class="n">{escape(f.instead)}</span>')
        rows.append(f'<tr id="{anchor(key)}"><td><strong>{escape(f.name)}</strong><br>'
                    f'<code>{escape(key)}</code>{"".join(extra)}</td>{"".join(cells)}'
                    f'<td class="src">{source_cell}</td></tr>')
    return (f'<div class="t"><table><thead><tr><th>Feature and feature key</th>{head}<th>Source</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def azure_cols(facts) -> list:
    return [(k, CLOUD[k]) for k in ("commercial", "government") if any(k in f.status for f in facts)]


def tenant_cols() -> list:
    return [(k, TENANT[k]) for k in TENANT]


def sources_list(facts) -> str:
    seen = {}
    for f in facts:
        seen.setdefault(f.source.key, [f.source, 0])[1] += 1
    items = "".join(f'<li><a href="{escape(s.url)}">{escape(s.title)}</a>: page updated {s.page_updated}, '
                    f"checked {s.checked}, {n} entr{'y' if n == 1 else 'ies'}</li>" for s, n in seen.values())
    return f"<ul>{items}</ul>"


# ---------------------------------------------------------------- service pages
def service_page(ds, svc) -> tuple[str, str]:
    facts = facts_for(ds, svc["prefixes"])
    by_azure = [f for f in facts if f.by == "azure"]
    by_tenant = [f for f in facts if f.by == "tenant"]
    by_both = [f for f in facts if f.by == "tenant+azure"]
    n, name = len({f.feature for f in facts}), svc["name"]
    path = f"availability/{svc['slug']}/"

    lead = []
    if by_azure and "government" in azure_cols(by_azure)[-1]:
        no = unavailable(by_azure, "government")
        note = sum(1 for f in by_azure if status(f.status.get("government", "ga"))[1] == "note")
        if svc["slug"] == "azure-openai":
            lead.append(f"Microsoft's list of models sold by Azure in Azure Government has <span class=\"stat\">"
                        f"{len(by_azure)}</span> Azure OpenAI models, each with its own deployment types. A model "
                        "missing from this page isn't on Microsoft's list.")
        else:
            lead.append(f"fairfax tracks {len(by_azure)} {name} features in Azure Government: <span class=\"stat\">"
                        f"{no}</span> not available, {note} in preview or available with limits, and "
                        f"{len(by_azure) - no - note} available.")
    if by_tenant:
        covered = [t for t in TENANT if any(t in f.status for f in by_tenant)]
        lead.append(f"Of the {len({f.feature for f in by_tenant})} features fairfax tracks, these are not available "
                    "today: " + ", ".join(f'<span class="stat">{unavailable(by_tenant, t)}</span> in {TENANT[t]}'
                                          for t in covered)
                    + ". Planned and in-development features count as not available until Microsoft ships them.")
    if by_both:
        lead.append(f"For the {len(by_both)} Microsoft 365 data connectors, the answer depends on where your tenant "
                    "lives and where your Sentinel workspace lives.")

    body = [f"<h1>{escape(svc['h1'])}</h1>",
            f'<p class="lead">{" ".join(lead)} Every row quotes Microsoft and links to the page it came from.</p>']
    if by_azure:
        heading = (f"{name} models in Azure Government" if svc["slug"] == "azure-openai"
                   else f"{name} features: commercial Azure and Azure Government")
        body += [f"<h2>{escape(heading)}</h2>", fact_table(by_azure, azure_cols(by_azure))]
    if by_both:
        pattern = connector_pattern(by_both)
        if pattern:
            cols = [(k, PAIRING[k]) for k in ("gcc+commercial", "gcchigh+government", "dod+government")
                    if k not in pattern]
            impossible = ", ".join(PAIRING[k].replace(", ", " with a workspace in ") for k in pattern)
            note = (f"<p>Microsoft marks the other pairings as not possible for every connector: {escape(impossible)}. "
                    "A GCC tenant's data lives in commercial Azure, so a workspace in Azure Government can't "
                    "reach it.</p>")
        else:
            cols, note = [(k, PAIRING[k]) for k in PAIRING], ""
        body += ["<h2>Microsoft 365 data connectors by tenant and workspace cloud</h2>", note,
                 fact_table(by_both, cols)]
    if by_tenant:
        per_cloud = [s for k, s in ((k, ds.sources.get(k)) for k in CLOUD_PAGE) if s and any(
            f.source.key == k for f in by_tenant)]
        if per_cloud:
            links = "".join(f'<li id="{"per-cloud-pages" if i == 0 else ""}"><a href="{escape(s.url)}">'
                            f'{escape(s.title)}</a>: page updated {s.page_updated}, checked {s.checked}</li>'
                            for i, s in enumerate(per_cloud))
            body += ["<p>Microsoft publishes one planning page per cloud, each with a status per feature. Every status "
                     "below is Microsoft's own word from that cloud's page:</p>", f"<ul>{links}</ul>"]
        if svc.get("group") == "name":  # one table per product or area, from the name before the colon
            groups: dict[str, list] = {}
            for f in by_tenant:
                groups.setdefault(f.name.split(":", 1)[0], []).append(f)
            for label, group in groups.items():
                cols = [(k, TENANT[k]) for k in TENANT if any(k in f.status for f in group)]
                clouds = " and ".join(", ".join(h for _, h in cols).rsplit(", ", 1))
                body += [f"<h2>{escape(label)} in {escape(clouds)}</h2>", fact_table(group, cols)]
        else:
            for prefix in svc["prefixes"]:
                group = [f for f in by_tenant if f.feature.startswith(prefix + "/")]
                if group:
                    body += [f"<h2>{escape(PRODUCT[prefix])} in GCC, GCC High and DoD</h2>",
                             fact_table(group, tenant_cols())]
    roadmap = [r for r in ds.roadmap if any(r_f.split("/")[0] in svc["prefixes"] for r_f in r.features)]
    if roadmap:
        items = "".join(
            f'<li><code>{escape(", ".join(r.features))}</code>: <a href="{escape(r.url)}">roadmap {r.id}</a>, '
            f"“{escape(r.title)}”, {escape(r.status)} for {escape(', '.join(r.clouds))}, target {r.ga}"
            f"{' (that month has passed)' if r.ga < TODAY.strftime('%Y-%m') and r.status != 'Launched' else ''}.</li>"
            for r in roadmap)
        body += ["<h2>On Microsoft's 365 roadmap</h2>",
                 "<p>Roadmap items linked by hand to features above that are missing in a cloud. "
                 "<code>fairfax check</code> shows them on blocked findings.</p>", f"<ul>{items}</ul>"]
    body += ["<h2>How to read these tables</h2>",
             "<ul><li><strong>GA</strong> and <strong>Available</strong>: Microsoft lists it as available.</li>"
             "<li><strong>Preview</strong>, <strong>Private preview</strong>, <strong>Limited</strong>, "
             "<strong>Rolling out</strong>: available with conditions, or on its way.</li>"
             "<li><strong>Not available</strong>, <strong>No plans</strong>, <strong>Planned</strong>, "
             "<strong>In development</strong>, <strong>On engineering backlog</strong>: you can't use it there "
             "today. These are Microsoft's own words. A planned date that has passed is marked, so you re-check "
             "it.</li><li><strong>Not possible</strong>: Microsoft says that pairing of clouds can't work.</li>"
             "<li><strong>not listed</strong>: Microsoft's page doesn't give a status for that cloud.</li></ul>",
             "<p>A feature missing from this page tells you nothing about whether it works. fairfax only knows "
             "what is in its dataset.</p>",
             "<h2>Check your own plan</h2>",
             f"<pre><code>pip install fairfax\nfairfax facts --grep {escape(svc['grep'])}\n"
             "fairfax check plan.yaml       # tenant, azure and the feature keys you plan to use</code></pre>",
             f'<p>The feature keys in the tables above go straight into a plan file. See the '
             f'<a href="{REPO}#writing-a-plan">plan format</a>.</p>',
             "<h2>Sources</h2>", sources_list(facts)]

    srcs = {f.source.key: f.source for f in facts}.values()
    graph = [{"@type": "WebPage", "@id": SITE + path, "url": SITE + path, "name": svc["title"],
              "description": svc["desc"].format(n=n), "inLanguage": "en",
              "dateModified": max(s.checked for s in srcs), "isPartOf": {"@id": SITE + "#website"},
              "about": {"@type": "Thing", "name": name}, "author": AUTHOR,
              "citation": [{"@type": "CreativeWork", "name": s.title, "url": s.url} for s in srcs]}]
    crumbs = [("fairfax", ""), ("Availability tables", "availability/"), (name, path)]
    return path, page(path, svc["title"], svc["desc"].format(n=n), "\n".join(body), graph, crumbs)


# ---------------------------------------------------------------- overview page
def overview_page(ds) -> tuple[str, str]:
    path = "availability/"
    rows = []
    for svc in SERVICES:
        facts = facts_for(ds, svc["prefixes"])
        az = [f for f in facts if f.by == "azure" and "government" in f.status]
        ten = [f for f in facts if f.by == "tenant"]
        both = [f for f in facts if f.by == "tenant+azure"]
        gov = str(unavailable(az, "government")) if az else "–"
        if ten:
            per = " · ".join(str(unavailable(ten, t)) if any(t in f.status for f in ten) else "–" for t in TENANT)
        elif both:
            per = " · ".join(str(unavailable(both, k)) for k in ("gcc+commercial", "gcchigh+government",
                                                                 "dod+government")) + "*"
        else:
            per = "–"
        rows.append(f'<tr><td><a href="{SITE}availability/{svc["slug"]}/">{escape(svc["name"])}</a></td>'
                    f"<td>{len({f.feature for f in facts})}</td><td>{gov}</td><td>{per}</td></tr>")
    sources = sorted(ds.sources.values(), key=lambda s: s.title.lower())
    count = {}
    for item in [*ds.facts, *ds.rules, *ds.endpoints, *ds.errors, *ds.roadmap]:
        count[item.source.key] = count.get(item.source.key, 0) + 1
    features = len(ds.features())

    def snapshot(s):
        return f'<a href="{escape(s.archived)}">snapshot</a>' if s.archived else ""

    src_rows = "".join(f'<tr><td><a href="{escape(s.url)}">{escape(s.title)}</a></td><td>{s.page_updated}</td>'
                       f"<td>{s.checked}</td><td>{count.get(s.key, 0)}</td><td>{snapshot(s)}</td></tr>"
                       for s in sources)
    files = sorted(p.name for p in (ROOT / "src" / "fairfax" / "data").glob("*.yaml"))
    title = "GCC, GCC High, DoD & Azure Government feature availability tables"
    desc = (f"Feature availability tables for Microsoft's US government clouds, built from Microsoft's own pages: "
            f"{features} features, {len(ds.sources)} sources, every row cited and dated.")
    body = f"""<h1>Microsoft government cloud feature availability</h1>
<p class="lead">One table per service for GCC, GCC High, DoD and Azure Government, built from Microsoft's own
availability pages: {features} features across Azure, Power Platform and Microsoft 365, {len(ds.rules)} cross-cloud
rules and {len(ds.endpoints)} endpoint mappings. Every row quotes Microsoft, links to the page and carries two dates:
when Microsoft last updated the page and when fairfax last checked it.</p>
<h2>Services</h2>
<div class="t"><table><thead><tr><th>Service</th><th>Features tracked</th><th>Not available in Azure Government</th>
<th>Not available in GCC · GCC High · DoD</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
<p>* For Sentinel, the Microsoft 365 data connectors with the workspace in the tenant's own cloud.
Commercial-cloud hosts and their government equivalents are on the <a href="{SITE}endpoints/">endpoints page</a>.</p>
<h2>Sources</h2>
<div class="t"><table><thead><tr><th>Microsoft page</th><th>Page updated</th><th>Checked</th><th>Entries</th>
<th>Archived copy</th></tr></thead>
<tbody>{src_rows}</tbody></table></div>
<p>Every Monday a workflow runs <code>fairfax verify</code>, which re-reads each of these pages and confirms that every
row and quote fairfax cites is still there, word for word. If Microsoft changes one, the workflow opens an issue that
shows the cited text next to what the page says now; if a page is gone, the issue says so too. Each page also has a
Wayback Machine snapshot that was checked to hold the same rows, so a citation can still be checked after Microsoft moves
or deletes the page. You can run the same checks yourself: <code>fairfax verify</code> and
<code>fairfax verify --archived</code>.</p>
<h2>Download the data</h2>
<p>The dataset is plain YAML in the repository, MIT licensed: {", ".join(f'<a href="{RAW + n}">{n}</a>' for n in files)}.
Or from the command line: <code>fairfax facts --format json</code>.</p>"""
    dataset_ld = {
        "@type": "Dataset", "@id": SITE + path + "#dataset", "url": SITE + path,
        "name": "Microsoft US government cloud feature availability (GCC, GCC High, DoD, Azure Government)",
        "description": (f"Availability of {features} features in Microsoft 365 GCC, GCC High and DoD and in Azure "
                        f"Government, {len(ds.rules)} cross-cloud rules, {len(ds.endpoints)} commercial-to-government "
                        f"endpoint mappings and {len(ds.errors)} cross-cloud sign-in errors. Each entry quotes the row "
                        "from Microsoft's own documentation, links to the page and section, and records the page's "
                        "updated date and the date it was last checked."),
        "keywords": ["GCC", "GCC High", "DoD", "Azure Government", "Microsoft 365", "feature availability",
                     "cloud parity", "Microsoft 365 Copilot", "Microsoft Teams", "Exchange Online", "Microsoft Purview",
                     "Microsoft Intune", "Microsoft Defender", "Microsoft Sentinel", "Defender for Cloud",
                     "Power Platform", "Azure OpenAI"],
        "license": "https://opensource.org/licenses/MIT", "isAccessibleForFree": True,
        "creator": AUTHOR, "dateModified": max(s.checked for s in ds.sources.values()),
        "isBasedOn": [s.url for s in sources],
        "distribution": [{"@type": "DataDownload", "encodingFormat": "application/yaml", "contentUrl": RAW + n}
                         for n in files],
        "measurementTechnique": "Rows copied from Microsoft's availability tables, parsed into statuses by "
                                "tools/build_facts.py and tools/build_m365.py, re-parsed by the test suite, and "
                                "compared with the live pages every week by fairfax verify.",
        "variableMeasured": "Availability status per cloud: GA, available, preview, limited, rolling out, planned, "
                            "in development, on engineering backlog, not available, no plans, not possible"}
    graph = [{"@type": "WebPage", "@id": SITE + path, "url": SITE + path, "name": title, "description": desc,
              "isPartOf": {"@id": SITE + "#website"}, "mainEntity": {"@id": SITE + path + "#dataset"}}, dataset_ld]
    return path, page(path, title, desc, body, graph, [("fairfax", ""), ("Availability tables", path)])


# ---------------------------------------------------------------- endpoints page
def endpoints_page(ds) -> tuple[str, str]:
    path = "endpoints/"

    def hosts(e, key):
        if key not in e.hosts:
            return "<td>–</td>"
        first, *rest = e.hosts[key]
        more = f'<span class="q">also {escape(", ".join(rest))}</span>' if rest else ""
        return f"<td><code>{escape(first)}</code>{more}</td>"

    def table(items, keys, labels):
        rows = "".join(f'<tr id="{anchor(e.id)}"><td>{escape(e.service)}</td>{"".join(hosts(e, k) for k in keys)}'
                       f'<td class="src">{cite(e.source, e.url)}</td></tr>'
                       for e in items)
        head = "".join(f"<th>{escape(x)}</th>" for x in labels)
        return f'<div class="t"><table><thead><tr><th>Service</th>{head}<th>Source</th></tr></thead><tbody>{rows}</tbody></table></div>'

    ident = [e for e in ds.endpoints if e.plane == "identity"]
    m365 = [e for e in ds.endpoints if e.plane == "m365"]
    azure = [e for e in ds.endpoints if e.plane == "azure"]
    rule = {r.id: r for r in ds.rules}
    title = "Azure Government & GCC High endpoints (commercial to gov hosts)"
    desc = (f"The {len(ds.endpoints)} commercial-to-government host mappings fairfax uses: Entra ID sign-in, "
            "Microsoft Graph, Power Platform, Power BI and Azure services, each cited.")
    body = f"""<h1>Azure Government and GCC High endpoints</h1>
<p class="lead">Code copied from commercial samples calls commercial hosts such as <code>login.microsoftonline.com</code>
and <code>graph.microsoft.com</code>. These are the {len(ds.endpoints)} mappings from Microsoft's endpoint tables that
<code>fairfax scan</code> uses to find them and name the right host for your clouds.</p>
<h2>Which sign-in cloud your tenant uses</h2>
<ul><li>{md_code(rule["pairing.gcc-commercial-entra"].says)}</li>
<li>{md_code(rule["pairing.gcchigh-gov-entra"].says)}</li></ul>
<p>So a GCC tenant keeps the worldwide Entra ID and Graph hosts, while its Power Platform and Power BI hosts are
government ones. If the same project also has an Azure Government subscription, a sign-in host can be right for one
call and wrong for the next, which is why <code>fairfax scan</code> marks those lines CHECK.</p>
<h2>Microsoft Entra ID and the Azure portal</h2>
{table(ident, ("commercial", "government"), ("Commercial", "Azure Government"))}
<h2>Microsoft 365, Power Platform and Power BI by tenant</h2>
{table(m365, ("commercial", "gcc", "gcchigh", "dod"), ("Commercial", "GCC", "GCC High", "DoD"))}
<h2>Azure services: commercial and Azure Government</h2>
{table(azure, ("commercial", "government"), ("Commercial", "Azure Government"))}
<h2>Scan your code</h2>
<pre><code>pip install fairfax
fairfax scan src/ --tenant gcchigh --azure government</code></pre>
<p>It exits 1 on a wrong-cloud host, so it works as a CI gate. Add <code>fairfax: ignore</code> in a comment to skip a
line.</p>"""
    srcs = {e.source.key: e.source for e in ds.endpoints}.values()
    graph = [{"@type": "WebPage", "@id": SITE + path, "url": SITE + path, "name": title, "description": desc,
              "isPartOf": {"@id": SITE + "#website"}, "author": AUTHOR,
              "dateModified": max(s.checked for s in srcs),
              "citation": [{"@type": "CreativeWork", "name": s.title, "url": s.url} for s in srcs]}]
    return path, page(path, title, desc, body, graph, [("fairfax", ""), ("Endpoints", path)])


# ---------------------------------------------------------------- sign-in error pages
def _title(*options: str) -> str:
    return next((t for t in options if len(t) <= 65), options[-1])


def _short(text: str, limit: int = 155) -> str:
    return text if len(text) <= limit else text[:limit - 1].rsplit(" ", 1)[0].rstrip(",:;") + "…"


def sign_in_table(ds) -> str:
    e = next(x for x in ds.endpoints if x.id == "endpoint.login-microsoftonline-com")
    return (f'<div class="t"><table><thead><tr><th>Your tenant or subscription</th><th>Sign-in host</th></tr></thead>'
            f'<tbody><tr><td>Commercial Microsoft 365 and Azure, and GCC tenants</td>'
            f'<td><code>{e.hosts["commercial"][0]}</code></td></tr>'
            f'<tr><td>GCC High and DoD tenants, and Azure Government</td><td><code>{e.hosts["government"][0]}</code>'
            f'</td></tr></tbody></table></div>')


def error_pages(ds) -> list:
    errors = sorted(ds.errors, key=lambda e: int(e.code[6:]))
    out = []
    for e in errors:
        path = f"errors/{e.code.lower()}/"
        title = _title(f"{e.code} {e.name}: cause and fix", f"{e.code}: {e.name}",
                       f"{e.code}: cross-cloud sign-in error, cause and fix")
        also = "".join(f'<li>“{escape(q.quote)}” (<a href="{escape(q.url)}">{escape(q.source.title)}</a>)</li>'
                       for q in e.also)
        caveat = ("" if e.confidence == "high" else
                  "<p><strong>Note:</strong> Microsoft's row for this code doesn't mention clouds. The cause above is "
                  "the common one in US government setups, so check it against yours.</p>")
        others = "".join(f'<li><a href="{SITE}errors/{x.code.lower()}/">{x.code}</a>: {escape(x.name)}</li>'
                         for x in errors if x is not e)
        body = f"""<h1>{escape(e.code)}: {escape(e.name)}</h1>
<p class="lead">{escape(e.says)}</p>
<h2>How to fix it</h2>
<p>{escape(e.fix)}</p>
{sign_in_table(ds)}
{caveat}
<h2>What Microsoft says</h2>
<p>“{escape(e.row)}”</p>
<p class="dates">Source: <a href="{escape(e.url)}">{escape(e.source.title)}</a>, page updated {e.source.page_updated},
checked {e.source.checked}.</p>
{f"<ul>{also}</ul>" if also else ""}
<h2>Decode it from the command line</h2>
<pre><code>pip install fairfax
fairfax explain {e.code} --tenant gcchigh      # or paste the whole error message</code></pre>
<p>To find the commercial sign-in host in your code before it fails, run
<code>fairfax scan src/ --tenant gcchigh --azure government</code>.</p>
<h2>Other cross-cloud sign-in errors</h2>
<ul>{others}</ul>"""
        graph = [{"@type": "TechArticle", "@id": SITE + path, "url": SITE + path, "headline": title,
                  "description": _short(e.says), "inLanguage": "en", "author": AUTHOR,
                  "dateModified": e.source.checked, "isPartOf": {"@id": SITE + "#website"},
                  "about": {"@type": "Thing", "name": f"{e.code} {e.name}"},
                  "citation": [{"@type": "CreativeWork", "name": s.title, "url": s.url}
                               for s in {e.source.key: e.source, **{q.source.key: q.source for q in e.also}}.values()]}]
        crumbs = [("fairfax", ""), ("Sign-in errors", "errors/"), (e.code, path)]
        out.append((path, page(path, title, _short(e.says), body, graph, crumbs)))

    path = "errors/"
    rows = "".join(f'<tr><td><a href="{SITE}errors/{e.code.lower()}/">{e.code}</a></td><td>{escape(e.name)}</td>'
                   f"<td>{escape(e.says.split('. ')[0].rstrip('.'))}.</td></tr>" for e in errors)
    title = "AADSTS sign-in errors from mixing Microsoft clouds: fixes"
    desc = (f"{len(errors)} Microsoft Entra sign-in errors that GCC High, DoD and Azure Government apps hit when they "
            "mix clouds, such as AADSTS900439, with Microsoft's wording and the fix.")
    body = f"""<h1>Sign-in errors from mixing Microsoft clouds</h1>
<p class="lead">An app built for commercial Microsoft 365 or Azure signs users in through
<code>login.microsoftonline.com</code>. GCC High, DoD and Azure Government tenants sign in through
<code>login.microsoftonline.us</code>, and the clouds don't federate, so a mixed-up host or app registration fails
with one of these errors. Each page quotes Microsoft and says what to change.</p>
<div class="t"><table><thead><tr><th>Code</th><th>Name</th><th>What it means</th></tr></thead>
<tbody>{rows}</tbody></table></div>
{sign_in_table(ds)}
<pre><code>fairfax explain "AADSTS900439: ..."   # paste the whole message; add --tenant gcchigh for the right host</code></pre>"""
    graph = [{"@type": "CollectionPage", "@id": SITE + path, "url": SITE + path, "name": title, "description": desc,
              "isPartOf": {"@id": SITE + "#website"}, "author": AUTHOR,
              "hasPart": [{"@id": SITE + f"errors/{e.code.lower()}/"} for e in errors]}]
    out.insert(0, (path, page(path, title, desc, body, graph, [("fairfax", ""), ("Sign-in errors", path)])))
    return out


# ---------------------------------------------------------------- landing page
def faq(ds) -> list[tuple[str, str]]:
    power = [f for f in ds.facts if f.source.key == "bap"]
    copilot = [f for f in ds.facts if f.feature.startswith("m365-copilot/")]
    missing = {t: [f.name.split(": ", 1)[1] for f in copilot if status(f.status.get(t, "available"))[1] == "no"]
               for t in ("gcchigh", "dod")}
    e439 = next(e for e in ds.errors if e.code == "AADSTS900439")
    conn = [f for f in ds.facts if f.by == "tenant+azure"]
    blocked_gcc_gov = sum(1 for f in conn if f.status.get("gcc+government") == "not-possible")
    models = [f.feature.split("/", 1)[1] for f in ds.facts
              if f.feature.startswith("azure-openai/") and status(f.status.get("government", "not-available"))[1] == "ok"]
    aoai = next(s for s in ds.sources.values() if s.key == "aoai-gov")
    ep = {e.service: e.hosts for e in ds.endpoints}
    entra, graph = ep["Microsoft Entra ID sign-in"], ep["Microsoft Graph"]
    learn = sum(1 for s in ds.sources.values() if "learn.microsoft.com" in s.url)
    checked = sorted({s.checked for s in ds.sources.values()})
    when = f"on {checked[0]}" if len(checked) == 1 else f"between {checked[0]} and {checked[-1]}"
    in_all = "all" if blocked_gcc_gov == len(conn) else f"{blocked_gcc_gov} of the"
    return [
        ("How do I check whether a Microsoft feature is available in GCC High or Azure Government?",
         f"Microsoft publishes availability per cloud across many pages: fairfax cites {learn} Microsoft Learn pages, "
         f"a PDF and the Microsoft 365 roadmap, and collects {len(ds.features())} features from them. Run "
         "`pip install fairfax`, then `fairfax facts --grep <name>` to see a feature's status in each cloud, or "
         "browse the availability tables on this site. Each row links to the Microsoft page it came from."),
        ("Is Microsoft 365 Copilot available in GCC High and DoD?",
         f"Yes, with gaps. Microsoft's Copilot service description lists {len(copilot)} features by cloud. Not "
         f"available today in GCC High: {', '.join(missing['gcchigh'])}. Not available in DoD: "
         f"{', '.join(missing['dod'])}. The Microsoft 365 Copilot table on this site quotes each row."),
        ("What does AADSTS900439 USGClientNotSupportedOnPublicEndpoint mean?",
         f"{e439.says} {e439.fix} `fairfax explain` decodes it and {len(ds.errors) - 1} other cross-cloud sign-in "
         "errors from the code or the whole message."),
        ("What is the difference between GCC, GCC High and DoD?",
         "They are separate US government clouds for Microsoft 365, and they differ in where users sign in and in "
         f"which features exist. GCC signs users in through commercial Entra ID (`{entra['commercial'][0]}`), while "
         f"GCC High and DoD sign in through Azure Government (`{entra['government'][0]}`). GCC support runs on "
         "worldwide terms, with no assurances about where support agents are or what citizenship they hold. Of the "
         f"{len(power)} Power Platform features fairfax tracks, {unavailable(power, 'gcc')} are not available today "
         f"in GCC, {unavailable(power, 'gcchigh')} in GCC High and {unavailable(power, 'dod')} in DoD."),
        ("Can a GCC tenant send data to Microsoft Sentinel in Azure Government?",
         "Not through the Microsoft 365 data connectors. Microsoft marks a GCC tenant with a Sentinel workspace in "
         f"Azure Government as not possible for {in_all} {len(conn)} connectors fairfax tracks, because a GCC "
         "tenant's data lives in commercial Azure. A GCC tenant connects to a workspace in commercial Azure; GCC High "
         "and DoD tenants connect to a workspace in Azure Government."),
        ("Which Azure OpenAI models are available in Azure Government?",
         f"Microsoft's page of Foundry Models sold by Azure in Azure Government (updated {aoai.page_updated}) lists "
         f"{', '.join(models)}. Deployment types differ by model and region, and the Azure OpenAI table on this site "
         "lists them for each model."),
        ("Which endpoints does GCC High use instead of login.microsoftonline.com and graph.microsoft.com?",
         f"GCC High uses `{entra['government'][0]}` for Entra ID sign-in and `{graph['gcchigh'][0]}` for Microsoft "
         f"Graph. DoD uses `{graph['dod'][0]}` for Graph. A GCC tenant keeps `{entra['commercial'][0]}` and "
         f"`{graph['gcc'][0]}`. The endpoints page lists all {len(ds.endpoints)} mappings, and `fairfax scan` finds "
         "commercial hosts in your code."),
        ("Does fairfax need access to my tenant or Azure subscription?",
         "No. It reads a plan file and your source code on your own machine and never connects to Microsoft 365 or "
         "Azure. The data ships inside the package."),
        ("How current is the data?",
         "Every entry stores the Microsoft page's own updated date and the date fairfax last checked it. All "
         f"{len(ds.sources)} cited pages were checked {when}. Every week `fairfax verify` re-reads each page and "
         "confirms that every cited row is still there word for word; when Microsoft changes one, an issue opens "
         "with the old and new text."),
        ("What if Microsoft deletes or moves a page fairfax cites?",
         "fairfax keeps working: every row is stored word for word inside the package, with its page and dates. "
         f"{sum(1 for s in ds.sources.values() if s.archived)} of the {len(ds.sources)} cited pages also have a "
         "Wayback Machine snapshot that was checked to contain the same rows, and every finding links to it. If a "
         "page returns 404 or 410, the weekly `fairfax verify` fails and opens an issue that points to the snapshot. "
         "`fairfax verify --archived` re-checks every cited row against the snapshots."),
        ("Can AI coding assistants use fairfax?",
         "Yes. `fairfax mcp` runs a Model Context Protocol server with four read-only tools: find feature keys, "
         "check a plan, scan code for wrong-cloud hosts and explain sign-in errors. Add it to Claude Code with "
         "`claude mcp add fairfax -- fairfax mcp`, or to any MCP client as the command `fairfax mcp`."),
        ("Is fairfax made by Microsoft, and is it compliance advice?",
         "No to both. fairfax is an independent open source project under the MIT license. It tells you whether "
         "Microsoft offers a feature in a cloud, quoting Microsoft's own rows. It doesn't tell you whether your use of "
         "a feature meets FedRAMP, ITAR or CMMC."),
    ]


def example(ds) -> str:
    """The README's example, run for real: header, the first blocked finding in full, the rest by key."""
    report = check(ds, load_plan(ROOT / "examples" / "field-inspections" / "plan.yaml"), TODAY)
    blocks = check_text(report).rstrip("\n").split("\n\n")
    blocked = [b for b in blocks[2:] if b.startswith("  ") and not b.startswith("  ok")][:len(report.groups()["blocked"])]
    lines = ["$ fairfax check examples/field-inspections/plan.yaml", blocks[0], "", blocks[1], "", blocked[0]]
    lines += [b.splitlines()[0] for b in blocked[1:]]
    lines += ["  ...", "", blocks[-1].splitlines()[-1]]
    return escape("\n".join(lines))


def m365_example(ds) -> str:
    """The Microsoft 365 example, run for real: the summary line and one blocked finding with its roadmap note."""
    report = check(ds, load_plan(ROOT / "examples" / "m365-rollout" / "plan.yaml"), TODAY)
    blocks = check_text(report).rstrip("\n").split("\n\n")
    with_roadmap = next(b for b in blocks if "Microsoft 365 roadmap" in b and b.startswith("  "))
    lines = ["$ fairfax check examples/m365-rollout/plan.yaml", blocks[0], "", blocks[1], "", with_roadmap,
             "  ...", "", blocks[-1].splitlines()[-1]]
    return escape("\n".join(lines))


def explain_example(ds) -> str:
    from fairfax import explain as explain_mod
    from fairfax.render import explain_text
    text = explain_text(explain_mod.explain(ds, "AADSTS900439", "gcchigh", None), ds)
    head = text.split("\n    source:")[0].rstrip()
    return escape("$ fairfax explain AADSTS900439 --tenant gcchigh\n" + head)


def landing_page(ds) -> tuple[str, str]:
    questions = faq(ds)
    features = len(ds.features())
    services = "".join(
        f'<li><a href="{SITE}availability/{s["slug"]}/">{escape(s["h1"])}</a>: '
        f'{len({f.feature for f in facts_for(ds, s["prefixes"])})} features</li>' for s in SERVICES)
    title = "GCC High & Azure Government feature availability checker · fairfax"
    desc = ("Open source checker: is a feature available in GCC, GCC High, DoD or Azure Government? "
            f"{features} features from Microsoft's own tables, every finding cited.")
    body = f"""<img src="header.svg" alt="fairfax: check a GCC, GCC High or Azure Government plan before you build it. Every finding cites the Microsoft row it came from." width="980" height="278">
<h1>Check a Microsoft gov-cloud plan before you build it</h1>
<p class="lead">fairfax is an open source command-line tool and dataset for Microsoft's US government clouds. Give it
your tenant type (GCC, GCC High or DoD), your Azure cloud and the features you plan to use, from Azure and Power
Platform to Microsoft 365 Copilot, Teams, Purview and Intune. It tells you what Microsoft doesn't offer there, what
can't cross between the clouds and what is retiring, and quotes the Microsoft row behind each answer.</p>
<a class="cta" href="{REPO}">View on GitHub</a>
<a class="cta alt" href="{SITE}availability/">Browse the availability tables</a>
<a class="cta alt" href="{PYPI}">pip install fairfax</a>

<h2>The problem</h2>
<p>Microsoft's US government clouds are not copies of commercial Microsoft 365 and Azure. GCC, GCC High, DoD and Azure
Government each lack features that commercial has, and some pairings of them can't talk to each other at all.
Microsoft does publish the gaps, spread across more than a dozen Learn pages and a PDF it republishes every few weeks.
Most teams find them halfway through a build, when a connector never shows up or a sign-in fails with a wrong-cloud
error.</p>

<h2>What it catches</h2>
<p>The repository ships a made-up example: a state agency's field inspection app on GCC High and Azure Government.</p>
<pre><code>{example(ds)}</code></pre>
<p><code>fairfax check</code> exits 1 when anything is blocked and <code>fairfax scan</code> exits 1 on a wrong-cloud
endpoint, so both work as CI gates.</p>

<h2>Microsoft 365, with Microsoft's roadmap</h2>
<p>Microsoft 365 Copilot, Teams, Exchange Online, SharePoint, OneDrive, Purview, Intune and Defender are covered
too. When a feature is missing and Microsoft's public roadmap has an item for it, the finding shows the item and its
target month, and says so when that month has passed.</p>
<pre><code>{m365_example(ds)}</code></pre>

<h2>Sign-in errors, decoded</h2>
<p>When a commercial sign-in host meets a GCC High or Azure Government tenant, the error is a code like
AADSTS900439. <code>fairfax explain</code> takes the code or the whole message and answers with Microsoft's wording,
the cause and the right host for your clouds. The <a href="{SITE}errors/">sign-in errors pages</a> cover all
{len(ds.errors)}.</p>
<pre><code>{explain_example(ds)}</code></pre>

<h2>In CI, and for AI coding tools</h2>
<p>The <a href="https://github.com/marketplace/actions/fairfax-gov-cloud-check">GitHub Action</a>, listed on the
GitHub Marketplace, runs <code>check</code> and <code>scan</code>, writes the report to the job summary, marks each
finding on its line in the pull request, and can upload SARIF to code scanning:</p>
<pre><code>- uses: intikhab49/fairfax@v{__version__}
  with:
    plan: plan.yaml        # optional
    scan: src</code></pre>
<p><code>fairfax mcp</code> runs a Model Context Protocol server, so Claude Code, VS Code, Cursor and other agents
can check a plan, scan code and decode errors with citations instead of guessing:</p>
<pre><code>claude mcp add fairfax -- fairfax mcp</code></pre>

<h2>Availability tables</h2>
<p>The same dataset, as tables with Microsoft's row, the page link and the dates for every entry:</p>
<ul>{services}
<li><a href="{SITE}endpoints/">Azure Government and GCC High endpoints</a>: {len(ds.endpoints)} host mappings</li></ul>

<h2>Quick start</h2>
<pre><code>pip install fairfax

fairfax facts --grep copilot                       # feature keys and their status per cloud
fairfax check plan.yaml                            # text report; --format md, json or sarif
fairfax scan src/ --tenant gcchigh --azure government
fairfax explain AADSTS900439 --tenant gcchigh      # decode a cross-cloud sign-in error
fairfax verify                                     # re-read Microsoft's pages, confirm every cited row
fairfax verify --archived                          # same check against the Wayback Machine copies
fairfax mcp                                        # MCP server for coding agents</code></pre>
<p>Python 3.10 or newer, MIT licensed, one dependency (PyYAML). A plan is a short YAML file:</p>
<pre><code>name: Field inspection app
tenant: gcchigh        # gcc | gcchigh | dod
azure: government      # commercial | government
features:
  - power-automate/actionable-approval-emails
  - sentinel/connector/teams
  - azure-openai/gpt-4o</code></pre>

<h2>How the data stays honest</h2>
<ul><li>Every entry stores the Microsoft page, the section anchor and the row exactly as Microsoft wrote it.</li>
<li>Statuses were parsed from those rows by a script, not retyped, and the tests re-parse them on every run.</li>
<li>Each entry carries the page's own updated date and the date fairfax last checked it.</li>
<li><code>fairfax verify</code> re-reads all {len(ds.sources)} pages and confirms every cited row is still there; a
weekly workflow runs it and opens an issue when Microsoft changes or removes one.</li>
<li>Each cited page has a Wayback Machine snapshot that was checked to hold the cited rows, so a citation outlives its
page.</li>
<li>Where Microsoft's tables don't answer a question, fairfax says so instead of guessing.</li></ul>

<h2>FAQ</h2>
{"".join(f"<h3>{escape(q)}</h3><p>{md_code(a)}</p>" for q, a in questions)}"""
    graph = [
        {"@type": "WebSite", "@id": SITE + "#website", "url": SITE, "name": "fairfax", "inLanguage": "en",
         "publisher": AUTHOR},
        {"@type": "SoftwareApplication", "@id": SITE + "#app", "name": "fairfax",
         "description": ("Open source command-line checker for Microsoft's US government clouds. Checks a planned "
                         "stack (GCC, GCC High or DoD tenant, commercial or Azure Government subscription, a list "
                         "of Azure, Power Platform and Microsoft 365 features) against Microsoft's own availability "
                         "tables and cites the row behind each finding. Also scans code for endpoints from the "
                         "wrong cloud, decodes cross-cloud AADSTS sign-in errors, runs as a GitHub Action with SARIF "
                         "and as an MCP server for coding agents."),
         "applicationCategory": "DeveloperApplication", "applicationSubCategory": "Cloud compliance checker",
         "operatingSystem": "Windows, macOS, Linux (Python 3.10+)", "softwareVersion": __version__,
         "license": "https://opensource.org/licenses/MIT", "isAccessibleForFree": True,
         "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
         "url": SITE, "downloadUrl": PYPI, "installUrl": PYPI, "sameAs": [REPO, PYPI],
         "keywords": "GCC High, GCC, DoD, Azure Government, Microsoft 365 government, feature availability, "
                     "cloud parity, Microsoft 365 Copilot, Teams, Purview, Intune, Microsoft Sentinel, "
                     "Defender for Cloud, Power Platform, Azure OpenAI, AADSTS900439, MCP server, GitHub Action",
         "author": AUTHOR},
        {"@type": "SoftwareSourceCode", "@id": REPO, "name": "fairfax", "codeRepository": REPO,
         "programmingLanguage": "Python", "license": "https://opensource.org/licenses/MIT",
         "targetProduct": {"@id": SITE + "#app"}, "author": AUTHOR},
        {"@type": "FAQPage", "@id": SITE + "#faq", "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a.replace("`", "")}}
            for q, a in questions]},
    ]
    return "", page("", title, desc, body, graph)


# ---------------------------------------------------------------- llms.txt, sitemap
def llms(ds, pages) -> tuple[str, str]:
    lines = ["# fairfax", "",
             f"> Open source CLI and cited dataset that checks a Microsoft US government cloud plan (GCC, GCC High, "
             f"DoD, Azure Government) against Microsoft's own feature availability tables. {len(ds.features())} "
             f"features across Azure, Power Platform and Microsoft 365, {len(ds.rules)} cross-cloud rules, "
             f"{len(ds.endpoints)} endpoint mappings and {len(ds.errors)} cross-cloud sign-in errors; every entry quotes "
             "the Microsoft row it came from and carries the page's updated date and the date it was last checked.", "",
             f"- Install: `pip install fairfax` (Python 3.10+, MIT, one dependency: PyYAML). Version {__version__}.",
             "- `fairfax check plan.yaml`: findings grouped as blocked, cross-cloud, retiring, notes and ok, with "
             "Microsoft 365 roadmap items on blocked features; exits 1 when anything is blocked. Text, Markdown, JSON "
             "or SARIF.",
             "- `fairfax scan <path> --tenant gcchigh --azure government`: finds commercial hosts in code "
             "(login.microsoftonline.com, graph.microsoft.com, *.vault.azure.net, api.security.microsoft.com) and "
             "names the government host.",
             "- `fairfax explain AADSTS900439 --tenant gcchigh`: decodes a cross-cloud sign-in error from the code or "
             "the whole message: Microsoft's wording, the cause and the right sign-in host.",
             "- `fairfax facts --grep <text>`: feature keys and their status per cloud. `--format json` for data.",
             "- `fairfax verify`: re-reads every cited Microsoft page and confirms each cited row is still there. "
             "`--archived` runs the same check against the Wayback Machine snapshot recorded for each page.",
             "- `fairfax mcp`: Model Context Protocol server (stdio) with find_features, check_plan, scan_code and "
             "explain_error tools. `claude mcp add fairfax -- fairfax mcp`.",
             "- GitHub Action: `uses: intikhab49/fairfax@v" + __version__ + "` with `plan` and `scan` inputs; job "
             "summary, line annotations, optional SARIF upload to code scanning. Marketplace listing: "
             "https://github.com/marketplace/actions/fairfax-gov-cloud-check",
             "- It works offline (except verify). It never connects to a tenant or subscription, and it is not "
             "compliance advice.",
             "- Independent project by Intikhab Azam, not affiliated with Microsoft.", "",
             "## Availability tables", ""]
    for svc in SERVICES:
        lines.append(f"- [{svc['h1']}]({SITE}availability/{svc['slug']}/): "
                     f"{svc['desc'].format(n=len({f.feature for f in facts_for(ds, svc['prefixes'])}))}")
    lines += [f"- [Overview and sources]({SITE}availability/): every service, every cited Microsoft page, download links",
              f"- [Endpoints]({SITE}endpoints/): {len(ds.endpoints)} commercial-to-government host mappings", "",
              "## Sign-in errors", ""]
    lines += [f"- [{e.code} {e.name}]({SITE}errors/{e.code.lower()}/): {_short(e.says, 140)}"
              for e in sorted(ds.errors, key=lambda e: int(e.code[6:]))]
    lines += ["",
              "## Docs", "",
              f"- [README]({REPO}#readme): usage, plan format, how the dataset is built, limits, roadmap",
              f"- [PyPI]({PYPI}): package page",
              f"- [Dataset (YAML)]({REPO}/tree/main/src/fairfax/data): the facts, rules and endpoints", ""]
    short_txt = "\n".join(lines + ["## Optional", "",
                                   f"- [llms-full.txt]({SITE}llms-full.txt): every fact, rule and endpoint as plain text",
                                   ""])

    full = ["\n".join(lines).rstrip("\n"), "",
            f"# Full dataset (pages checked {min(s.checked for s in ds.sources.values())})", ""]
    for svc in SERVICES:
        full += [f"## {svc['h1']}", ""]
        for key, (items, merged) in by_feature(facts_for(ds, svc["prefixes"])).items():
            f = items[0]
            states = "; ".join(f"{(TENANT.get(k) or CLOUD.get(k) or PAIRING.get(k))}: {status(v)[0]}"
                               for k, v in merged.items())
            notes = list(dict.fromkeys(i.note for i in items if i.note))
            extra = "".join(f" {x}" for x in (*notes, f"Retires {f.retires}." if f.retires else None, f.instead) if x)
            if len(items) == 1:
                cites = (f"Source: {f.source.title}, page updated {f.source.page_updated}: {f.url} . "
                         f"Microsoft's row: {f.row}")
            else:  # one row per cloud page; the pages are listed under Sources at the end
                cites = "Microsoft's rows: " + "; ".join(f"{i.row} [{i.source.key}]" for i in items)
            full.append(f"- {f.name} (`{key}`). {states}.{extra} {cites}")
        full.append("")
    full += ["## Cross-cloud rules", ""]
    full += [f"- {r.title}: {r.says} Source: {r.url} ({r.confidence})" for r in ds.rules]
    full += ["", "## Endpoints (commercial to government)", ""]
    for e in ds.endpoints:
        hosts = "; ".join(f"{TENANT.get(k) or CLOUD.get(k) or k}: {', '.join(v)}" for k, v in e.hosts.items())
        full.append(f"- {e.service}: {hosts}. Source: {e.url}")
    full += ["", "## Cross-cloud sign-in errors", ""]
    for e in sorted(ds.errors, key=lambda e: int(e.code[6:])):
        full.append(f"- {e.code} {e.name}: {e.says} Fix: {e.fix} Microsoft: \"{e.row}\" Source: {e.url} "
                    f"({e.confidence})")
    full += ["", "## Microsoft 365 roadmap items linked to missing features", ""]
    for r in ds.roadmap:
        full.append(f"- {', '.join(r.features)}: roadmap {r.id} \"{r.title}\", {r.status} for {', '.join(r.clouds)}, "
                    f"target {r.ga}. {r.url}")
    full += ["", "## Sources", ""]
    full += [f"- [{s.key}] {s.title}: {s.url} (page updated {s.page_updated}, checked {s.checked})"
             for s in sorted(ds.sources.values(), key=lambda s: s.key)]
    return short_txt, "\n".join(full) + "\n"


def sitemap(paths) -> str:
    urls = "".join(f"  <url><loc>{SITE + p}</loc><lastmod>{TODAY.isoformat()}</lastmod></url>\n" for p in paths)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{urls}</urlset>\n")


def main() -> None:
    ds = dataset.load()
    pages = [landing_page(ds), overview_page(ds), *(service_page(ds, s) for s in SERVICES), endpoints_page(ds),
             *error_pages(ds)]
    for path, html in pages:
        out = DOCS / path / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8", newline="\n")
    short_txt, full_txt = llms(ds, pages)
    (DOCS / "llms.txt").write_text(short_txt, encoding="utf-8", newline="\n")
    (DOCS / "llms-full.txt").write_text(full_txt, encoding="utf-8", newline="\n")
    (DOCS / "sitemap.xml").write_text(sitemap([p for p, _ in pages]), encoding="utf-8", newline="\n")
    (DOCS / "favicon.svg").write_text(FAVICON, encoding="utf-8", newline="\n")
    print(f"wrote {len(pages)} pages, llms.txt, llms-full.txt ({len(full_txt)} chars), sitemap.xml, favicon.svg")


if __name__ == "__main__":
    main()
