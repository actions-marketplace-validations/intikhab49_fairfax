"""The one-time builder that produced the 0.1.0 dataset from Microsoft's pages.

Statuses are parsed from the row text found in the page dumps. Any row, quote or host that can't be
found is a hard error, so nothing in the output was retyped by hand. Since 0.1.0 the YAML files in
src/govgap/data are the source of truth: re-running this overwrites any hand edits made since.

Usage:
  python tools/dump_learn.py <saved-page.html> <dump_dir>/<key>.txt   (once per page in URLS)
  python tools/build_facts.py <dump_dir> <out_dir>
The Power Platform PDF is dumped to <dump_dir>/bap.txt with pypdf's extract_text().
"""
import json
import re
import sys
from pathlib import Path

CHECKED = "2026-10-11"
DUMP, OUT = Path(sys.argv[1]), Path(sys.argv[2])

URLS = {
    "security-fa": "https://learn.microsoft.com/en-us/azure/security/fundamentals/feature-availability",
    "sentinel-fa": "https://learn.microsoft.com/en-us/azure/sentinel/feature-availability",
    "aml-parity": "https://learn.microsoft.com/en-us/azure/machine-learning/reference-machine-learning-cloud-parity?view=azureml-api-2",
    "lang-regions": "https://learn.microsoft.com/en-us/azure/ai-services/language-service/concepts/regional-support",
    "ctc-overview": "https://learn.microsoft.com/en-us/azure/ai-services/language-service/custom-text-classification/overview",
    "aoai-gov": "https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-gov",
    "graph-deployments": "https://learn.microsoft.com/en-us/graph/deployments",
    "azgov-compare": "https://learn.microsoft.com/en-us/azure/azure-government/compare-azure-government-global-azure",
    "pa-usgov": "https://learn.microsoft.com/en-us/power-platform/admin/powerapps-us-government",
    "pauto-usgov": "https://learn.microsoft.com/en-us/power-automate/us-govt",
    "gcc-sd": "https://learn.microsoft.com/en-us/office365/servicedescriptions/office-365-platform-service-description/office-365-us-government/gcc",
    "scc-ps": "https://learn.microsoft.com/en-us/powershell/exchange/connect-to-scc-powershell",
    "dv-regions": "https://learn.microsoft.com/en-us/power-platform/admin/new-datacenter-regions",
    "pbi-gov": "https://learn.microsoft.com/en-us/fabric/enterprise/powerbi/service-government-us-overview",
}


class Page:
    def __init__(self, key):
        self.key = key
        self.rows, self.text, self.meta, self.title = [], [], {}, ""
        for line in (DUMP / f"{key}.txt").read_text(encoding="utf-8").splitlines():
            if line.startswith("META "):
                k, _, v = line[5:].partition(" = ")
                self.meta[k] = v
            elif line.startswith("## [h1#") and not self.title:
                self.title = line.split("] ", 1)[1]
            m = re.match(r"  (ROW|P|LI)\[([^\]]*)\] ?(.*)$", line)
            if m:
                kind, sec, body = m.groups()
                if kind == "ROW":
                    self.rows.append((sec, [c.strip() for c in body.split(" | ")]))
                else:
                    self.text.append((sec, body))

    def row(self, section, first):
        hits = [c for s, c in self.rows if s == section and c[0] == first]
        if len(hits) != 1:
            sys.exit(f"{self.key}#{section}: expected 1 row starting {first!r}, found {len(hits)}")
        return hits[0]

    def section_rows(self, section):
        return [c for s, c in self.rows if s == section]

    def quote(self, section, needle):
        for s, t in self.text:
            if s == section and needle in t:
                return needle
        sys.exit(f"{self.key}#{section}: quote not found: {needle!r}")

    def updated(self):
        return self.meta["updated_at"][:10]


PAGES = {k: Page(k) for k in URLS}
BAP_LINES = (DUMP / "bap.txt").read_text(encoding="utf-8").splitlines()
assert "May, 2026" in BAP_LINES, "BAP PDF date line moved"

SOURCES = {k: {"title": p.title, "url": URLS[k], "page_updated": p.updated(), "checked": CHECKED} for k, p in PAGES.items()}
SOURCES["bap"] = {
    "title": "Business Applications feature availability in US Government clouds (PDF, May, 2026)",
    "url": "https://aka.ms/BAPFunctionalParity",
    "page_updated": "2026-06-15",
    "checked": CHECKED,
}


def cells(c):
    return " | ".join(c).strip(" |")


def strip_fn(s):
    m = re.match(r"^(.*?)\s+(\d)$", s)
    return (m.group(1), m.group(2)) if m else (s, None)


# ---------------------------------------------------------------- Defender for Cloud (by azure)
DEF_MAP = {"GA": "ga", "Public Preview": "preview", "Not Available": "not-available"}
DEF_FN = {}
for s, t in PAGES["security-fa"].text:
    m = re.match(r"^(\d) (.*)$", t)
    if s == "microsoft-defender-for-cloud" and m:
        DEF_FN[m.group(1)] = m.group(2)

DEFENDER = [
    ("- Continuous export", "continuous-export"),
    ("- Workflow automation", "workflow-automation"),
    ("- Recommendation exemption rules", "recommendation-exemption-rules"),
    ("- Microsoft Defender for servers", "servers"),
    ("- Microsoft Defender for AI Services", "ai-services"),
    ("- Microsoft Defender for App Service", "app-service"),
    ("- Microsoft Defender for DNS", "dns"),
    ("- Microsoft Defender for Containers", "containers"),
    ("- Microsoft Defender for Azure SQL database servers", "azure-sql"),
    ("- Microsoft Defender for SQL servers on machines", "sql-servers-on-machines"),
    ("- Microsoft Defender for open-source relational databases", "open-source-databases"),
    ("- Microsoft Defender for Key Vault", "key-vault"),
    ("- Microsoft Defender for Resource Manager", "resource-manager"),
    ("- Microsoft Defender for Storage 1", "storage"),
    ("- Microsoft Defender for Azure Cosmos DB", "cosmos-db"),
    ("- Kubernetes workload protection", "kubernetes-workload-protection"),
    ("- Bi-directional alert synchronization with Microsoft Sentinel", "sentinel-alert-sync"),
    ("- Just-in-time VM access", "just-in-time-vm-access"),
    ("- File integrity monitoring", "file-integrity-monitoring"),
    ("- Adaptive network hardening", "adaptive-network-hardening"),
    ("- Integrated vulnerability assessment for machines", "vulnerability-assessment"),
    ("- Regulatory compliance dashboard and reports 4", "regulatory-compliance"),
    ("- Connect AWS account", "connect-aws"),
    ("- Connect GCP account", "connect-gcp"),
]


def build_defender():
    out = []
    for first, slug in DEFENDER:
        c = PAGES["security-fa"].row("microsoft-defender-for-cloud", first)
        name, fn1 = strip_fn(first[2:])
        com, fn2 = strip_fn(c[1])
        gov, fn3 = strip_fn(c[2])
        notes = [DEF_FN[f] for f in (fn1, fn2, fn3) if f]
        out.append(fact(
            f"defender-for-cloud.{slug}", f"defender-for-cloud/{slug}", name, "azure",
            {"commercial": DEF_MAP[com], "government": DEF_MAP[gov]},
            "security-fa", "microsoft-defender-for-cloud", cells(c), note=" ".join(notes) or None))
    return out


# ---------------------------------------------------------------- Sentinel M365 connectors (by tenant+azure)
CONN_MAP = {"GA": "ga", "Public Preview": "preview", "Not Available": "not-available", "-": "not-possible"}
TENANT_ROWS = {"- Office 365 GCC": "gcc", "- Office 365 GCC High": "gcchigh", "- Office 365 DoD": "dod"}
CONNECTORS = {
    "Office IRM": "office-irm", "Dynamics 365": "dynamics-365", "Microsoft Defender XDR": "defender-xdr",
    "Microsoft Defender for Cloud Apps": "defender-for-cloud-apps",
    "Microsoft Defender for Cloud Apps / Shadow IT logs": "defender-for-cloud-apps-shadow-it",
    "Microsoft Defender for Cloud Apps / Alerts": "defender-for-cloud-apps-alerts",
    "Microsoft Defender for Endpoint": "defender-for-endpoint", "Microsoft Defender for Identity": "defender-for-identity",
    "Microsoft Defender for Office 365": "defender-for-office-365", "Microsoft Power BI": "power-bi",
    "Microsoft Project": "project", "Office 365": "office-365", "Teams": "teams",
}


def build_connectors():
    out, cur, rows = [], None, {}
    groups = []
    for c in PAGES["security-fa"].section_rows("microsoft-purview-data-connectors"):
        if c[0] == "Connector" or not c[0]:
            continue
        if c[0] in TENANT_ROWS:
            rows[c[0]] = c
            continue
        if cur:
            groups.append((cur, rows))
        cur, rows = c[0].removeprefix("- "), {}
    groups.append((cur, rows))
    seen = set()
    for name, rows in groups:
        slug = CONNECTORS[name]
        seen.add(name)
        assert set(rows) == set(TENANT_ROWS), name
        status = {}
        for first, tenant in TENANT_ROWS.items():
            r = rows[first]
            status[f"{tenant}+commercial"] = CONN_MAP[r[1]]
            status[f"{tenant}+government"] = CONN_MAP[r[2]]
        row = " ; ".join(cells([k[2:], *rows[k][1:]]) for k in TENANT_ROWS)
        out.append(fact(
            f"sentinel.connector.{slug}", f"sentinel/connector/{slug}", f"{name} data connector for Microsoft Sentinel",
            "tenant+azure", status, "security-fa", "microsoft-purview-data-connectors", f"{name}: {row}"))
    assert seen == set(CONNECTORS), set(CONNECTORS) - seen
    return out


# ---------------------------------------------------------------- Sentinel features (by azure)
STAGE = {"GA": "ga", "Public preview": "preview", "Limited preview": "private-preview",
         "Supported for production use": "ga", "Deprecated": "deprecated"}
SENTINEL = [
    ("analytics", "Scheduled and Microsoft rules", "scheduled-rules"),
    ("analytics", "NRT rules", "nrt-rules"),
    ("content-and-content-management", "Content hub and solutions", "content-hub"),
    ("content-and-content-management", "Repositories", "repositories"),
    ("content-and-content-management", "Workbooks", "workbooks"),
    ("data-collection", "Microsoft Entra ID", "connector/entra-id"),
    ("data-collection", "Microsoft Entra ID Protection", "connector/entra-id-protection"),
    ("data-collection", "Azure Activity", "connector/azure-activity"),
    ("data-collection", "Azure Key Vault", "connector/key-vault"),
    ("data-collection", "Azure Information Protection (Preview)", "connector/azure-information-protection"),
    ("data-collection", "Codeless Connectors Platform", "codeless-connector-platform"),
    ("data-collection", "DNS", "connector/dns"),
    ("data-collection", "Microsoft Defender for Cloud", "connector/defender-for-cloud"),
    ("data-collection", "Microsoft Purview Insider Risk Management (Preview)", "connector/purview-insider-risk"),
    ("data-collection", "Microsoft Purview (Preview)", "connector/purview"),
    ("data-collection", "Microsoft Purview Information Protection", "connector/purview-information-protection"),
    ("data-collection", "Microsoft Sentinel solution for Microsoft Business Apps", "business-apps-solution"),
    ("data-collection", "Summary rules", "summary-rules"),
    ("data-collection", "Syslog via AMA", "connector/syslog-ama"),
    ("data-collection", "Common Event Format (CEF) via AMA", "connector/cef-ama"),
    ("data-collection", "Windows Security Events via AMA", "connector/windows-security-events-ama"),
    ("hunting", "Hunts", "hunts"),
    ("hunting", "Search large datasets", "search-jobs"),
    ("hunting", "Restore historical data", "restore"),
    ("incidents", "Automation rules", "automation-rules"),
    ("incidents", "Run playbooks on incidents", "playbooks"),
    ("incidents", "Microsoft Teams integrations", "teams-integration"),
    ("machine-learning", "Fusion - advanced multistage attack detections 1", "fusion"),
    ("managing-microsoft-sentinel", "Workspace manager", "workspace-manager"),
    ("managing-microsoft-sentinel", "SIEM migration experience", "siem-migration"),
    ("notebooks", "Notebooks", "notebooks"),
    ("soc-optimizations", "SOC optimizations", "soc-optimizations"),
    ("sap", "Threat protection for SAP", "sap-threat-protection"),
    ("sap", "Agentless data connector", "connector/sap-agentless"),
    ("threat-intelligence-support", "GeoLocation and WhoIs data enrichment", "geolocation-whois-enrichment"),
    ("threat-intelligence-support", "Threat Intelligence - TAXII data connector", "connector/ti-taxii"),
    ("threat-intelligence-support", "Microsoft Defender Threat intelligence matching analytics", "mdti-matching-analytics"),
    ("threat-intelligence-support", "URL detonation", "url-detonation"),
    ("threat-intelligence-support", "Threat Intelligence Upload Indicators API", "ti-upload-api"),
    ("ueba", "Entity pages", "ueba-entity-pages"),
    ("ueba", "Peer/Blast radius enrichments", "ueba-peer-blast-radius"),
]


def sentinel_cloud(stage, yes_no):
    if yes_no == "No":
        return "not-available"
    assert yes_no == "Yes", yes_no
    return STAGE[stage]


def build_sentinel():
    out = []
    for sec, first, slug in SENTINEL:
        c = PAGES["sentinel-fa"].row(sec, first)
        name, _ = strip_fn(first)
        if c[1] == "Deprecated":
            status = {"commercial": "not-available", "government": "not-available"}
            note = "Microsoft lists this connector as deprecated."
        else:
            status = {"commercial": sentinel_cloud(c[1], c[2]), "government": sentinel_cloud(c[1], c[3])}
            note = None
        label = name if not slug.startswith("connector/") else f"{name} data connector"
        out.append(fact(f"sentinel.{slug.replace('/', '.')}", f"sentinel/{slug}", f"Microsoft Sentinel: {label}",
                        "azure", status, "sentinel-fa", sec, cells(c), note=note))
    return out


# ---------------------------------------------------------------- Azure Machine Learning (by azure)
AML_PUBLIC = {"GA": "ga", "Public Preview": "preview", "Preview": "preview"}
AML = [
    ("Create and run experiments in notebooks", "automl", "Automated ML experiments in notebooks"),
    ("Azure Databricks integration", "automl-databricks", "Automated ML: Azure Databricks integration"),
    ("Create, run, visualize, and publish pipelines in Azure Machine Learning designer", "designer", "Designer pipelines"),
    ("Azure Databricks Integration with ML Pipeline", "pipeline-databricks", "Azure Databricks integration with ML pipelines"),
    ("Managed compute Instances for integrated Notebooks", "compute-instance", "Managed compute instances for notebooks"),
    ("Configure Apache Spark pools to perform data wrangling", "spark-pools", "Apache Spark pools for data wrangling"),
    ("Python SDK support", "python-sdk", "Python SDK"),
    ("Managed virtual network support", "managed-vnet", "Managed virtual network"),
    ("Workplace private endpoint", "workspace-private-endpoint", "Workspace private endpoint"),
    ("ACI behind VNet", "aci-behind-vnet", "Azure Container Instances behind a VNet"),
    ("Private IP of AKS cluster", "aks-private-ip", "Private IP for an AKS cluster"),
    ("Network isolation for managed online endpoints", "managed-endpoint-network-isolation", "Network isolation for managed online endpoints"),
    ("Kubernetes compute", "kubernetes-compute", "Kubernetes compute"),
    ("Model profiling (SDK/CLI v1)", "model-profiling", "Model profiling (SDK/CLI v1)"),
    ("Visual Studio Code integration", "vscode-integration", "Visual Studio Code integration"),
    ("Event Grid integration", "event-grid", "Event Grid integration"),
    ("Integrate Azure Stream Analytics with Azure Machine Learning", "stream-analytics", "Azure Stream Analytics integration"),
    ("Labeling Project Management Portal", "data-labeling", "Data labeling projects"),
    ("Explainability in UI", "explainability-ui", "Explainability in the studio UI"),
    ("Fairness Azure Machine Learning Integration", "fairness", "Fairness integration"),
    ("Custom tags in Azure Machine Learning to implement datasheets", "datasheet-tags", "Custom tags for datasheets"),
    ("Managed online endpoints", "managed-online-endpoints", "Managed online endpoints"),
    ("Batch inferencing", "batch-inference", "Batch inference"),
]
AML_NOTES = {
    "compute-instance": "For Azure Machine Learning compute instances, the ability to refresh a token lasting more than 24 hours isn't available in Azure Government.",
    "model-profiling": "Model Profiling doesn't support 4 CPUs in the US-Arizona region.",
}


def aml_gov(public, v):
    v = v.rstrip("*").upper()
    if v == "YES":
        return public
    return {"NO": "not-available", "PARTIAL": "limited", "GA": "ga", "PREVIEW": "preview"}[v]


def build_aml():
    out = []
    for first, slug, name in AML:
        c = PAGES["aml-parity"].row("azure-machine-learning-features", first)
        public = AML_PUBLIC[c[1]]
        va, az = aml_gov(public, c[2]), aml_gov(public, c[3])
        notes = []
        if va != az:
            notes.append(f"US Gov Virginia: {c[2]}, US Gov Arizona: {c[3]}.")
        gov = va if va == az else "limited"
        if slug in AML_NOTES:
            notes.append(PAGES["aml-parity"].quote("other-azure-government-limitations", AML_NOTES[slug]))
        out.append(fact(f"azure-ml.{slug}", f"azure-ml/{slug}", f"Azure Machine Learning: {name}", "azure",
                        {"commercial": public, "government": gov}, "aml-parity", "azure-machine-learning-features",
                        cells(c), note=" ".join(notes) or None))
    return out


# ---------------------------------------------------------------- Azure AI Language (by azure, region tables)
LANG = [
    ("conversational-language-understanding-and-orchestration-workflow", "conversational-language-understanding",
     "Conversational language understanding (CLU) and orchestration workflow"),
    ("custom-named-entity-recognition", "custom-ner", "Custom named entity recognition"),
    ("custom-text-classification", "custom-text-classification", "Custom text classification"),
    ("summarization", "summarization", "Summarization"),
    ("custom-question-and-answering", "custom-question-answering", "Custom question answering"),
]


def build_language():
    out, p = [], PAGES["lang-regions"]
    for sec, slug, name in LANG:
        rows = p.section_rows(sec)
        assert len(rows) > 5, sec
        gov = [c for c in rows if c[0].lower().startswith("usgov")]
        if gov:
            assert {c[0] for c in gov} == {"USGovVirginia", "USGovArizona"}, gov
            status, row = "available", " ; ".join(cells(c) for c in gov)
        else:
            status, row = "not-available", "No USGovVirginia or USGovArizona row in the region table"
        extra = {}
        if slug == "custom-text-classification":
            q = PAGES["ctc-overview"].quote(
                "ms--in-this-article", "Custom text classification retires from Azure Language on March 31, 2029.")
            PAGES["ctc-overview"].quote("ms--in-this-article", "direct all new projects to Microsoft Foundry")
            extra = {"retires": "2029-03-31", "retires_source": "ctc-overview", "retires_quote": q,
                     "instead": "Microsoft says to direct all new projects to Microsoft Foundry."}
        out.append(fact(f"ai-language.{slug}", f"ai-language/{slug}", f"Azure AI Language: {name}", "azure",
                        {"commercial": "available", "government": status}, "lang-regions", sec, row, **extra))
    return out


# ---------------------------------------------------------------- Azure OpenAI models (by azure)
AOAI_TABLES = [
    ("data-zone-standard-model-availability", "Data Zone Standard"),
    ("data-zone-provisioned-managed-model-availability", "Data Zone Provisioned"),
    ("standard-deployment-model-availability", "Standard"),
    ("provisioned-deployment-model-availability", "Provisioned"),
]


def build_aoai():
    p = PAGES["aoai-gov"]
    avail = {}
    for sec, label in AOAI_TABLES:
        rows = p.section_rows(sec)
        header = rows[0]
        assert header[0] == "Region", header
        models = [h.split(",")[0].strip() for h in header[1:]]
        for r in rows[1:]:
            region = r[0]
            assert region in ("usgovarizona", "usgovvirginia"), region
            vals = r[1:] + [""] * (len(models) - len(r[1:]))
            for m, v in zip(models, vals):
                if "✅" in v:
                    avail.setdefault(m, {}).setdefault(label, []).append(region)
    out = []
    for m in sorted(avail):
        parts = []
        for _, label in AOAI_TABLES:
            regions = sorted(avail[m].get(label, []))
            if regions:
                parts.append(f"{label} ({' and '.join(regions)})")
        note = "Deployment types in Azure Government: " + "; ".join(parts) + "."
        if "Standard" not in avail[m]:
            note += " No regional Standard deployment."
        out.append(fact(f"azure-openai.{m}", f"azure-openai/{m}", f"Azure OpenAI model {m}", "azure",
                        {"government": "available"}, "aoai-gov", "model-summary-table-and-region-availability",
                        f"{m}: " + "; ".join(parts), note=note))
    assert len(out) >= 10, [f["feature"] for f in out]
    return out


# ---------------------------------------------------------------- Power Platform (BAP PDF, by tenant)
BAP_STATUS = r"(?:Not Available|Available \(CSS ticket\)|\*Available|Available|Public Preview|Private Preview|Limited|No [Pp]lans|Not Relevant|CY\d{4}-(?:H[12]|Q[1-4]))"
BAP_RE = re.compile(rf"^(?P<name>.+?) (?P<a>{BAP_STATUS}) (?P<b>{BAP_STATUS}) (?P<c>{BAP_STATUS})$")


def bap_status(s):
    s = s.lstrip("*")
    if s.startswith("CY"):
        return f"planned:{s}"
    return {"Available": "ga", "Available (CSS ticket)": "ga", "Not Available": "not-available",
            "Public Preview": "preview", "Private Preview": "private-preview", "Limited": "limited",
            "No plans": "no-plans", "No Plans": "no-plans"}[s]


BAP = [
    # (exact feature text in the PDF, feature key, display name or None)
    ("Azure Synapse Link for Dataverse (and Data Lake)", "dataverse/synapse-link", None),
    ("Continuous access evaluation integration with Power Platform (preview)", "power-platform/continuous-access-evaluation", None),
    ("Customer Lockbox", "power-platform/customer-lockbox", None),
    ("Install Applications via AppSource", "power-platform/appsource-install", None),
    ("Pay as you Go licensing model", "power-platform/pay-as-you-go", None),
    ("Capacity management for Dataverse environment", "dataverse/capacity-management", None),
    ("Customer managed key", "power-platform/customer-managed-key", None),
    ("Data loss prevention activity logging", "power-platform/dlp-activity-logging", None),
    ("Export Diagnostics & Performance Data to App Insights", "power-platform/app-insights-export", None),
    ("Tenant Isolation", "power-platform/tenant-isolation", None),
    ("Security Hub in PPAC", "power-platform/security-hub", None),
    ("Virtual Network (vNet) support for Power Platform", "power-platform/vnet-support", None),
    ("GitHub Actions CI/CD CLI Tool Integration", "power-platform/github-actions", None),
    ("Power Platform inventory and usage data", "power-platform/inventory-usage-data", None),
    ("Managed Environments", "power-platform/managed-environments", None),
    ("ME Admin Digest (Usage insights)", "power-platform/me-admin-digest", "Managed Environments admin digest (usage insights)"),
    ("ME Data Policies", "power-platform/me-data-policies", "Managed Environments data policies"),
    ("ME Limit Sharing", "power-platform/me-limit-sharing", "Managed Environments limit sharing"),
    ("ME Maker Onboarding", "power-platform/me-maker-onboarding", "Managed Environments maker onboarding"),
    ("ME Set up pipelines in Power Platform", "power-platform/pipelines", "Pipelines in Power Platform"),
    ("Solution Checker", "power-platform/solution-checker", None),
    ("Custom Connectors", "power-platform/custom-connectors", None),
    ("Custom Code Connectors", "power-platform/custom-code-connectors", None),
    ("Cards for PowerApps", "power-apps/cards", "Cards for Power Apps"),
    ("Coauthoring in model-driven apps (preview)", "power-apps/model-driven-coauthoring", None),
    ("Code Apps", "power-apps/code-apps", None),
    ("Custom Pages in MDAs", "power-apps/custom-pages", "Custom pages in model-driven apps"),
    ("Dataflows in Power Apps", "power-apps/dataflows", None),
    ("Dataverse for Teams", "dataverse/for-teams", None),
    ("Dataverse for Teams Edit in Excel", "dataverse/for-teams-edit-in-excel", None),
    ("Embed a canvas app as personal app in Teams", "power-apps/canvas-teams-personal-app", None),
    ("Embed a canvas app as tab app in Teams", "power-apps/canvas-teams-tab", None),
    ("Embed a model-driven app as personal app in Teams", "power-apps/model-driven-teams-personal-app", None),
    ("Embed a model-driven app as tab app in Teams", "power-apps/model-driven-teams-tab", None),
    ("Embed Stream in Canvas App", "power-apps/stream-embed", None),
    ("Geospatial Components", "power-apps/geospatial-components", None),
    ("Native Power Apps (Wrap Service)", "power-apps/wrap", None),
    ("Power Apps B2B Bring your Own License (Cross Cloud) - Per User", "power-apps/b2b-byol-cross-cloud", None),
    ("Push Notifications - Android", "power-apps/push-notifications-android", None),
    ("Push Notifications - IOS", "power-apps/push-notifications-ios", "Push Notifications - iOS"),
    ("Test Studio", "power-apps/test-studio", None),
    ("Power Apps / Dataverse native integration with Git (ALM)", "power-apps/git-integration", None),
    ("Plan Designer", "power-apps/plan-designer", None),
    ("Azure Maps in Canvas Apps", "power-apps/azure-maps", None),
    ("Power Apps Monitor", "power-apps/monitor", None),
    ("Intune MAM", "power-apps/intune-mam", None),
    ('Actionable Approval Emails (.e.g. "Adaptive Cards")', "power-automate/actionable-approval-emails",
     "Actionable approval emails (Adaptive Cards in Outlook)"),
    ("Excel App", "power-automate/excel-app", "Power Automate Excel app"),
    ("Guest User Participation in Approval Workflows", "power-automate/guest-approvals", None),
    ("Mobile App - iOS", "power-automate/mobile-ios", "Power Automate mobile app for iOS"),
    ("Mobile App - Android", "power-automate/mobile-android", "Power Automate mobile app for Android"),
    ("Power Automate Analytics (Per Flow)", "power-automate/analytics-per-flow", None),
    ("Power Automate Analytics (Tenant)", "power-automate/analytics-tenant", None),
    ("Power Automate Desktop", "power-automate/desktop-flows", None),
    ("Power Automate Teams App", "power-automate/teams-app", None),
    ("Process Advisor", "power-automate/process-advisor", None),
    ("Send a message in Teams using Power Automate (Teams Flow Bot)", "power-automate/teams-flow-bot", None),
    ("Create a Power Automate visual for Power BI (Preview)", "power-automate/power-bi-visual", None),
    ("Power Pages", "power-pages/sites", None),
    ("Web Application Firewall (WAF)", "power-pages/waf", "Power Pages Web Application Firewall"),
    ("Power Platform AI Builder", "ai-builder/service", "AI Builder"),
    ("Custom Document Processing (Unstructured Documents)", "ai-builder/document-processing-unstructured", "AI Builder custom document processing (unstructured)"),
    ("Prebuilt Category Classification", "ai-builder/prebuilt-category-classification", "AI Builder prebuilt category classification"),
    ("Custom Image Classification (Lobe)", "ai-builder/custom-image-classification", "AI Builder custom image classification (Lobe)"),
    ("Document Automation Toolkit", "ai-builder/document-automation-toolkit", None),
    ("Copilot Studio", "copilot-studio/service", None),
    ("Copilot Studio Microsoft Teams app experience", "copilot-studio/teams-app", None),
    ("Teams channel in the Copilot Studio web app", "copilot-studio/teams-channel", None),
    ("Transfer to agents", "copilot-studio/transfer-to-agents", "Copilot Studio transfer to agents"),
    ("PVA Telephony(Standalone IVR)", "copilot-studio/telephony", "Copilot Studio telephony (standalone IVR)"),
]


def build_bap():
    parsed = {}
    for line in BAP_LINES:
        m = BAP_RE.match(line.strip())
        if m:
            parsed.setdefault(m.group("name"), set()).add((m.group("a"), m.group("b"), m.group("c")))
    out = []
    for text, key, display in BAP:
        hits = parsed.get(text)
        if not hits or len(hits) != 1:
            sys.exit(f"BAP: expected one consistent row for {text!r}, got {hits}")
        a, b, c = next(iter(hits))
        status = {"gcc": bap_status(a), "gcchigh": bap_status(b), "dod": bap_status(c)}
        out.append(fact(key.replace("/", "."), key, display or text, "tenant", status,
                        "bap", "", f"{text} | {a} | {b} | {c}"))
    return out


# ---------------------------------------------------------------- stack-level rules
def build_rules():
    sfa, gd, gcc, pa = PAGES["security-fa"], PAGES["graph-deployments"], PAGES["gcc-sd"], PAGES["pa-usgov"]
    tokens = gd.quote("microsoft-graph-and-graph-explorer-service-root-endpoints",
                      "Access tokens acquired for a national cloud deployment are not interchangeable with those acquired for the global service or any other national cloud.")
    return [
        rule("pairing.gcc-commercial-entra", 'GCC signs in through commercial Entra ID', {"tenant": ["gcc"]}, "note",
             "Office 365 GCC signs users in through commercial Entra ID: login.microsoftonline.com, graph.microsoft.com "
             "and portal.azure.com, the same endpoints as worldwide Microsoft 365.",
             "security-fa", "microsoft-365-integration",
             sfa.quote("microsoft-365-integration", "Office 365 and Office 365 GCC are paired with Microsoft Entra ID in Azure.")),
        rule("pairing.gcchigh-gov-entra", 'GCC High and DoD sign in through Azure Government', {"tenant": ["gcchigh", "dod"]}, "note",
             "GCC High and DoD sign users in through Entra ID in Azure Government: login.microsoftonline.us, with "
             "graph.microsoft.us (GCC High) or dod-graph.microsoft.us (DoD).",
             "security-fa", "microsoft-365-integration",
             sfa.quote("microsoft-365-integration", "Office 365 GCC High and Office 365 DoD are paired with Microsoft Entra ID in Azure Government.")),
        rule("cross-cloud.gcc-with-azure-government", 'Tenant and Azure subscription are in different clouds', {"tenant": ["gcc"], "azure": ["government"]}, "cross-cloud",
             "Your Microsoft 365 tenant lives in commercial Entra ID, but your Azure subscription is in Azure Government. "
             "A token from one cloud is rejected by the other, so every call across that line needs an app registration "
             "and credentials in the cloud being called. A managed identity in Azure Government can't sign in to your GCC tenant.",
             "graph-deployments", "microsoft-graph-and-graph-explorer-service-root-endpoints", tokens),
        rule("cross-cloud.gcchigh-with-azure-commercial", 'Tenant and Azure subscription are in different clouds', {"tenant": ["gcchigh", "dod"], "azure": ["commercial"]}, "cross-cloud",
             "Your Microsoft 365 tenant lives in Entra ID in Azure Government, but your Azure subscription is in commercial Azure. "
             "A token from one cloud is rejected by the other, so every call across that line needs an app registration "
             "and credentials in the cloud being called.",
             "graph-deployments", "microsoft-graph-and-graph-explorer-service-root-endpoints", tokens),
        rule("support.gcc-worldwide-terms", 'GCC support has no location or citizenship assurances', {"tenant": ["gcc"]}, "note",
             "GCC support runs on worldwide terms: Microsoft gives no assurances about where support agents are or what "
             "citizenship they hold. Background checks apply only to staff who can reach customer content.",
             "gcc-sd", "office-365-government-gcc-customer-support",
             gcc.quote("office-365-government-gcc-customer-support",
                       "Office 365 GCC customer support is provided under the same terms and conditions offered to Worldwide versions of Office 365, including no support agent physical location or citizenship assurances.")),
        rule("network.power-platform-gov-to-commercial-azure", 'Power Platform calls into commercial Azure cross clouds', {"tenant": ["gcc", "gcchigh"], "azure": ["commercial"],
             "uses": ["power-apps/", "power-automate/", "power-platform/", "dataverse/", "power-pages/", "copilot-studio/", "ai-builder/"]},
             "cross-cloud",
             "Power Platform for GCC and GCC High runs in Azure Government, so calls from your flows and apps to commercial "
             "Azure services cross clouds. If a service sits behind a firewall (Azure SQL, for example), the firewall must "
             "allow the Azure Government IP ranges for AzureCloud.usgovtexas and AzureCloud.usgovvirginia.",
             "pa-usgov", "connectivity-between-power-apps-us-government-and-public-azure-cloud-services",
             pa.quote("connectivity-between-power-apps-us-government-and-public-azure-cloud-services",
                      "cross-cloud networking is different and requires opening specific firewall rules to communicate between services")),
        rule("network.azure-ml-gov-firewall-hosts", 'Azure Machine Learning in Azure Government needs its own firewall hosts', {"azure": ["government"], "uses": ["azure-ml/"]}, "note",
             "Azure Machine Learning in Azure Government needs usgovvirginia.api.ml.azure.us or usgovarizona.api.ml.azure.us "
             "open in your firewall, depending on the region.",
             "aml-parity", "other-azure-government-limitations",
             PAGES["aml-parity"].quote("other-azure-government-limitations", "For Virginia use: usgovvirginia.api.ml.azure.us")),
        rule("unverified.entra-logs-gcc-to-gov-sentinel", 'Entra ID logs from a GCC tenant into Sentinel in Azure Government', {"tenant": ["gcc"], "azure": ["government"],
             "uses": ["sentinel/connector/entra-id"]}, "cross-cloud",
             "Your tenant's Entra ID is in commercial Azure, and your Sentinel workspace is in Azure Government. "
             "Microsoft's tables list the Entra ID connector in both clouds, but none covers sending a commercial tenant's "
             "sign-in logs to an Azure Government workspace. Test it before you depend on it.",
             "security-fa", "microsoft-purview-data-connectors",
             sfa.quote("microsoft-purview-data-connectors", "Office 365 GCC is paired with Microsoft Entra ID in Azure."),
             confidence="unverified"),
    ]


# ---------------------------------------------------------------- endpoints
AZGOV = [
    # (public host as written in Microsoft's table, service label, plane)
    ("botframework.com", "Azure Bot Service", "azure"),
    ("cognitiveservices.azure.com", "Azure AI services (Language, Vision, Document Intelligence and others)", "azure"),
    ("openai.azure.com", "Azure OpenAI", "azure"),
    ("azurehdinsight.net", "Azure HDInsight", "azure"),
    ("servicebus.windows.net", "Service Bus, Event Hubs and Notification Hubs", "azure"),
    ("batch.azure.com", "Azure Batch", "azure"),
    ("cloudapp.net", "Cloud Services", "azure"),
    ("cloudapp.azure.com", "Azure Service Fabric and VM DNS names", "azure"),
    ("azurecr.io", "Azure Container Registry", "azure"),
    ("redis.cache.windows.net", "Azure Cache for Redis", "azure"),
    ("documents.azure.com", "Azure Cosmos DB", "azure"),
    ("mariadb.database.azure.com", "Azure Database for MariaDB", "azure"),
    ("mysql.database.azure.com", "Azure Database for MySQL", "azure"),
    ("postgres.database.azure.com", "Azure Database for PostgreSQL", "azure"),
    ("database.windows.net", "Azure SQL Database", "azure"),
    ("login.microsoftonline.com", "Microsoft Entra ID sign-in", "identity"),
    ("certauth.login.microsoftonline.com", "Microsoft Entra ID certificate sign-in", "identity"),
    ("passwordreset.microsoftonline.com", "Microsoft Entra ID password reset", "identity"),
    ("azure-devices.net", "Azure IoT Hub", "azure"),
    ("atlas.microsoft.com", "Azure Maps", "azure"),
    ("azure-automation.net", "Azure Automation", "azure"),
    ("{region}.in.applicationinsights.azure.com", "Application Insights ingestion", "azure"),
    ("mms.microsoft.com", "Log Analytics workspace portal", "azure"),
    ("ods.opinsights.azure.com", "Log Analytics data collector API", "azure"),
    ("oms.opinsights.azure.com", "Log Analytics agent endpoint", "azure"),
    ("portal.loganalytics.io", "Log Analytics portal", "azure"),
    ("api.loganalytics.io", "Log Analytics query API", "azure"),
    ("adx.monitor.azure.com", "Azure Monitor Data Explorer queries", "azure"),
    ("management.azure.com", "Azure Resource Manager", "azure"),
    ("gallery.azure.com", "Azure gallery", "azure"),
    ("portal.azure.com", "Azure portal", "identity"),
    ("hypervrecoverymanager.windowsazure.com", "Azure Site Recovery", "azure"),
    ("backup.windowsazure.com", "Azure Backup", "azure"),
    ("blob.core.windows.net", "Azure Blob Storage", "azure"),
    ("queue.core.windows.net", "Azure Queue Storage", "azure"),
    ("table.core.windows.net", "Azure Table Storage", "azure"),
    ("file.core.windows.net", "Azure Files", "azure"),
    ("trafficmanager.net", "Traffic Manager", "azure"),
    ("vault.azure.net", "Azure Key Vault", "azure"),
    ("managedhsm.azure.net", "Azure Key Vault Managed HSM", "azure"),
    ("azure-api.net", "API Management gateway", "azure"),
    ("management.azure-api.net", "API Management management endpoint", "azure"),
    ("portal.azure-api.net", "API Management developer portal", "azure"),
    ("azconfig.io", "Azure App Configuration", "azure"),
    ("azurewebsites.net", "App Service and Azure Functions", "azure"),
    ("search.windows.net", "Azure AI Search", "azure"),
]


def build_endpoints():
    p = PAGES["azgov-compare"]
    rows = [c for c in p.section_rows("guidance-for-developers") if len(c) >= 4 and c[0] != "Service category"]
    out = []
    for public, label, plane in AZGOV:
        hits = [c for c in rows if c[2] == public]
        if not hits:
            sys.exit(f"azgov: no row for {public}")
        govs = {c[3].split(" / ")[0].strip() for c in hits}
        if len(govs) != 1:
            sys.exit(f"azgov: {public} maps to {govs}")
        gov = govs.pop()
        com_host, gov_host = public.replace("{region}.", ""), gov.replace("{region}.", "")
        out.append(endpoint("endpoint." + re.sub(r"[^a-z0-9]+", "-", com_host).strip("-"),
                            label, plane, {"commercial": com_host, "government": gov_host},
                            "azgov-compare", "guidance-for-developers", cells(hits[0])))

    gd = PAGES["graph-deployments"]
    sec = "microsoft-graph-and-graph-explorer-service-root-endpoints"
    g_world = gd.row(sec, "Microsoft Graph global service")
    g_high = gd.row(sec, "Microsoft Graph for US Government L4 (GCC High)")
    g_dod = gd.row(sec, "Microsoft Graph for US Government L5 (DOD)")
    gd.quote(sec, "If you're working in a Microsoft 365 GCC environment, continue using the worldwide endpoints: https://portal.azure.com and https://graph.microsoft.com.")
    host = lambda u: re.sub(r"^https?://", "", u).strip("/")
    out.append(endpoint("endpoint.microsoft-graph", "Microsoft Graph", "m365",
                        {"commercial": host(g_world[1]), "gcc": host(g_world[1]), "gcchigh": host(g_high[1]), "dod": host(g_dod[1])},
                        "graph-deployments", sec, " ; ".join(cells(c[:2]) for c in (g_world, g_high, g_dod))))

    def tiers(cell):
        found = {}
        for url, tier in re.findall(r"https?://(\S+?)/?\s*\((GCC High|GCC|DoD)\)", cell):
            found[{"GCC": "gcc", "GCC High": "gcchigh", "DoD": "dod"}[tier]] = url.split("/")[0]
        assert set(found) == {"gcc", "gcchigh", "dod"}, cell
        return found

    pp = [
        ("pa-usgov", "power-apps-us-government-service-urls", "https://make.powerapps.com", "Power Apps maker portal", "endpoint.power-apps-maker"),
        ("pauto-usgov", "power-automate-us-government-service-urls", "https://make.powerautomate.com", "Power Automate maker portal", "endpoint.power-automate-maker"),
        ("pauto-usgov", "power-automate-us-government-service-urls", "https://flow.microsoft.com", "Power Automate (classic portal)", "endpoint.power-automate-flow"),
        ("pauto-usgov", "power-automate-us-government-service-urls", "https://admin.powerplatform.microsoft.com/", "Power Platform admin center", "endpoint.power-platform-admin"),
    ]
    for key, sec, first, label, eid in pp:
        c = PAGES[key].row(sec, first)
        hosts = {"commercial": host(first)} | tiers(c[1])
        out.append(endpoint(eid, label, "m365", hosts, key, sec, cells(c)))

    dv = PAGES["dv-regions"]
    dv_rows = dv.section_rows("ms--in-this-article")[1:]
    commercial = [c[1] for c in dv_rows if c[0] not in ("GCC", "GCC High", "CHN", "DEU")]
    gcc_dv = dv.row("ms--in-this-article", "GCC")[1]
    high_dv = dv.row("ms--in-this-article", "GCC High")[1]
    pa_net = " ".join(t for s, t in PAGES["pa-usgov"].text if s == "power-apps-us-government-service-urls")
    assert "*.crm.appsplatform.us (DoD)" in pa_net
    out.append(endpoint("endpoint.dataverse", "Dataverse environment URL", "m365",
                        {"commercial": commercial, "gcc": gcc_dv, "gcchigh": high_dv, "dod": "crm.appsplatform.us"},
                        "dv-regions", "ms--in-this-article",
                        f"NAM | {commercial[0]} ; GCC | {gcc_dv} ; GCC High | {high_dv} ; DoD: *.crm.appsplatform.us (Power Apps US Government network list)"))

    pb = PAGES["pbi-gov"]
    sec = "sign-in-to-power-bi-for-us-government"
    pb_hosts = {}
    for tier, k in (("Commercial version", "commercial"), ("GCC", "gcc"), ("GCC High", "gcchigh"), ("DoD", "dod")):
        hit = [t for s, t in pb.text if s == sec and t.startswith(f"{tier}: ")]
        assert len(hit) == 1, (tier, hit)
        pb_hosts[k] = host(hit[0].split(": ", 1)[1])
    out.append(endpoint("endpoint.power-bi-app", "Power BI service", "m365", pb_hosts, "pbi-gov", sec,
                        " ; ".join(f"{k}: {v}" for k, v in pb_hosts.items())))
    api = [c for c in pb.section_rows("power-bi-urls-for-general-site-usage") if c[0] == "Back-end APIs" and "api.powerbigov.us" in c[1]]
    assert len(api) == 1, api
    api = api[0]
    api_hosts = dict((({"GCC": "gcc", "GCC High": "gcchigh", "DoD": "dod"}[t]), h)
                     for t, h in re.findall(r"(GCC High|GCC|DoD): ([\w.-]+)", api[1]))
    assert set(api_hosts) == {"gcc", "gcchigh", "dod"}, api
    out.append(endpoint("endpoint.power-bi-api", "Power BI back-end APIs (US Government tiers)", "m365", api_hosts,
                        "pbi-gov", "power-bi-urls-for-general-site-usage", cells(api)))

    sp = PAGES["scc-ps"]
    sec = "step-2-connect-and-authenticate"
    sp.quote(sec, "The required value https://ps.compliance.protection.outlook.com/powershell-liveid/ is also the default value")
    sp.quote(sec, "Microsoft 365 GCC High: ConnectionUri: https://ps.compliance.protection.office365.us/powershell-liveid/")
    sp.quote(sec, "Microsoft 365 DoD: ConnectionUri: https://l5.ps.compliance.protection.office365.us/powershell-liveid/")
    out.append(endpoint("endpoint.security-compliance-powershell", "Security & Compliance PowerShell", "m365",
                        {"commercial": "ps.compliance.protection.outlook.com", "gcc": "ps.compliance.protection.outlook.com",
                         "gcchigh": "ps.compliance.protection.office365.us", "dod": "l5.ps.compliance.protection.office365.us"},
                        "scc-ps", sec, "Microsoft 365 or Microsoft 365 GCC: default ; GCC High and DoD ConnectionUri values"))
    return out


# ---------------------------------------------------------------- emit
def fact(fid, feature, name, by, status, source, anchor, row, note=None, confidence="high", **extra):
    d = {"id": fid, "feature": feature, "name": name, "by": by, "status": status}
    d.update({k: v for k, v in extra.items() if v is not None})
    if note:
        d["note"] = note
    d.update({"source": source, "anchor": anchor, "row": row, "confidence": confidence})
    return d


def rule(fid, title, when, group, says, source, anchor, quote, confidence="high"):
    return {"id": fid, "title": title, "when": when, "group": group, "says": says, "source": source, "anchor": anchor,
            "quote": quote, "confidence": confidence}


def endpoint(eid, service, plane, hosts, source, anchor, row):
    return {"id": eid, "service": service, "plane": plane, "hosts": hosts, "source": source, "anchor": anchor, "row": row}


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
    src_lines = ["# Microsoft pages the facts cite. page_updated is the page's own updated_at date;",
                 "# checked is when govgap last read the page and confirmed every row it cites.", "sources:"]
    for k, s in SOURCES.items():
        src_lines.append(f"  {k}:")
        for sk in ("title", "url", "page_updated", "checked"):
            src_lines.append(f"    {sk}: {scalar(s[sk]) if sk != 'url' else json.dumps(s[sk])}")
    (OUT / "sources.yaml").write_text("\n".join(src_lines) + "\n", encoding="utf-8", newline="\n")
    hdr = "# Generated from Microsoft's own tables, then reviewed. Each row is the source text the status came from."
    write("defender-for-cloud.yaml", hdr, "facts", build_defender())
    write("sentinel.yaml", hdr, "facts", build_connectors() + build_sentinel())
    write("azure-ml.yaml", hdr, "facts", build_aml())
    write("azure-ai.yaml", hdr, "facts", build_language() + build_aoai())
    write("power-platform.yaml", hdr + "\n# Columns in the PDF: GCC (IL2), GCC High (IL4), DoD (IL5).", "facts", build_bap())
    write("rules.yaml", "# Stack-level rules: they fire on tenant and Azure cloud, not on a single feature.", "rules", build_rules())
    write("endpoints.yaml", "# Commercial to US Government host map used by `govgap scan`.", "endpoints", build_endpoints())


if __name__ == "__main__":
    main()
