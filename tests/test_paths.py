"""Tests for 0.2.3: per-path cloud settings (`paths:` in a plan) for repositories that mix clouds."""
import json
from pathlib import Path

import pytest

from fairfax import cli, dataset
from fairfax.check import PathRule, PlanError, check, load_plan
from fairfax.scan import clouds_for, scan

PLAN = """tenant: gcchigh
azure: government
features: [sentinel/connector/teams]
paths:
  - glob: "services/legacy/**"
    azure: commercial
  - glob: "services/legacy/teams-bot/**"
    tenant: gcc
  - glob: apps/partner
    tenant: gcc
"""
FILES = {
    "app/main.py": 'K = "https://kv1.vault.azure.net/"\n',
    "services/legacy/pay.py": 'K = "https://kv1.vault.azure.net/"\nG = "https://graph.microsoft.com/v1.0"\n',
    "services/legacy/teams-bot/bot.py": 'G = "https://graph.microsoft.com/v1.0"\nD = "https://org.crm4.dynamics.com"\n',
    "apps/partner/portal.py": 'D = "https://org.crm4.dynamics.com"\nL = "https://login.microsoftonline.com/x"\n',
    "apps/partnership/site.py": 'D = "https://org.crm4.dynamics.com"\n',
}


@pytest.fixture(scope="module")
def ds():
    return dataset.load()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    for rel, text in {"plan.yaml": PLAN, **FILES}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


def by_file(hits, root):
    out = {}
    for h in hits:
        out.setdefault(Path(h.path).resolve().relative_to(root.resolve()).as_posix(), []).append(
            (h.found, h.kind, h.tenant, h.azure, h.from_paths))
    return out


# ---------------------------------------------------------------- the plan file
def test_plan_reads_paths_and_check_ignores_them(repo, ds):
    plan = load_plan(repo / "plan.yaml")
    assert plan.paths == [PathRule("services/legacy/**", None, "commercial"),
                          PathRule("services/legacy/teams-bot/**", "gcc", None), PathRule("apps/partner", "gcc", None)]
    assert check(ds, plan).plan.tenant == "gcchigh"  # check uses the plan's own clouds


@pytest.mark.parametrize("paths, error", [
    ("paths: services/**", "paths must be a list"),
    ("paths: [{azure: commercial}]", "paths entry 1 needs a glob"),
    ('paths: [{glob: "a/**", cloud: commercial}]', "unknown keys: cloud"),
    ('paths: [{glob: "a/**"}]', "sets neither tenant nor azure"),
    ('paths: [{glob: "a/**", tenant: gcchi}]', "tenant must be one of"),
    ('paths: [{glob: "a/**", azure: usgov}]', "azure must be one of"),
])
def test_bad_paths_entries_are_errors(tmp_path, paths, error):
    p = tmp_path / "plan.yaml"
    p.write_text(f"tenant: gcc\n{paths}\n", encoding="utf-8")
    with pytest.raises(PlanError, match=error):
        load_plan(p)


def test_globs_are_normalised(tmp_path):
    p = tmp_path / "plan.yaml"
    p.write_text('tenant: gcc\npaths:\n  - {glob: "./a/**", azure: government}\n  - {glob: "b\\\\c\\\\*.py", tenant: dod}\n')
    assert [r.glob for r in load_plan(p).paths] == ["a/**", "b/c/*.py"]


# ---------------------------------------------------------------- which clouds a file gets
def test_most_specific_glob_wins_for_tenant_and_azure_separately():
    rules = [PathRule("a/**", azure="commercial"), PathRule("a/b/**", tenant="gcc"), PathRule("**/*.tf", tenant="dod")]
    assert clouds_for("a/b/x.py", "gcchigh", "government", rules) == ("gcc", "commercial", ["a/b/**", "a/**"])
    assert clouds_for("a/x.tf", "gcchigh", "government", rules) == ("dod", "commercial", ["**/*.tf", "a/**"])
    # a/b/** and **/*.tf each spell out 4 characters, so the later entry wins
    assert clouds_for("a/b/x.tf", "gcchigh", "government", rules) == ("dod", "commercial", ["**/*.tf", "a/**"])


def test_a_tie_goes_to_the_later_entry_and_no_match_keeps_the_plan():
    rules = [PathRule("a/**", azure="commercial"), PathRule("a/**", azure="government")]
    assert clouds_for("a/x.py", "gcc", "commercial", rules) == ("gcc", "government", ["a/**"])
    assert clouds_for("z/x.py", "gcc", "commercial", rules) == ("gcc", "commercial", [])
    assert clouds_for(None, "gcc", "commercial", rules) == ("gcc", "commercial", [])  # outside the plan's folder


def test_a_glob_without_wildcards_is_a_file_or_a_whole_folder():
    rules = [PathRule("apps/partner", tenant="gcc")]
    assert clouds_for("apps/partner/x.py", "dod", None, rules)[0] == "gcc"
    assert clouds_for("apps/partner", "dod", None, rules)[0] == "gcc"
    assert clouds_for("apps/partnership/x.py", "dod", None, rules)[0] == "dod"


# ---------------------------------------------------------------- scanning a mixed repository
def test_each_file_is_checked_against_the_clouds_its_path_maps_to(ds, repo):
    plan = load_plan(repo / "plan.yaml")
    hits, files = scan([str(repo)], ds, plan.tenant, plan.azure, rules=plan.paths, base=repo)
    assert files == 6 and by_file(hits, repo) == {
        # no override: GCC High and Azure Government
        "app/main.py": [("kv1.vault.azure.net", "wrong", "gcchigh", "government", [])],
        "apps/partnership/site.py": [("org.crm4.dynamics.com", "wrong", "gcchigh", "government", [])],
        # commercial Azure, so its Key Vault host is fine; the tenant is still GCC High, so Graph is not
        "services/legacy/pay.py": [("graph.microsoft.com", "wrong", "gcchigh", "commercial", ["services/legacy/**"])],
        # GCC tenant from the nested glob, commercial Azure from the outer one: Graph is fine, Dataverse is not
        "services/legacy/teams-bot/bot.py": [("org.crm4.dynamics.com", "wrong", "gcc", "commercial",
                                              ["services/legacy/teams-bot/**", "services/legacy/**"])],
        # GCC tenant with Azure Government: Dataverse is wrong, and sign-in may be either
        "apps/partner/portal.py": [("org.crm4.dynamics.com", "wrong", "gcc", "government", ["apps/partner"]),
                                   ("login.microsoftonline.com", "check", "gcc", "government", ["apps/partner"])],
    }


def test_globs_follow_the_plan_file_not_the_scan_path(ds, repo, monkeypatch):
    monkeypatch.chdir(repo.parent)
    plan = load_plan(repo / "plan.yaml")
    hits, _ = scan([str(repo / "services" / "legacy" / "teams-bot")], ds, plan.tenant, plan.azure, rules=plan.paths,
                   base=repo)
    assert [(h.found, h.tenant, h.azure) for h in hits] == [("org.crm4.dynamics.com", "gcc", "commercial")]
    outside = repo.parent / "other"
    outside.mkdir()
    (outside / "x.py").write_text('K = "https://kv1.vault.azure.net/"\n', encoding="utf-8")
    hits, _ = scan([str(outside)], ds, plan.tenant, plan.azure, rules=plan.paths, base=repo)
    assert [(h.found, h.azure, h.from_paths) for h in hits] == [("kv1.vault.azure.net", "government", [])]


# ---------------------------------------------------------------- what the reports say
def test_cli_reports_which_clouds_each_finding_used(capsys, repo, tmp_path):
    plan = str(repo / "plan.yaml")
    assert cli.main(["scan", str(repo), "--plan", plan]) == 1
    out = capsys.readouterr().out
    assert out.startswith("fairfax scan: tenant GCC High, Azure Government, 3 path overrides from the plan")
    assert ("bot.py  (checked as tenant GCC, commercial Azure, from paths: services/legacy/teams-bot/**, "
            "services/legacy/**)") in out
    assert "main.py\n" in out  # a file on the plan's own clouds gets no note
    assert "5 wrong-cloud endpoints and 1 to check in 5 of 6 files scanned." in out

    cli.main(["scan", str(repo), "--plan", plan, "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert data["paths"][0] == {"glob": "services/legacy/**", "tenant": None, "azure": "commercial"}
    portal = [h for h in data["hits"] if h["path"].endswith("portal.py")]
    assert {(h["tenant"], h["azure"], tuple(h["from_paths"])) for h in portal} == {("gcc", "government", ("apps/partner",))}

    cli.main(["scan", str(repo), "--plan", plan, "--format", "md"])
    assert "<br>checked as tenant GCC, Azure Government, from paths: `apps/partner`" in capsys.readouterr().out

    out_file = tmp_path / "scan.sarif"
    cli.main(["scan", str(repo), "--plan", plan, "--format", "sarif", "-o", str(out_file)])
    results = json.loads(out_file.read_text(encoding="utf-8"))["runs"][0]["results"]
    bot = next(r for r in results if r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"].endswith("bot.py"))
    assert bot["properties"] == {"tenant": "gcc", "azure": "commercial",
                                 "fromPaths": ["services/legacy/teams-bot/**", "services/legacy/**"]}
    assert "This file was checked as tenant GCC, commercial Azure" in bot["message"]["text"]
    main = next(r for r in results if r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"].endswith("main.py"))
    assert main["properties"]["fromPaths"] == [] and "checked as" not in main["message"]["text"]


def test_tenant_and_azure_flags_replace_the_plans_clouds_but_paths_still_apply(capsys, repo):
    cli.main(["scan", str(repo), "--plan", str(repo / "plan.yaml"), "--azure", "commercial", "--format", "json"])
    hits = json.loads(capsys.readouterr().out)["hits"]
    assert not any(h["path"].endswith("main.py") for h in hits)  # kv1.vault.azure.net is right for commercial Azure
    assert {h["tenant"] for h in hits if h["path"].endswith("bot.py")} == {"gcc"}
