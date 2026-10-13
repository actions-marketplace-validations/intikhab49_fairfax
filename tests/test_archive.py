"""Tests for 0.2.2: pages that disappear, and the Wayback Machine copies that keep citations checkable."""
import importlib.util
import json
import urllib.error
from dataclasses import replace
from pathlib import Path

import pytest

from fairfax import cli, dataset, learn, render, verify
from fairfax.check import Plan, check

ROW = "Threat Experts | [check-no] On engineering backlog | [check-yes]"
PAGE = ('<html><body><main><h2 id="parity">Parity</h2><table><tr><th>Feature</th><th>GCC</th><th>GCC High</th></tr>'
        '<tr><td>Threat Experts</td><td><img src="media/svg/check-no.svg"> On engineering backlog</td>'
        '<td><img src="media/svg/check-yes.svg"></td></tr></table></main></body></html>').encode()
SNAP = "https://web.archive.org/web/20261012140947/https://example.com/page"


def tiny(tmp_path, archived=None):
    (tmp_path / "sources.yaml").write_text(
        "sources:\n  p:\n    title: Page\n    url: https://example.com/page\n    page_updated: 2026-09-17\n"
        "    checked: 2026-10-12\n" + (f'    archived: "{archived}"\n' if archived else ""))
    (tmp_path / "f.yaml").write_text(
        "facts:\n  - id: x.threat-experts\n    feature: x/threat-experts\n    name: Threat Experts\n    by: tenant\n"
        "    status: {gcc: backlog, gcchigh: available}\n    source: p\n    anchor: parity\n"
        f"    row: {json.dumps(ROW)}\n    confidence: high\n")
    return dataset.load(tmp_path)


def http(code):
    def fetch(url):
        raise urllib.error.HTTPError(url, code, "status", {}, None)
    return fetch


# ---------------------------------------------------------------- a page that's gone
def test_a_deleted_page_fails_the_run_and_points_at_the_archived_copy(tmp_path):
    for code in (404, 410):
        res = verify.verify(tiny(tmp_path, SNAP), fetch=http(code))
        assert res[0].state == "gone" and verify.exit_code(res) == 1
        assert SNAP in res[0].error
    text = render.verify_text(res)
    assert "GONE" in text and "1 gone" in text and SNAP in text
    md = render.verify_md(res)
    assert "| GONE |" in md and SNAP in md


def test_a_temporary_outage_is_still_only_a_warning(tmp_path):
    res = verify.verify(tiny(tmp_path), fetch=http(503))
    assert res[0].state == "unreachable" and verify.exit_code(res) == 2 and "HTTP 503" in res[0].error


def test_gone_wins_over_unreachable_in_the_exit_code(tmp_path):
    ds = tiny(tmp_path)
    results = verify.verify(ds, fetch=http(404)) + verify.verify(ds, fetch=http(503))
    assert verify.exit_code(results) == 1


# ---------------------------------------------------------------- archived copies
def test_archived_link_is_validated_and_has_a_raw_form(tmp_path):
    src = tiny(tmp_path, SNAP).sources["p"]
    assert src.archived_raw == "https://web.archive.org/web/20261012140947id_/https://example.com/page"
    assert tiny(tmp_path).sources["p"].archived_raw is None
    for bad in ("https://archive.ph/abc", "https://web.archive.org/web/2026/https://example.com/page"):
        with pytest.raises(dataset.DatasetError, match="archived must be"):
            tiny(tmp_path, bad)


def test_verify_archived_checks_the_snapshot_not_the_live_page(tmp_path):
    seen = []

    def fetch(url):
        seen.append(url)
        return PAGE
    res = verify.verify(tiny(tmp_path, SNAP), fetch=fetch, archived=True)
    assert res[0].state == "ok" and seen == ["https://web.archive.org/web/20261012140947id_/https://example.com/page"]
    res = verify.verify(tiny(tmp_path), fetch=fetch, archived=True)
    assert res[0].state == "gone" and "no archived copy" in res[0].error and verify.exit_code(res) == 1


def test_a_snapshot_that_lost_the_row_is_reported(tmp_path):
    res = verify.verify(tiny(tmp_path, SNAP), fetch=lambda url: PAGE.replace(b"check-no", b"check-yes"), archived=True)
    assert res[0].state == "changed"


def test_cli_verify_archived(monkeypatch, capsys):
    monkeypatch.setattr(learn, "fetch", http(404))
    assert cli.main(["verify", "--archived", "--source", "teams-sd"]) == 1
    assert "GONE" in capsys.readouterr().out


def test_findings_and_facts_carry_the_archived_copy(tmp_path):
    ds = tiny(tmp_path, SNAP)
    plan = Plan(path="p.yaml", name="t", tenant="gcc", azure=None, features=["x/threat-experts"])
    report = check(ds, plan)
    assert json.loads(render.check_json(report))["findings"][0]["archived"] == SNAP
    assert f"([archived copy]({SNAP}))" in render.check_md(report)
    assert json.loads(render.facts_json(ds.facts))[0]["archived"] == SNAP


# ---------------------------------------------------------------- tools/mark_checked.py writes the YAML
@pytest.fixture(scope="module")
def mark():
    path = Path(__file__).resolve().parents[1] / "tools" / "mark_checked.py"
    spec = importlib.util.spec_from_file_location("mark_checked", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


YAML = """# comment
sources:
  a:
    title: "A"
    url: "https://example.com/a"
    page_updated: 2026-09-01
    checked: 2026-10-01

  b:
    title: "B"
    url: "https://example.com/b"
    page_updated: 2026-09-01
    checked: 2026-10-01
    archived: "https://web.archive.org/web/20261001000000/https://example.com/b"
facts:
  - id: x
""".splitlines()


def test_mark_checked_adds_and_replaces_fields_in_place(mark):
    new_a = '"https://web.archive.org/web/20261012000000/https://example.com/a"'
    out, changed = mark.apply(YAML, {"a": {"checked": "2026-10-12", "archived": new_a},
                                     "b": {"checked": "2026-10-12", "page_updated": "2026-10-02"}})
    assert changed
    assert out[out.index("  a:") + 4:out.index("  a:") + 7] == ["    checked: 2026-10-12", f"    archived: {new_a}", ""]
    assert "    page_updated: 2026-10-02" in out and out.count("    checked: 2026-10-12") == 2
    assert out[-2:] == ["facts:", "  - id: x"] and len(out) == len(YAML) + 1
    assert mark.apply(YAML, {}) == (YAML, False)


# ---------------------------------------------------------------- the weekly pull request (watch.yml runs mark_checked)
NEW = "https://web.archive.org/web/20261019060000/https://example.com/page"


def test_a_failed_snapshot_keeps_the_old_page_date_so_the_next_run_tries_again(mark, tmp_path):
    r = verify.PageResult(tiny(tmp_path, SNAP).sources["p"], "ok", page_updated="2026-10-15")
    assert mark.updates_for([r], "2026-10-19", {}, {"p": "HTTPError: HTTP Error 520"}) == {"p": {"checked": "2026-10-19"}}
    assert mark.updates_for([r], "2026-10-19", {"p": NEW}, {}) == {
        "p": {"checked": "2026-10-19", "page_updated": "2026-10-15", "archived": f'"{NEW}"'}}
    assert mark.updates_for([replace(r, state="unreachable")], "2026-10-19", {}, {}) == {}


def test_only_updated_pages_get_a_snapshot_and_only_if_it_holds_the_rows(mark, monkeypatch, tmp_path):
    src = tiny(tmp_path, SNAP).sources["p"]
    same = verify.PageResult(src, "ok", page_updated=src.page_updated)
    newer = verify.PageResult(src, "ok", page_updated="2026-10-15")
    saved = []
    monkeypatch.setattr(mark, "save_snapshot", lambda url: saved.append(url) or NEW)
    monkeypatch.setattr(verify, "check_archived", lambda s, cites, fetch=None: verify.PageResult(s, "ok"))
    assert mark.archive([same], dry=False) == ({}, {}) and saved == []
    assert mark.archive([newer], dry=False) == ({"p": NEW}, {})
    monkeypatch.setattr(verify, "check_archived", lambda s, cites, fetch=None: verify.PageResult(s, "changed"))
    assert mark.archive([newer], dry=False) == ({}, {"p": "the snapshot is changed: rows missing"})


def test_snapshots_stop_after_failures_in_a_row(mark, monkeypatch, tmp_path):
    src = tiny(tmp_path).sources["p"]  # no archived copy yet, so every page needs one
    pages = [verify.PageResult(replace(src, key=f"p{i}"), "ok") for i in range(mark.GIVE_UP + 2)]
    tried = []

    def down(url):
        tried.append(url)
        raise urllib.error.HTTPError(url, 520, "status", {}, None)
    monkeypatch.setattr(mark, "save_snapshot", down)
    links, failed = mark.archive(pages, dry=False)
    assert links == {} and len(tried) == mark.GIVE_UP and len(failed) == len(pages)
    assert "HTTP Error 520" in failed["p0"] and failed[f"p{mark.GIVE_UP}"].startswith("skipped after")


def test_the_pull_request_summary(mark, tmp_path):
    src = tiny(tmp_path, SNAP).sources["p"]
    results = [verify.PageResult(src, "ok", page_updated="2026-10-15"),
               verify.PageResult(replace(src, key="q", title="Q | page"), "ok", page_updated="2026-10-16"),
               verify.PageResult(replace(src, key="r", title="R"), "ok", page_updated=src.page_updated),
               verify.PageResult(replace(src, key="t", title="T"), "unreachable", error="timed out")]
    text = mark.summary(results, {"p": NEW}, {"q": "HTTPError: HTTP Error 520"}, "2026-10-19")
    assert text.startswith("3 of 4 cited pages still hold every cited row; their checked date moves to 2026-10-19.")
    assert f"| [Page](https://example.com/page) | 2026-09-17 → 2026-10-15 | [new snapshot]({NEW})" in text
    assert "| [Q \\| page](https://example.com/page) | 2026-09-17 → 2026-10-16 | not saved (HTTPError" in text
    assert "[R]" not in text and "- [T](https://example.com/page): unreachable (timed out)" in text
    assert "no new snapshots were needed" in mark.summary(results[2:3], {}, {}, "2026-10-19")
