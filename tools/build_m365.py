"""Builder for the 0.2.0 additions: Microsoft 365 availability, Defender API hosts and sign-in errors.

It reads saved Learn pages with the same reader `fairfax verify` uses, so every row it writes is
exactly what verify later looks for on the live page. Statuses are parsed from the row text, and any
row, quote or footnote that can't be found is a hard error: nothing in the output is retyped.

Usage:
  curl -sL -o <pages_dir>/<key>.html <url>     (once per page in URLS)
  python tools/build_m365.py <pages_dir> <out_dir>
Like tools/build_facts.py, re-running it overwrites any hand edits to the files it writes.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fairfax.learn import cells, parse  # noqa: E402

CHECKED = "2026-10-12"
PAGES_DIR, OUT = Path(sys.argv[1]), Path(sys.argv[2])
SD = "https://learn.microsoft.com/en-us/office365/servicedescriptions"
USGOV = f"{SD}/office-365-platform-service-description/office-365-us-government"
PURVIEW = f"{SD}/microsoft-365-service-descriptions/microsoft-365-tenantlevel-services-licensing-guidance"

URLS = {
    "copilot-sd": f"{SD}/office-365-platform-service-description/microsoft-365-copilot",
    "teams-sd": f"{SD}/teams-service-description",
    "teams-apps": "https://learn.microsoft.com/en-us/microsoftteams/platform/concepts/cloud-overview",
    "exo-gov": f"{USGOV}/exchange-online-for-us-government-environments",
    "spo-gov": f"{USGOV}/sharepoint",
    "odb-gov": f"{USGOV}/onedrive",
    "purview-gcc": f"{PURVIEW}/plan-for-microsoft-purview-gcc-deployments",
    "purview-gcchigh": f"{PURVIEW}/plan-for-microsoft-purview-gcc-high-deployments",
    "purview-dod": f"{PURVIEW}/plan-for-microsoft-purview-dod-deployments",
    "intune-gov": "https://learn.microsoft.com/en-us/intune/fundamentals/government-service",
    "mde-gov": "https://learn.microsoft.com/en-us/defender-endpoint/gov",
    "xdr-gov": "https://learn.microsoft.com/en-us/defender-xdr/usgov",
    "xdr-apis": "https://learn.microsoft.com/en-us/defender-xdr/api-supported",
    "mde-apis": "https://learn.microsoft.com/en-us/defender-endpoint/api/exposed-apis-list",
    "entra-errors": "https://learn.microsoft.com/en-us/entra/identity-platform/reference-error-codes",
    "entra-breaking": "https://learn.microsoft.com/en-us/entra/identity-platform/reference-breaking-changes",
    "entra-national": "https://learn.microsoft.com/en-us/entra/identity-platform/authentication-national-cloud",
}
# Where a page's own heading is too vague to name it in a finding.
TITLES = {"copilot-sd": "Microsoft Copilot service description", "teams-apps": "Teams for Government Clouds"}
PAGES = {k: parse((PAGES_DIR / f"{k}.html").read_text(encoding="utf-8"), u) for k, u in URLS.items()}
SOURCES = {k: {"title": TITLES.get(k, p.title), "url": URLS[k], "page_updated": p.updated, "checked": CHECKED}
           for k, p in PAGES.items()}
TENANTS = ("gcc", "gcchigh", "dod")


def fail(msg):
    sys.exit(f"build_m365: {msg}")


def rows(key, section):
    out = PAGES[key].section_rows(section)
    if not out:
        fail(f"{key}#{section}: no table rows")
    return out


def quote(key, section, needle):
    if not PAGES[key].find_quote(section, needle):
        fail(f"{key}#{section}: quote not found: {needle!r}")
    return needle


def footnotes(key, section):
    """{number: text} from the numbered note block under a table (' / ' separates the notes)."""
    notes = {}
    for s, t in PAGES[key].text:
        if s == section and re.match(r"^\d+ ?\S", t):
            for chunk in re.split(r" / (?=\d+ ?[A-Z])", t.rstrip(" /")):
                m = re.match(r"^(\d+) ?(\S.*)$", chunk)
                if m:
                    notes[m.group(1)] = m.group(2).strip()
    return notes


def slug(text, limit=60):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(s) > limit:
        s = s[:limit].rsplit("-", 1)[0]
    return s


def unique(items):
    seen = set()
    for d in items:
        if d["id"] in seen:
            fail(f"duplicate id {d['id']}")
        seen.add(d["id"])
    return items


# ---------------------------------------------------------------- Microsoft 365 Copilot (by tenant)
COPILOT = [  # first cell as Microsoft writes it, slug
    ("Web data, referenced files, uploaded files, referenced files, uploaded files", "web-and-file-grounding"),
    ("Work data and organizational context2", "work-data-grounding"),
    ("Chat", "chat"),
    ("Copilot Search3", "search"),
    ("Copilot Notebooks2", "notebooks"),
    ("Pages", "pages"),
    ("Create3", "create"),
    ("Researcher2", "researcher"),
    ("Analyst2", "analyst"),
    ("Word, Excel, and PowerPoint Agents", "word-excel-powerpoint-agents"),
    ("Copilot Prompt Gallery", "prompt-gallery"),
    ("Scheduled Prompts", "scheduled-prompts"),
    ("Copilot in Outlook", "outlook"),
    ("Copilot Chat in Word, Excel, PowerPoint, and OneNote6", "chat-in-office-apps"),
    ("Edit with Copilot in Word, Excel, PowerPoint, and OneNote2", "edit-in-office-apps"),
    ("Copilot in Teams (Chat, Channel, Meetings)", "teams"),
    ("Copilot in SharePoint", "sharepoint"),
    ("SharePoint agents", "sharepoint-agents"),
    ("Declarative agents", "declarative-agents"),
    ("Agent Builder", "agent-builder"),
    ("Microsoft 365 Copilot Connectors", "copilot-connectors"),
    ("Power Platform Connectors10", "power-platform-connectors"),
    ("Enterprise Data Protection (EDP)", "enterprise-data-protection"),
    ("Microsoft Purview controls for Microsoft Copilot & Copilot chat11", "purview-controls"),
    ("Copilot Analytics in Viva Insights", "copilot-analytics"),
]
YES_NO = {"Yes": "available", "No": "not-available", "Not currently available": "not-available"}


def status_cell(text, words, where):
    m = re.fullmatch(r"(.+?)(\d+(?:,\d+)*)?", text)
    word, refs = m.group(1), m.group(2)
    if word not in words:
        fail(f"{where}: unknown status cell {text!r}")
    return words[word], (refs.split(",") if refs else [])


def name_refs(first, notes):
    """Split a trailing footnote number off a first cell ('Researcher2' -> 'Researcher', ['2'])."""
    m = re.fullmatch(r"(.*?[^\d\s])(\d{1,2})", first)
    if m and m.group(2) in notes and not first.endswith("365"):
        return m.group(1), [m.group(2)]
    return first, []


def build_copilot():
    sec, notes = "feature-availability", footnotes("copilot-sd", "feature-availability")
    table = rows("copilot-sd", sec)
    if table[0] != ["Feature", "Commercial/Worldwide", "GCC", "GCCH", "DoD"]:
        fail(f"copilot-sd: header changed: {table[0]}")
    by_first = {c[0]: c for c in table[1:] if any(c[1:])}
    if set(by_first) != {f for f, _ in COPILOT}:
        fail(f"copilot-sd: rows changed: {set(by_first) ^ {f for f, _ in COPILOT}}")
    out = []
    for first, s in COPILOT:
        c = by_first[first]
        name, refs = name_refs(first, notes)
        status = {}
        for tenant, cell in zip(TENANTS, c[2:5]):
            status[tenant], more = status_cell(cell, YES_NO, f"copilot-sd:{first}")
            refs += more
        note = " ".join(notes[r] for r in dict.fromkeys(refs)) or None
        out.append(fact(f"m365-copilot.{s}", f"m365-copilot/{s}", f"Microsoft 365 Copilot: {name}", "tenant", status,
                        "copilot-sd", sec, cells(c), note=note))
    return out


# ---------------------------------------------------------------- Teams (by tenant)
TEAMS = [
    ("Teams Apps", "apps"), ("Audio conferencing", "audio-conferencing"), ("Channels - Standard", "channels-standard"),
    ("Channels - Private", "channels-private"), ("Channels - Shared", "channels-shared"), ("Chat", "chat"),
    ("Meetings", "meetings"), ("Screen sharing PowerPoint Audio/Video Desktop", "screen-sharing"), ("Teams", "teams"),
    ("PTSN calling enablement (via Teams Phone)6", "pstn-calling"), ("Teams events7,8", "events"),
    ("Town halls (Teams events)", "town-halls"), ("Webinars (Teams events)", "webinars"), ("VoIP calling", "voip-calling"),
    ("Loop Integrations", "loop"),
]
TEAMS_NAMES = {"Teams events7,8": ("Teams events", ["7", "8"]), "PTSN calling enablement (via Teams Phone)6":
               ("PSTN calling (via Teams Phone)", ["6"])}
TEAMS_APPS = [
    ("Apps built by Microsoft", "microsoft-apps"), ("Third-party apps", "third-party-apps"),
    ("Custom apps built for your org (LOB apps) distributed and used in specific organization", "custom-apps"),
    ("Upload a custom app", "upload-custom-app"), ("Tabs", "tabs"), ("Bots", "bots"),
    ("Message extensions", "message-extensions"), ("Message actions", "message-actions"),
    ("Cards: Adaptive, Hero, Thumbnail, Microsoft 365 connector, Receipt, Sign in, and OAuth cards", "cards"),
    ("Dialogs (referred as task modules in TeamsJS v1.x)", "dialogs"), ("Link unfurling", "link-unfurling"),
    ("Meeting extensions", "meeting-extensions"), ("Webhooks and connectors", "webhooks-and-connectors"),
    ("Workflows", "workflows"), ("Teams Store", "store"), ("In-context Teams Store or app flyouts", "store-flyouts"),
    ("Manage apps in Teams", "manage-apps-in-teams"), ("Manage apps in Teams Admin Center", "manage-apps-in-admin-center"),
    ("Graph APIs", "graph-apis"), ("Developer Portal for Teams", "developer-portal"),
]
TICKS = {"✔️": "available", "✔": "available", "❌": "not-available"}
TEAMS_APP_NOTES = {
    "third-party-apps": "Third-party apps are turned off by default for GCC and aren't available for GCC High and DoD.",
    "webhooks-and-connectors": "GCC High supports Incoming Webhooks only.",
}


def build_teams():
    sec, notes = "feature-availability", footnotes("teams-sd", "feature-availability")
    table = rows("teams-sd", sec)
    if table[0][3:6] != ["GCC", "GCC - High", "DOD"]:
        fail(f"teams-sd: header changed: {table[0]}")
    by_first = {c[0]: c for c in table[1:]}
    if set(by_first) != {f for f, _ in TEAMS}:
        fail(f"teams-sd: rows changed: {set(by_first) ^ {f for f, _ in TEAMS}}")
    out = []
    for first, s in TEAMS:
        c = by_first[first]
        name, refs = TEAMS_NAMES.get(first, (first, []))
        status = {}
        for tenant, cell in zip(TENANTS, c[3:6]):
            status[tenant], more = status_cell(cell, YES_NO, f"teams-sd:{first}")
            refs = refs + more
        note = " ".join(notes[r] for r in dict.fromkeys(refs)) or None
        out.append(fact(f"teams.{s}", f"teams/{s}", f"Microsoft Teams: {name}", "tenant", status,
                        "teams-sd", sec, cells(c), note=note))

    sec = "teams-app-capabilities"
    table = rows("teams-apps", sec)
    if table[0][1:] != ["GCC", "GCC High", "DoD"]:
        fail(f"teams-apps: header changed: {table[0]}")
    by_first = {c[0]: c for c in table[1:] if any(c[1:])}
    if set(by_first) != {f for f, _ in TEAMS_APPS}:
        fail(f"teams-apps: rows changed: {set(by_first) ^ {f for f, _ in TEAMS_APPS}}")
    for first, s in TEAMS_APPS:
        c = by_first[first]
        status = {}
        for tenant, cell in zip(TENANTS, c[1:4]):
            if cell not in TICKS:
                fail(f"teams-apps:{first}: unknown cell {cell!r}")
            status[tenant] = TICKS[cell]
        note = quote("teams-apps", sec, TEAMS_APP_NOTES[s]) if s in TEAMS_APP_NOTES else None
        out.append(fact(f"teams.apps.{s}", f"teams/apps/{s}", f"Teams apps: {first}", "tenant", status,
                        "teams-apps", sec, cells(c), note=note))
    return out


# ---------------------------------------------------------------- Exchange Online (by tenant)
EXO_SLUGS = {"Office 365 Groups": "microsoft-365-groups", "Outlook on the web1": "outlook-on-the-web",
             "EWS application support2": "ews-application-support"}


def build_exchange():
    sec, notes = "exchange-online-features", footnotes("exo-gov", "exchange-online-features")
    out = []
    for c in rows("exo-gov", sec)[1:]:
        if c[1:4] == ["GCC", "GCC High", "DoD"] or not any(c[1:4]):
            continue  # a group heading
        name, refs = name_refs(c[0], notes)
        s = EXO_SLUGS.get(c[0]) or slug(name)
        status = {}
        for tenant, cell in zip(TENANTS, c[1:4]):
            status[tenant], more = status_cell(cell, YES_NO, f"exo-gov:{c[0]}")
            refs += more
        extra = [notes[r] for r in dict.fromkeys(refs)]
        if len(c) > 4 and c[4]:
            extra.insert(0, c[4])
        out.append(fact(f"exchange.{s}", f"exchange/{s}", f"Exchange Online: {name}", "tenant", status,
                        "exo-gov", sec, cells(c[:4]), note=" ".join(extra) or None))
    if len(out) < 80:
        fail(f"exo-gov: only {len(out)} features")
    return unique(out)


# ---------------------------------------------------------------- SharePoint and OneDrive (by tenant, sentences)
ALL = ("gcc", "gcchigh", "dod")
HIGH = ("gcchigh", "dod")
SPO = [  # page, section, Microsoft's sentence, key, name, clouds it says the feature is missing from
    ("spo-gov", "it-admin-features", "Changing a site address isn't available for GCC High customers.",
     "sharepoint/change-site-address", "Changing a site address", ("gcchigh",)),
    ("spo-gov", "it-admin-features", "Mover.io isn't yet supported.",
     "sharepoint/mover-io", "Mover.io migrations", ALL),
    ("spo-gov", "it-admin-features", "Multi-geo isn't available for government cloud customers.",
     "sharepoint/multi-geo", "Multi-geo", ALL),
    ("spo-gov", "it-admin-features", "The following cards aren't available on the home page of the SharePoint admin "
     "center for GCC High and DoD customers:", "sharepoint/admin-center-usage-cards",
     "Usage and activity cards on the SharePoint admin center home page", HIGH),
    ("spo-gov", "it-admin-features", "Tracked view cards aren't available in the SharePoint admin center for all "
     "government cloud customers.", "sharepoint/tracked-view-cards", "Tracked view cards in the SharePoint admin center",
     ALL),
    ("spo-gov", "sites-and-content", "Organization assets library isn't available",
     "sharepoint/organization-assets-library", "Organization assets library", ALL),
    ("spo-gov", "sites-and-content", "Graph functionality within SharePoint Online for GCC High is currently disabled.",
     "sharepoint/graph-functionality", "Microsoft Graph functionality within SharePoint Online", ("gcchigh",)),
    ("spo-gov", "sites-and-content", "Notifications for file and site activity aren't available",
     "sharepoint/activity-notifications", "Notifications for file and site activity", ALL),
    ("spo-gov", "sites-and-content", "News from selected sites or hub news rollups from associated sites isn't "
     "available for GCC High and DoD customers", "sharepoint/news-rollups",
     "News from selected sites and hub news rollups", HIGH),
    ("odb-gov", "web-features", "File cards are not available in the GCC High and DoD environments",
     "onedrive/file-cards", "File cards", HIGH),
    ("odb-gov", "web-features", 'SharePoint library access ("Shared libraries" in the navigation pane) is not '
     "available in the GCC High and DoD environments", "onedrive/shared-libraries",
     'SharePoint library access ("Shared libraries")', HIGH),
    ("odb-gov", "mobile-features", "The Windows 10 app for XBox One, HoloLens, Surface Hub, and tablets is not "
     "available for the government environments (GCC, GCC High, and DoD).", "onedrive/windows-10-device-app",
     "OneDrive Windows 10 app for Xbox One, HoloLens, Surface Hub and tablets", ALL),
]
SPO_LIMITED = [
    ("spo-gov", "sites-and-content", "Web parts that rely on connections to Internet services, such as the Amazon "
     "Kindle, Bing Maps, Twitter, and YouTube web parts, won't work as expected", "sharepoint/internet-web-parts",
     "Web parts that rely on Internet services (Bing Maps, YouTube and others)", ALL),
]


def build_sharepoint():
    out = []
    for key, sec, sentence, feature, name, clouds in SPO + SPO_LIMITED:
        quote(key, sec, sentence)
        status = {t: "not-available" if (key, sec, sentence, feature, name, clouds) in SPO else "limited"
                  for t in clouds}
        product = "SharePoint" if feature.startswith("sharepoint/") else "OneDrive"
        out.append(fact(feature.replace("/", "."), feature, f"{product}: {name}", "tenant", status, key, sec, sentence))
    return out


# ---------------------------------------------------------------- Purview (by tenant, one page per cloud)
PURVIEW_STATUS = {"Available": "available", "In development": "in-development", "On engineering backlog": "backlog",
                  "Public Preview": "preview", "Rolling out": "rolling-out"}
PURVIEW_AREAS = {  # shorter keys for the long area names
    "Microsoft Purview Data Lifecycle Management (formerly Information Governance)": "data-lifecycle-management",
    "Microsoft Purview Data Security Posture Management for AI": "dspm-for-ai",
}


def purview_area(area):
    short = re.sub(r"^Microsoft Purview ", "", area)
    return PURVIEW_AREAS.get(area) or slug(re.sub(r"\s*\(.*?\)", "", short)), short


def build_purview():
    out, keys = [], {}
    for tenant in TENANTS:
        key = f"purview-{tenant}"
        sec = next(s for s, c in PAGES[key].rows if c and c[0] == "Area")
        notes = footnotes(key, sec)
        table = rows(key, sec)
        area = None
        for c in table[1:]:
            if len(c) != 3:
                fail(f"{key}: unexpected row {c}")
            first, feature, cell = c
            if first and not feature and not cell:
                continue  # a heading such as "Data protection"
            if first:
                area = first
            if not area or not feature:
                fail(f"{key}: row without an area or feature: {c}")
            status, refs = status_cell(cell, PURVIEW_STATUS, f"{key}:{feature}")
            area_slug, area_name = purview_area(area)
            feature_key = f"purview/{area_slug}/{slug(feature)}"
            if (tenant, feature_key) in keys:
                if keys[(tenant, feature_key)] != status:
                    fail(f"{key}: two rows give {feature_key} with different statuses")
                print(f"  {key}: skipped a second row for {feature_key} with the same status: {feature!r}")
                continue
            keys[(tenant, feature_key)] = status
            note = " ".join(notes[r] for r in refs) or None
            out.append(fact(f"{feature_key.replace('/', '.')}.{tenant}", feature_key, f"Purview {area_name}: {feature}",
                            "tenant", {tenant: status}, key, sec, f"{area}: {cells([feature, cell])}", note=note))
    return unique(out)


# ---------------------------------------------------------------- Intune (by tenant: GCC High and DoD)
INTUNE_PLANNED = "intune-features-planned-for-gcc-high-and-dod"
INTUNE_MISSING = "intune-features-not-available-in-gcc-high-and-dod"
INTUNE_SUPPORTED = "supported-intune-features-in-gcc-high-and-dod"
INTUNE_PLANNED_NAMES = {"What is Microsoft Security Copilot?": ("security-copilot", "Security Copilot in Intune")}


def build_intune():
    out = []
    area = None
    for c in rows("intune-gov", INTUNE_PLANNED)[1:]:
        area = c[0] or area
        s, name = INTUNE_PLANNED_NAMES.get(c[1], (slug(c[1]), c[1]))
        out.append(fact(f"intune.{s}", f"intune/{s}", f"Intune: {name}", "tenant",
                        {"gcchigh": "planned", "dod": "planned"}, "intune-gov", INTUNE_PLANNED, f"{area}: {c[1]}",
                        note=f"Listed by Microsoft under \"Intune features planned for GCC High and DoD\" ({area})."))
    for c in rows("intune-gov", INTUNE_MISSING)[1:]:
        if c[1] != "n/a":
            fail(f"intune-gov: unexpected cell {c}")
        s = slug(c[0])
        out.append(fact(f"intune.{s}", f"intune/{s}", f"Intune: {c[0]}", "tenant",
                        {"gcchigh": "not-available", "dod": "not-available"}, "intune-gov", INTUNE_MISSING, cells(c),
                        note="Listed by Microsoft under \"Intune features not available in GCC High and DoD\"."))
    sec = INTUNE_SUPPORTED
    pki = "The following Intune advanced capabilities support GCC High environments only and aren't supported in DoD: / / - Cloud PKI / - Remote Help"
    if not PAGES["intune-gov"].find(sec, pki):
        fail("intune-gov: the Cloud PKI and Remote Help sentence moved")
    for s, name in (("cloud-pki", "Cloud PKI"), ("remote-help", "Remote Help")):
        out.append(fact(f"intune.{s}", f"intune/{s}", f"Intune: {name}", "tenant",
                        {"gcchigh": "available", "dod": "not-available"}, "intune-gov", sec, pki))
    mde = ("This support extends to the US Government Community Cloud (GCC), US Government Community High (GCC High), "
           "and Department of Defense (DoD) environments.")
    if not PAGES["intune-gov"].find(sec, mde):
        fail("intune-gov: the Defender security settings sentence moved")
    out.append(fact("intune.defender-security-settings-management", "intune/defender-security-settings-management",
                    "Intune: Microsoft Defender for Endpoint security settings management", "tenant",
                    {t: "available" for t in TENANTS}, "intune-gov", sec, mde))
    return unique(out)


# ---------------------------------------------------------------- Defender for Endpoint and Defender XDR (by tenant)
DEFENDER = [  # page, first cell, key, name
    ("mde-gov", "Microsoft Secure Score", "defender-endpoint/secure-score", "Microsoft Secure Score"),
    ("mde-gov", "Microsoft Threat Experts", "defender-endpoint/threat-experts", "Microsoft Threat Experts"),
    ("mde-gov", "Microsoft Defender for Endpoint Security Configuration Management",
     "defender-endpoint/security-configuration-management", "Security Configuration Management"),
    ("mde-gov", "Microsoft Defender for IoT enterprise IoT security", "defender-endpoint/enterprise-iot-security",
     "Defender for IoT enterprise IoT security"),
    ("mde-gov", "Reports: Web content filtering", "defender-endpoint/mobile/web-content-filtering-reports",
     "Mobile: web content filtering reports"),
    ("mde-gov", "Reports: Device health", "defender-endpoint/mobile/device-health-reports", "Mobile: device health reports"),
    ("mde-gov", "Web Protection (Anti-Phishing and custom indicators)", "defender-endpoint/mobile/web-protection",
     "Mobile: web protection (anti-phishing and custom indicators)"),
    ("mde-gov", "Malware Protection (Android-Only)", "defender-endpoint/mobile/malware-protection",
     "Mobile: malware protection (Android)"),
    ("mde-gov", "Jailbreak Detection (iOS-Only)", "defender-endpoint/mobile/jailbreak-detection",
     "Mobile: jailbreak detection (iOS)"),
    ("mde-gov", "Conditional Access/Conditional Launch", "defender-endpoint/mobile/conditional-access",
     "Mobile: Conditional Access and Conditional Launch"),
    ("mde-gov", "Support for MAM", "defender-endpoint/mobile/mam", "Mobile: support for MAM"),
    ("mde-gov", "Privacy Controls", "defender-endpoint/mobile/privacy-controls", "Mobile: privacy controls"),
    ("mde-gov", "Microsoft Defender Vulnerability Management core capabilities / (included in Defender for Endpoint "
     "Plan 2) / See note following this table", "defender-vulnerability-management/core",
     "Defender Vulnerability Management core capabilities"),
    ("mde-gov", "Microsoft Defender Vulnerability Management premium capabilities / See note following this table",
     "defender-vulnerability-management/premium", "Defender Vulnerability Management premium capabilities"),
    ("xdr-gov", "Microsoft Threat Experts", "defender-xdr/threat-experts", "Microsoft Threat Experts"),
    ("xdr-gov", "Microsoft Defender for IoT enterprise IoT security", "defender-xdr/enterprise-iot-security",
     "Defender for IoT enterprise IoT security"),
]
ICONS = {"[check-yes]": "available", "[check-no]": "not-available", "[check-no] On engineering backlog": "backlog"}
PRODUCT = {"defender-endpoint": "Defender for Endpoint", "defender-xdr": "Defender XDR",
           "defender-vulnerability-management": "Defender Vulnerability Management"}
DEFENDER_NOTES = {
    "defender-endpoint/secure-score": "While Microsoft Secure Score is available for GCC, GCC High and DoD customers, "
                                      "there are some security recommendations that aren't available.",
}
DVM_MISSING = "The following Defender Vulnerability Management functionality isn't available for GCC, GCC High, and DoD customers:"


def build_defender():
    sec, out = "feature-parity-with-commercial", []
    for key, first, feature, name in DEFENDER:
        hits = [c for c in rows(key, sec) if c[0] == first]
        if len(hits) != 1:
            fail(f"{key}: expected one row {first!r}, found {len(hits)}")
        c = hits[0]
        status = {}
        for tenant, cell in zip(TENANTS, c[1:4]):
            bare = cell.removesuffix(" / See note following this table")
            if bare not in ICONS:
                fail(f"{key}:{first}: unknown cell {cell!r}")
            status[tenant] = ICONS[bare]
        note = quote(key, sec, DEFENDER_NOTES[feature]) if feature in DEFENDER_NOTES else None
        product = PRODUCT[feature.split("/")[0]]
        out.append(fact(feature.replace("/", "."), feature, f"{product}: {name}", "tenant", status, key, sec, cells(c),
                        note=note))
    quote("mde-gov", sec, DVM_MISSING)
    for item, s in (("Report inaccuracy", "report-inaccuracy"), ("Request CVE support", "request-cve-support")):
        quote("mde-gov", sec, item)
        feature = f"defender-vulnerability-management/{s}"
        out.append(fact(feature.replace("/", "."), feature, f"Defender Vulnerability Management: {item}", "tenant",
                        {t: "not-available" for t in TENANTS}, "mde-gov", sec, f"{DVM_MISSING} ; {item}"))
    return unique(out)


# ---------------------------------------------------------------- Defender API hosts for `fairfax scan`
def build_endpoints():
    xdr = [c for c in rows("xdr-gov", "api") if c[0] == "Microsoft Defender XDR API"]
    mde = [c for c in rows("mde-gov", "api") if c[0] == "Defender for Endpoint API"]
    if len(xdr) != 1 or len(mde) != 1:
        fail("defender api rows moved")
    xdr, mde = xdr[0], mde[0]
    if xdr[1:] != ["https://api-gcc.security.microsoft.us", "https://api-gov.security.microsoft.us"]:
        fail(f"xdr-gov api row changed: {xdr}")
    if mde[1:] != ["https://api-gcc.securitycenter.microsoft.us", "https://api-gov.securitycenter.microsoft.us"]:
        fail(f"mde-gov api row changed: {mde}")
    base = quote("xdr-apis", "endpoint-uris", "The base URI for both of the main APIs is: https://api.security.microsoft.com.")
    geo = ["us", "eu", "uk", "au", "swa", "ina", "aea"]
    also = [{"source": "xdr-apis", "anchor": "endpoint-uris", "quote": base}]
    for g in geo:
        also.append({"source": "mde-apis", "anchor": "versioning", "quote": quote("mde-apis", "versioning", f"{g}.api.security.microsoft.com")})
    return [
        endpoint("endpoint.defender-xdr-api", "Microsoft Defender XDR API", "m365",
                 {"commercial": ["api.security.microsoft.com"] + [f"{g}.api.security.microsoft.com" for g in geo],
                  "gcc": "api-gcc.security.microsoft.us", "gcchigh": "api-gov.security.microsoft.us",
                  "dod": "api-gov.security.microsoft.us"},
                 "xdr-gov", "api", cells(xdr), also=also),
        endpoint("endpoint.defender-endpoint-api-gov", "Microsoft Defender for Endpoint API (US Government)", "m365",
                 {"gcc": "api-gcc.securitycenter.microsoft.us", "gcchigh": "api-gov.securitycenter.microsoft.us",
                  "dod": "api-gov.securitycenter.microsoft.us"},
                 "mde-gov", "api", cells(mde)),
    ]


# ---------------------------------------------------------------- sign-in errors for `fairfax explain`
SIGN_IN = "endpoint.login-microsoftonline-com"
NATIONAL_ROW = "Microsoft Entra ID for US Government | https://login.microsoftonline.us"
ERRORS = [  # code, says, fix, confidence, extra quotes (source, section, text)
    ("AADSTS900439",
     "Your app signed in a GCC High, DoD or Azure Government user through the commercial sign-in host, "
     "login.microsoftonline.com. Microsoft Entra ID has blocked that since 2020: users in US Government tenants "
     "must sign in through login.microsoftonline.us.",
     "Point the app's authority at login.microsoftonline.us. If the app is registered in a commercial tenant and is "
     "meant to serve US Government users, Microsoft says it may need a new app registration in the US Government cloud.",
     "high",
     [("entra-breaking", "azure-government-endpoints-are-changing",
       "If you own an application within a US Government tenant, you must update your application to sign users in on the .us endpoint."),
      ("entra-breaking", "azure-government-endpoints-are-changing",
       "This may require creating a new app registration in the US Government cloud."),
      ("entra-national", "microsoft-entra-authentication-endpoints", NATIONAL_ROW)]),
    ("AADSTS90038",
     "The tenant you're signing in to belongs to a different national cloud from the sign-in host you used, and the "
     "two clouds don't federate. Typical cause: a GCC High, DoD or Azure Government tenant reached through "
     "login.microsoftonline.com, or the other way round.",
     "Send the request to the sign-in host of the tenant's own cloud.",
     "high", [("entra-national", "microsoft-entra-authentication-endpoints", NATIONAL_ROW)]),
    ("AADSTS90002",
     "Microsoft Entra ID can't find the tenant on the host you asked. Microsoft says this often happens because a "
     "cross-cloud app was used against the wrong cloud: a GCC High, DoD or Azure Government tenant doesn't exist on "
     "login.microsoftonline.com.",
     "Check the tenant ID, then sign in through the host of the cloud that tenant lives in.",
     "high", [("entra-national", "microsoft-entra-authentication-endpoints", NATIONAL_ROW)]),
    ("AADSTS900432",
     "An app that signs in with a secret or certificate (a confidential client) asked for a token across clouds, for "
     "example an app registered in commercial Entra ID calling into a GCC High tenant. Microsoft doesn't support "
     "confidential clients in cross-cloud requests.",
     "Register the app in the same cloud as the tenant it calls, and request tokens from that cloud's sign-in host.",
     "high", [("entra-national", "microsoft-entra-authentication-endpoints", NATIONAL_ROW)]),
    ("AADSTS900382",
     "Same message as AADSTS900432: a confidential client (an app with a secret or certificate) asked for a token "
     "across clouds, and Microsoft doesn't support that.",
     "Register the app in the same cloud as the tenant it calls, and request tokens from that cloud's sign-in host.",
     "high", [("entra-national", "microsoft-entra-authentication-endpoints", NATIONAL_ROW)]),
    ("AADSTS1000104",
     "A user from one cloud tried to reach a resource in another cloud (cross-cloud B2B), and the tenant's settings "
     "don't allow that pairing of clouds.",
     "Either allow B2B collaboration with the other Microsoft cloud in the tenant's cross-tenant access settings, or "
     "use an account from the resource's own cloud.",
     "medium", []),
    ("AADSTS700016",
     "The app wasn't found in the tenant. In US government setups a common cause is an app registered in one cloud "
     "(for example Azure Government) while the token request goes to the other cloud's sign-in host, where the app "
     "doesn't exist.",
     "Check which cloud the app registration lives in and send the request to that cloud's sign-in host, with that "
     "tenant's ID.",
     "medium", [("entra-national", "microsoft-entra-authentication-endpoints", NATIONAL_ROW)]),
    ("AADSTS90051",
     "The national cloud identifier in the request isn't valid, for example a misspelled or mixed-up cloud name in "
     "your authentication library's settings.",
     "Check the cloud or instance setting your library uses against the endpoint for your tenant's cloud.",
     "medium", [("entra-national", "microsoft-entra-authentication-endpoints", NATIONAL_ROW)]),
    ("AADSTS50049",
     "The authority your app was given isn't a known Microsoft Entra instance, often a typo in the sign-in host or a "
     "host from the wrong cloud.",
     "Use the sign-in host for your tenant's cloud exactly as Microsoft lists it.",
     "medium", [("entra-national", "microsoft-entra-authentication-endpoints", NATIONAL_ROW)]),
]
BREAKING_900439 = ("Impacted apps will begin seeing an error AADSTS900439 - USGClientNotSupportedOnPublicEndpoint. "
                   "This error indicates that the app is attempting to sign in a US Government user on the public "
                   "cloud endpoint.")


def build_errors():
    table = {c[0]: c for c in rows("entra-errors", "aadsts-error-codes")}
    out = []
    for code, says, fix, confidence, extra in ERRORS:
        if code == "AADSTS900439":
            source, anchor, row = "entra-breaking", "azure-government-endpoints-are-changing", \
                quote("entra-breaking", "azure-government-endpoints-are-changing", BREAKING_900439)
            name = "USGClientNotSupportedOnPublicEndpoint"
        else:
            if code not in table:
                fail(f"entra-errors: {code} not in the table")
            row = cells(table[code])
            source, anchor = "entra-errors", "aadsts-error-codes"
            m = re.match(r"([A-Za-z0-9_]+) - ", table[code][1])
            name = m.group(1) if m else table[code][1].rstrip(".")
        also = []
        for key, sec, text in extra:
            if not PAGES[key].find(sec, text):
                fail(f"{key}#{sec}: not found: {text!r}")
            also.append({"source": key, "anchor": sec, "quote": text})
        d = {"id": f"error.{code.lower()}", "code": code, "name": name, "says": says, "fix": fix,
             "endpoint": SIGN_IN, "source": source, "anchor": anchor, "row": row, "confidence": confidence}
        if also:
            d["also"] = also
        out.append(d)
    return out


# ---------------------------------------------------------------- emit (same YAML style as build_facts.py)
def fact(fid, feature, name, by, status, source, anchor, row, note=None, confidence="high", **extra):
    d = {"id": fid, "feature": feature, "name": name, "by": by, "status": status}
    d.update({k: v for k, v in extra.items() if v is not None})
    if note:
        d["note"] = note
    d.update({"source": source, "anchor": anchor, "row": row, "confidence": confidence})
    return d


def endpoint(eid, service, plane, hosts, source, anchor, row, also=None):
    d = {"id": eid, "service": service, "plane": plane, "hosts": hosts, "source": source, "anchor": anchor, "row": row}
    if also:
        d["also"] = also
    return d


def scalar(v):
    if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return v
    if isinstance(v, str) and re.fullmatch(r"[a-z][a-z0-9.+/:-]*", v) and v not in ("yes", "no", "on", "off", "true", "false", "null"):
        return v
    return json.dumps(v, ensure_ascii=False)


def emit_item(d):
    lines, first = [], True
    for k, v in d.items():
        lead = "  - " if first else "    "
        first = False
        if isinstance(v, dict):
            inner = ", ".join(f"{ik}: {emit_list(iv) if isinstance(iv, list) else scalar(iv)}" for ik, iv in v.items())
            lines.append(f"{lead}{k}: {{{inner}}}")
        elif isinstance(v, list) and v and isinstance(v[0], dict):
            lines.append(f"{lead}{k}:")
            for q in v:
                lines.append("      - " + "\n        ".join(f"{qk}: {scalar(qv)}" for qk, qv in q.items()))
        elif isinstance(v, list):
            lines.append(f"{lead}{k}: {emit_list(v)}")
        else:
            lines.append(f"{lead}{k}: {scalar(v)}")
    return "\n".join(lines)


def emit_list(v):
    return "[" + ", ".join(scalar(x) for x in v) + "]"


def write(name, header, key, items):
    body = "\n\n".join(emit_item(d) for d in items)
    (OUT / name).write_text(f"{header}\n{key}:\n{body}\n", encoding="utf-8", newline="\n")
    print(f"{name}: {len(items)}")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    src = ["# Pages added in 0.2.0, written by tools/build_m365.py. Same fields as sources.yaml.", "sources:"]
    for k, s in SOURCES.items():
        src.append(f"  {k}:")
        for sk in ("title", "url", "page_updated", "checked"):
            src.append(f"    {sk}: {scalar(s[sk]) if sk != 'url' else json.dumps(s[sk])}")
    (OUT / "sources-m365.yaml").write_text("\n".join(src) + "\n", encoding="utf-8", newline="\n")
    hdr = "# Generated from Microsoft's own tables by tools/build_m365.py. Each row is the source text the status came from."
    write("m365-copilot.yaml", hdr, "facts", build_copilot())
    write("teams.yaml", hdr, "facts", build_teams())
    write("exchange.yaml", hdr, "facts", build_exchange())
    write("sharepoint.yaml", hdr + "\n# These pages list differences as sentences; each row is the sentence itself.", "facts",
          build_sharepoint())
    write("purview.yaml", hdr + "\n# Microsoft publishes one page per cloud, so each feature has one entry per cloud.",
          "facts", build_purview())
    write("intune.yaml", hdr + "\n# The Intune page covers GCC High and DoD only.", "facts", build_intune())
    write("defender.yaml", hdr + "\n# Microsoft marks these cells with tick and cross images, written here as [check-yes] and [check-no].",
          "facts", build_defender())
    write("endpoints-defender.yaml", "# Defender API hosts added in 0.2.0 for `fairfax scan`.", "endpoints", build_endpoints())
    write("errors.yaml", "# Sign-in errors decoded by `fairfax explain`. says and fix are fairfax's words; row and also are Microsoft's.",
          "errors", build_errors())


if __name__ == "__main__":
    main()
