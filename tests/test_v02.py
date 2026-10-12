"""Tests for 0.2.0: the Learn page reader, verify, Microsoft 365 data, roadmap, explain, SARIF and MCP."""
import datetime as dt
import hashlib
import io
import json
import re

import pytest

from fairfax import cli, dataset, explain, learn, mcp, sarif, verify
from fairfax.check import Plan, check
from fairfax.scan import HostIndex, scan_text

TODAY = dt.date(2026, 10, 12)


@pytest.fixture(scope="module")
def ds():
    return dataset.load()


def run(capsys, *argv):
    code = cli.main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


# ---------------------------------------------------------------- the page reader
PAGE = """<html><head><meta name="updated_at" content="2026-09-17 10:00 AM"></head><body><main>
<h1 id="t">Availability</h1>
<h2 id="parity">Feature parity</h2>
<p>These are the known gaps:</p>
<table>
<tr><th>Feature name</th><th>GCC</th><th>GCC High</th></tr>
<tr><td>Threat Experts</td><td><img src="media/svg/check-no.svg"> On engineering backlog</td><td><img src="media/svg/check-yes.svg"></td></tr>
<tr><td>Office IRM</td><td></td><td></td></tr>
<tr><td>- Office 365 GCC</td><td>GA</td><td>-</td></tr>
<tr><td>- Office 365 GCC High</td><td>-</td><td>GA</td></tr>
<tr><td>Dynamics 365</td><td></td><td></td></tr>
<tr><td>- Office 365 GCC</td><td>Preview</td><td>-</td></tr>
<tr><td>Records management</td><td>Disposition review</td><td>Available</td></tr>
<tr><td></td><td>Proof of disposal</td><td>In development</td></tr>
<tr><td>Long cell</td><td>The following capabilities support GCC High only:<br>- Cloud PKI</td><td></td></tr>
</table>
<ul><li>Report inaccuracy</li></ul>
</main></body></html>"""


@pytest.fixture(scope="module")
def page():
    return learn.parse(PAGE, "https://example.com/page")


def test_reader_keeps_sections_icons_and_dates(page):
    assert page.title == "Availability" and page.updated == "2026-09-17"
    rows = page.section_rows("parity")
    assert rows[1] == ["Threat Experts", "[check-no] On engineering backlog", "[check-yes]"]
    assert rows[-1][1] == "The following capabilities support GCC High only: / - Cloud PKI"
    assert ("parity", "Report inaccuracy") in page.text


def test_reader_finds_rows_runs_groups_and_quotes(page):
    assert page.find("parity", "Threat Experts | [check-no] On engineering backlog | [check-yes]")
    assert page.find("parity", "Threat Experts | [check-no] On engineering backlog")  # a run of cells
    assert page.find("parity", "Office IRM: Office 365 GCC | GA | - ; Office 365 GCC High | - | GA")
    assert page.find("parity", "Records management: Proof of disposal | In development")
    assert page.find("parity", "These are the known gaps: ; Report inaccuracy")
    assert page.find("parity", "The following capabilities support GCC High only")  # inside a long cell
    assert not page.find("other-section", "Report inaccuracy")


def test_reader_doesnt_borrow_rows_from_another_group(page):
    # Dynamics 365's GCC row says Preview; Office IRM's says GA. A change must not hide behind the other group.
    assert not page.find("parity", "Office IRM: Office 365 GCC | Preview | -")
    assert not page.find("parity", "Records management: Proof of disposal | Available")


# ---------------------------------------------------------------- verify
def tiny_dataset(tmp_path, row, extra=""):
    (tmp_path / "sources.yaml").write_text(
        "sources:\n  p:\n    title: Page\n    url: https://example.com/page\n    page_updated: 2026-09-17\n"
        "    checked: 2026-10-12\n" + extra)
    (tmp_path / "f.yaml").write_text(
        "facts:\n  - id: x.threat-experts\n    feature: x/threat-experts\n    name: Threat Experts\n    by: tenant\n"
        "    status: {gcc: backlog, gcchigh: available}\n    source: p\n    anchor: parity\n"
        f"    row: {json.dumps(row)}\n    confidence: high\n")
    return dataset.load(tmp_path)


def test_verify_matches_and_reports_changes(tmp_path):
    good = tiny_dataset(tmp_path, "Threat Experts | [check-no] On engineering backlog | [check-yes]")
    res = verify.verify(good, fetch=lambda url: PAGE.encode())
    assert [r.state for r in res] == ["ok"] and verify.exit_code(res) == 0
    stale = tiny_dataset(tmp_path, "Threat Experts | [check-yes] | [check-yes]")
    res = verify.verify(stale, fetch=lambda url: PAGE.encode())
    assert res[0].state == "changed" and verify.exit_code(res) == 1
    assert res[0].missing[0].nearest == "Threat Experts | [check-no] On engineering backlog | [check-yes]"


def test_verify_reports_unreachable_pages_without_failing_the_run(tmp_path):
    ds = tiny_dataset(tmp_path, "Threat Experts | [check-yes] | [check-yes]")

    def down(url):
        raise OSError("connection refused")
    res = verify.verify(ds, fetch=down)
    assert res[0].state == "unreachable" and verify.exit_code(res) == 2


def test_verify_compares_a_pdf_by_hash(tmp_path):
    body = b"%PDF-1.7 the parity table"
    extra = ("  pdf:\n    title: PDF\n    url: https://example.com/a.pdf\n    page_updated: 2026-06-15\n"
             f"    checked: 2026-10-12\n    sha256: {hashlib.sha256(body).hexdigest()}\n")
    ds = tiny_dataset(tmp_path, "Threat Experts | [check-no] On engineering backlog | [check-yes]", extra)
    pages = {"https://example.com/page": PAGE.encode(), "https://example.com/a.pdf": body}
    assert verify.exit_code(verify.verify(ds, fetch=pages.__getitem__)) == 0
    pages["https://example.com/a.pdf"] = body + b" (updated)"
    res = {r.source.key: r for r in verify.verify(ds, fetch=pages.__getitem__)}
    assert res["pdf"].state == "changed"


def test_verify_checks_roadmap_items_against_the_api(ds):
    cites = verify.citations(ds)["m365-roadmap"]
    items = [{"id": r.id, "title": r.title, "status": r.status, "cloudInstances": list(r.clouds),
              "generalAvailabilityDate": r.ga, "modified": "2026-10-01T00:00:00Z"} for r in ds.roadmap]
    body = json.dumps({"value": items}).encode()
    src = ds.sources["m365-roadmap"]
    assert verify.check_page(src, cites, lambda url: body).state == "ok"
    items[0]["generalAvailabilityDate"] = "2027-06"
    cites = verify.citations(ds)["m365-roadmap"]
    result = verify.check_page(src, cites, lambda url: json.dumps({"value": items}).encode())
    assert result.state == "changed" and result.missing[0].nearest.endswith("| 2027-06")


def test_cli_verify_uses_the_same_fetch(monkeypatch, capsys):
    monkeypatch.setattr(learn, "fetch", lambda url: (_ for _ in ()).throw(OSError("offline")))
    code, out, _ = run(capsys, "verify", "--source", "teams-sd")
    assert code == 2 and "UNREACHABLE" in out and "offline" in out
    code, _, err = run(capsys, "verify", "--source", "nope")
    assert code == 2 and "unknown source" in err


# ---------------------------------------------------------------- Microsoft 365 data, parsed back from the rows
YES_NO = {"Yes": "available", "No": "not-available", "Not currently available": "not-available"}
STATUS_WORDS = {"Available": "available", "In development": "in-development", "On engineering backlog": "backlog",
                "Public Preview": "preview", "Rolling out": "rolling-out"}
ICON_WORDS = {"[check-yes]": "available", "[check-no]": "not-available",
              "[check-no] On engineering backlog": "backlog"}
TICKS = {"✔️": "available", "✔": "available", "❌": "not-available"}


def word(cell):
    return re.sub(r"\d+(,\d+)*$", "", cell.removesuffix(" / See note following this table"))


def test_m365_statuses_match_microsofts_row_text(ds):
    checked = 0
    for f in ds.facts:
        key, cells = f.source.key, [c.strip() for c in f.row.split(" | ")]
        if key == "copilot-sd":
            want = [YES_NO[word(c)] for c in cells[2:5]]
        elif key == "teams-sd":
            want = [YES_NO[word(c)] for c in cells[3:6]]
        elif key == "exo-gov":
            want = [YES_NO[word(c)] for c in cells[1:4]]
        elif key == "teams-apps":
            want = [TICKS[c] for c in cells[1:4]]
        elif key in ("mde-gov", "xdr-gov") and f.feature.split("/")[0] != "defender-vulnerability-management" \
                or f.id.startswith("defender-vulnerability-management.co") or f.id.endswith("premium"):
            want = [ICON_WORDS[word(c)] for c in cells[1:4]]
        elif key.startswith("purview-"):
            tenant = key.removeprefix("purview-")
            assert f.status == {tenant: STATUS_WORDS[word(cells[-1])]}, f.id
            checked += 1
            continue
        else:
            continue
        assert [f.status[t] for t in ("gcc", "gcchigh", "dod")] == want, f.id
        checked += 1
    assert checked >= 820


def test_intune_and_sharepoint_statuses_follow_microsofts_wording(ds):
    for f in ds.facts:
        if f.source.key == "intune-gov" and f.anchor.startswith("intune-features-planned"):
            assert f.status == {"gcchigh": "planned", "dod": "planned"}, f.id
        elif f.source.key == "intune-gov" and f.anchor.startswith("intune-features-not-available"):
            assert f.row.endswith("| n/a") and set(f.status.values()) == {"not-available"}, f.id
        elif f.source.key in ("spo-gov", "odb-gov"):
            missing = re.search(r"isn't|aren't|not available|currently disabled|won't work", f.row)
            assert missing, f.id
            clouds = {"gcc": "GCC", "gcchigh": "GCC High", "dod": "DoD"}
            named = [t for t, n in clouds.items() if re.search(rf"\b{n}\b(?! High)", f.row)]
            if named:  # the sentence names its clouds: the statuses must be exactly those
                assert sorted(f.status) == sorted(named), f.id


def test_every_feature_has_one_by_and_known_statuses(ds):
    for key, facts in ds.features().items():
        assert len({f.by for f in facts}) == 1, key
        assert len(facts) == len({k for f in facts for k in f.status}) or len(facts) == 1, key


# ---------------------------------------------------------------- check with per-cloud pages and the roadmap
def test_a_feature_cited_per_cloud_uses_that_clouds_page(ds):
    for tenant in ("gcc", "gcchigh", "dod"):
        r = check(ds, Plan(tenant, None, ["purview/ediscovery/hold-reports"]), TODAY)
        blocked = r.groups()["blocked"]
        assert len(blocked) == 1 and blocked[0].id.endswith("." + tenant)
        assert "Microsoft lists it as in development." in blocked[0].says


def test_roadmap_notes_flag_passed_months_and_disagreements(ds):
    r = check(ds, Plan("gcchigh", None, ["m365-copilot/copilot-analytics", "m365-copilot/edit-in-office-apps"]), TODAY)
    notes = {f.feature: f.roadmap for f in r.groups()["blocked"]}
    assert "That month has passed" in notes["m365-copilot/copilot-analytics"][0]["says"]
    assert notes["m365-copilot/edit-in-office-apps"][0]["ga"] == "2026-10"
    dod = check(ds, Plan("dod", None, ["m365-copilot/declarative-agents"]), TODAY).groups()["blocked"][0]
    assert "says it has launched while the table says it's missing" in dod.roadmap[0]["says"]
    gcc = check(ds, Plan("gcc", None, ["m365-copilot/copilot-analytics"]), TODAY)
    assert gcc.groups()["blocked"] == []  # available in GCC: no roadmap note needed


def test_a_page_that_covers_some_clouds_says_only_those(ds):
    r = check(ds, Plan("gcchigh", None, ["intune/remediations"]), TODAY)
    assert r.groups()["blocked"][0].elsewhere == "Microsoft lists it for none of GCC High or DoD."
    gcc = check(ds, Plan("gcc", None, ["intune/remediations"]), TODAY)
    note = next(f for f in gcc.groups()["note"] if f.feature == "intune/remediations")
    assert "doesn't cover it in GCC" in note.says


# ---------------------------------------------------------------- explain
def test_explain_by_code_message_and_wording(ds):
    r = explain.explain(ds, "AADSTS900439", "gcchigh", None)
    assert [x.error.code for x in r.matches] == ["AADSTS900439"]
    assert r.matches[0].hosts == [("login.microsoftonline.us", "a GCC High tenant")]
    msg = "AADSTS90002: Tenant 'abc' not found. Trace ID: 1"
    assert [x.error.code for x in explain.explain(ds, msg).matches] == ["AADSTS90002"]
    words = explain.explain(ds, "Confidential Client isn't supported in Cross Cloud request")
    assert sorted(x.error.code for x in words.matches) == ["AADSTS900382", "AADSTS900432"]
    assert explain.explain(ds, "AADSTS50126").unknown == ["AADSTS50126"]


def test_cli_explain_exit_codes(capsys):
    code, out, _ = run(capsys, "explain", "AADSTS900439", "--tenant", "dod")
    assert code == 0 and "USGClientNotSupportedOnPublicEndpoint" in out and "for a DoD tenant" in out
    code, out, _ = run(capsys, "explain", "AADSTS50126")
    assert code == 2 and "doesn't decode" in out
    code, out, _ = run(capsys, "explain", "--list")
    assert code == 0 and out.count("AADSTS") >= 9
    code, out, _ = run(capsys, "explain", "900439", "--format", "json")
    assert code == 0 and json.loads(out)["matches"][0]["code"] == "AADSTS900439"


# ---------------------------------------------------------------- SARIF
def test_scan_sarif_points_at_the_line(capsys, tmp_path):
    f = tmp_path / "settings.py"
    f.write_text('A = 1\nAUTH = "https://login.microsoftonline.com/x"\n', encoding="utf-8")
    code, out, _ = run(capsys, "scan", str(f), "--tenant", "gcchigh", "--format", "sarif")
    log = json.loads(out)
    assert code == 1 and log["version"] == "2.1.0"
    result = log["runs"][0]["results"][0]
    assert result["level"] == "error" and result["ruleId"] == "endpoint.login-microsoftonline-com"
    region = result["locations"][0]["physicalLocation"]["region"]
    assert region == {"startLine": 2, "startColumn": 17, "endColumn": 42}  # login. starts after https://
    assert {r["id"] for r in log["runs"][0]["tool"]["driver"]["rules"]} == {result["ruleId"]}


def test_check_sarif_points_at_the_plan_line(ds, tmp_path):
    plan = tmp_path / "plan.yaml"
    plan.write_text("tenant: gcchigh\nazure: government\nfeatures:\n  - teams/channels-shared\n", encoding="utf-8")
    from fairfax.check import load_plan
    log = json.loads(sarif.check_sarif(check(ds, load_plan(plan), TODAY)))
    results = {r["ruleId"]: r for r in log["runs"][0]["results"]}
    region = results["teams/channels-shared"]["locations"][0]["physicalLocation"]["region"]
    assert results["teams/channels-shared"]["level"] == "error" and region["startLine"] == 4


# ---------------------------------------------------------------- MCP
def call(server, method, params=None, mid=1):
    msg = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        msg["params"] = params
    return server.handle(msg)


def test_mcp_handshake_and_tools(ds):
    s = mcp.Server(ds, TODAY)
    init = call(s, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t"}})
    assert init["result"]["protocolVersion"] == "2025-03-26" and "tools" in init["result"]["capabilities"]
    assert call(s, "initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"] == "2025-06-18"
    assert s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    names = [t["name"] for t in call(s, "tools/list")["result"]["tools"]]
    assert names == ["find_features", "check_plan", "scan_code", "explain_error"]
    r = call(s, "tools/call", {"name": "check_plan", "arguments": {"tenant": "dod", "features": ["teams/webinars"]}})
    assert r["result"]["isError"] is False and "## Blocked (1)" in r["result"]["content"][0]["text"]
    r = call(s, "tools/call", {"name": "scan_code", "arguments": {"text": "graph.microsoft.com", "tenant": "gcchigh"}})
    assert "graph.microsoft.us" in r["result"]["content"][0]["text"]
    r = call(s, "tools/call", {"name": "check_plan", "arguments": {"tenant": "gcc", "features": ["no/such"]}})
    assert r["result"]["isError"] is True
    assert call(s, "tools/call", {"name": "nope"})["error"]["code"] == -32602
    assert call(s, "resources/list")["error"]["code"] == -32601


def test_mcp_serve_reads_and_writes_lines(monkeypatch, ds):
    monkeypatch.setattr(mcp.dataset_mod, "load", lambda: ds)
    lines = [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}), "not json", ""]
    out = io.BytesIO()
    mcp.serve(io.BytesIO("\n".join(lines).encode()), out)
    replies = [json.loads(x) for x in out.getvalue().decode().splitlines()]
    assert replies == [{"jsonrpc": "2.0", "id": 1, "result": {}},
                       {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}]


def test_scan_text_matches_file_scanning(ds):
    hits = scan_text("x = 'https://api.security.microsoft.com/api/alerts'", "a.py", HostIndex(ds.endpoints),
                     "gcc", None)
    assert [(h.found, h.expected) for h in hits] == [("api.security.microsoft.com", ["api-gcc.security.microsoft.us"])]
