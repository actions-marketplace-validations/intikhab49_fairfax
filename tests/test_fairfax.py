import datetime as dt
import json
from pathlib import Path

import pytest

from fairfax import cli, dataset
from fairfax.check import Plan, check, load_plan, PlanError
from fairfax.scan import scan

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "field-inspections"
TODAY = dt.date(2026, 10, 11)


@pytest.fixture(scope="module")
def ds():
    return dataset.load()


def groups(report):
    return {g: sorted(f.feature or f.id for f in items) for g, items in report.groups().items()}


def run(capsys, *argv):
    code = cli.main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


# ---------------------------------------------------------------- dataset
def test_dataset_is_large_cited_and_dated(ds):
    assert len(ds.facts) >= 60
    assert len(ds.endpoints) >= 40
    for item in [*ds.facts, *ds.rules, *ds.endpoints]:
        assert item.url.startswith("https://")
        assert item.source.checked == "2026-10-11"
    for f in ds.facts:
        assert f.row.strip()


PDF_WORDS = {"Available": "ga", "Available (CSS ticket)": "ga", "Not Available": "not-available",
             "Public Preview": "preview", "Private Preview": "private-preview", "Limited": "limited",
             "No plans": "no-plans", "No Plans": "no-plans"}
TABLE_WORDS = {"GA": "ga", "Public Preview": "preview", "Not Available": "not-available"}


def test_status_matches_microsofts_row_text(ds):
    # A hand edit that changes a status without its row (or the reverse) should fail here.
    checked = 0
    for f in ds.facts:
        cells = [c.strip() for c in f.row.split("|")]
        if f.source.key == "bap":
            want = [PDF_WORDS.get(c, f"planned:{c}") for c in cells[1:]]
            assert [f.status[t] for t in ("gcc", "gcchigh", "dod")] == want, f.id
        elif f.anchor == "microsoft-defender-for-cloud":
            want = [TABLE_WORDS[c.split(" ")[0] if c.startswith("GA ") else c] for c in cells[1:]]
            assert [f.status["commercial"], f.status["government"]] == want, f.id
        else:
            continue
        checked += 1
    assert checked >= 90


def test_loader_rejects_a_bad_status(tmp_path):
    (tmp_path / "sources.yaml").write_text(
        "sources:\n  s:\n    title: t\n    url: https://example.com\n    page_updated: 2026-01-01\n    checked: 2026-01-01\n")
    (tmp_path / "f.yaml").write_text(
        "facts:\n  - id: a.b\n    feature: a/b\n    name: A\n    by: azure\n    status: {government: maybe}\n"
        "    source: s\n    anchor: x\n    row: r\n    confidence: high\n")
    with pytest.raises(dataset.DatasetError, match="unknown status"):
        dataset.load(tmp_path)


# ---------------------------------------------------------------- check
def test_example_plan(ds):
    r = check(ds, load_plan(EXAMPLE / "plan.yaml"), TODAY)
    g = groups(r)
    assert g["blocked"] == ["defender-for-cloud/ai-services", "power-automate/actionable-approval-emails",
                            "power-automate/mobile-ios", "sentinel/connector/teams"]
    assert "sentinel/scheduled-rules" in g["ok"]
    assert g["cross-cloud"] == []
    assert r.failed()


def test_gcc_tenant_with_gov_sentinel_is_cross_cloud(ds):
    gov = check(ds, Plan("gcc", "government", ["sentinel/connector/office-365"]), TODAY)
    assert groups(gov)["cross-cloud"] == ["cross-cloud.gcc-with-azure-government", "sentinel/connector/office-365"]
    assert not gov.failed() and gov.failed(strict=True)
    com = check(ds, Plan("gcc", "commercial", ["sentinel/connector/office-365"]), TODAY)
    assert groups(com)["ok"] == ["sentinel/connector/office-365"]
    assert groups(com)["cross-cloud"] == []


def test_retiring_feature_reports_both_findings(ds):
    r = check(ds, Plan("gcchigh", "government", ["ai-language/custom-text-classification"]), TODAY)
    g = groups(r)
    assert g["blocked"] == ["ai-language/custom-text-classification"]
    assert g["retiring"] == ["ai-language/custom-text-classification"]
    retiring = r.groups()["retiring"][0]
    assert "2029-03-31" in retiring.says and "Foundry" in retiring.says


def test_planned_eta_flags_a_passed_date(ds):
    r = check(ds, Plan("dod", "government", ["power-platform/customer-managed-key"]), TODAY)
    f = r.groups()["blocked"][0]
    assert "CY2026-H1" in f.says and "That date has passed" in f.says
    early = check(ds, Plan("dod", "government", ["power-platform/customer-managed-key"]), dt.date(2026, 3, 1))
    assert "That date has passed" not in early.groups()["blocked"][0].says


def test_missing_azure_cloud_becomes_a_note(ds):
    r = check(ds, Plan("gcc", None, ["defender-for-cloud/ai-services", "power-apps/test-studio"]), TODAY)
    assert groups(r)["note"] == ["defender-for-cloud/ai-services", "pairing.gcc-commercial-entra",
                                 "support.gcc-worldwide-terms"]
    assert groups(r)["blocked"] == ["power-apps/test-studio"]


def test_unverified_rule_is_labelled(ds):
    r = check(ds, Plan("gcc", "government", ["sentinel/connector/entra-id"]), TODAY)
    unverified = [f for f in r.findings if f.confidence == "unverified"]
    assert [f.id for f in unverified] == ["unverified.entra-logs-gcc-to-gov-sentinel"]


def test_unknown_feature_suggests(ds):
    r = check(ds, Plan("gcc", "commercial", ["sentinel/connector/team"]), TODAY)
    assert "sentinel/connector/teams" in r.unknown["sentinel/connector/team"]


def test_plan_validation(tmp_path):
    p = tmp_path / "plan.yaml"
    p.write_text("tenant: gcc-high\nfeatures: []\n")
    with pytest.raises(PlanError, match="tenant must be one of"):
        load_plan(p)
    p.write_text("tenant: gcc\nazure: government\nfeature: [a/b]\n")
    with pytest.raises(PlanError, match="unknown keys: feature"):
        load_plan(p)


# ---------------------------------------------------------------- scan
def write(tmp_path, text):
    f = tmp_path / "app.py"
    f.write_text(text, encoding="utf-8")
    return [str(tmp_path)]


def found(hits):
    return [(h.found, h.kind, h.expected) for h in hits]


def test_scan_gcc_high_flags_commercial_hosts(ds, tmp_path):
    paths = write(tmp_path, 'A = "https://login.microsoftonline.com/x"\nB = "https://kv1.vault.azure.net/"\n')
    hits, files = scan(paths, ds, "gcchigh", "government")
    assert files == 1
    assert found(hits) == [("login.microsoftonline.com", "wrong", ["login.microsoftonline.us"]),
                           ("kv1.vault.azure.net", "wrong", ["kv1.vault.usgovcloudapi.net"])]


def test_scan_gcc_keeps_worldwide_graph_but_not_commercial_dataverse(ds, tmp_path):
    paths = write(tmp_path, 'G = "https://graph.microsoft.com/v1.0"\nD = "https://org.crm4.dynamics.com"\n')
    hits, _ = scan(paths, ds, "gcc", "commercial")
    assert found(hits) == [("org.crm4.dynamics.com", "wrong", ["org.crm9.dynamics.com"])]


def test_scan_gcc_with_azure_government_marks_sign_in_for_checking(ds, tmp_path):
    paths = write(tmp_path, 'A = "https://login.microsoftonline.com/x"\n')
    hits, _ = scan(paths, ds, "gcc", "government")
    assert found(hits) == [("login.microsoftonline.com", "check", ["login.microsoftonline.us"])]


def test_scan_gov_tier_mixup_and_longest_suffix(ds, tmp_path):
    paths = write(tmp_path, 'P = "api.powerbigov.us"\nS = "l5.ps.compliance.protection.office365.us"\n')
    hits, _ = scan(paths, ds, "gcchigh", "government")
    assert found(hits) == [("api.powerbigov.us", "wrong", ["api.high.powerbigov.us"]),
                           ("l5.ps.compliance.protection.office365.us", "wrong",
                            ["ps.compliance.protection.office365.us"])]
    hits, _ = scan(paths, ds, "dod", "government")
    assert found(hits) == [("api.powerbigov.us", "wrong", ["api.mil.powerbigov.us"])]


def test_scan_ignore_marker_and_exclude(ds, tmp_path):
    paths = write(tmp_path, 'A = "https://graph.microsoft.com"  # fairfax: ignore\n')
    assert scan(paths, ds, "gcchigh", "government")[0] == []
    paths = write(tmp_path, 'A = "https://graph.microsoft.com"\n')
    assert scan(paths, ds, "gcchigh", "government", exclude=["*.py"])[0] == []


# ---------------------------------------------------------------- CLI
def test_cli_check_formats_and_exit_codes(capsys):
    plan = str(EXAMPLE / "plan.yaml")
    code, out, _ = run(capsys, "check", plan, "--today", "2026-10-11")
    assert code == 1 and "BLOCKED (4)" in out
    code, out, _ = run(capsys, "check", plan, "--format", "json", "--today", "2026-10-11")
    data = json.loads(out)
    assert data["summary"]["blocked"] == 4 and data["dataset"]["facts"] >= 60
    code, out, _ = run(capsys, "check", plan, "--format", "md", "--today", "2026-10-11")
    assert out.startswith("# fairfax check: Field inspection app") and "## Blocked (4)" in out


def test_cli_unknown_feature_exits_2(capsys, tmp_path):
    p = tmp_path / "plan.yaml"
    p.write_text("tenant: gcc\nazure: commercial\nfeatures: [power-apps/test-studios]\n")
    code, _, err = run(capsys, "check", str(p))
    assert code == 2 and "power-apps/test-studio" in err


def test_cli_scan_example(capsys):
    code, out, _ = run(capsys, "scan", str(EXAMPLE), "--plan", str(EXAMPLE / "plan.yaml"))
    assert code == 1 and "6 wrong-cloud endpoints and 0 to check" in out
    code, _, err = run(capsys, "scan", str(EXAMPLE))
    assert code == 2 and "--tenant" in err


def test_cli_facts_grep_and_stale(capsys):
    code, out, _ = run(capsys, "facts", "--grep", "actionable")
    assert code == 0 and out.startswith("power-automate/actionable-approval-emails")
    code, out, _ = run(capsys, "facts", "--stale", "90", "--today", "2026-11-01")
    assert code == 0 and "within the last 90 days" in out
    code, out, _ = run(capsys, "facts", "--stale", "90", "--today", "2027-02-01")
    assert code == 1 and "learn.microsoft.com" in out
