"""Evaluate a plan (tenant type, Azure cloud, feature list) against the dataset."""

from __future__ import annotations

import datetime as dt
import difflib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .dataset import CLOUDS, ROADMAP_CLOUDS, TENANTS, Dataset, Fact, RoadmapItem, Rule

GROUP_ORDER = ("blocked", "cross-cloud", "retiring", "note", "ok")
TENANT_LABEL = {"gcc": "GCC", "gcchigh": "GCC High", "dod": "DoD"}
CLOUD_LABEL = {"commercial": "commercial Azure", "government": "Azure Government"}
PHRASE = {
    "ga": "generally available",
    "available": "available",
    "preview": "in preview only",
    "private-preview": "in private preview only",
    "limited": "available with limits",
    "rolling-out": "rolling out",
    "planned": "not available yet",
    "in-development": "not available yet",
    "backlog": "not available",
    "not-available": "not available",
    "no-plans": "not available, and Microsoft has no plans to add it",
    "not-possible": "not possible",
}
EXPLAIN = {
    "planned": "Microsoft lists it as planned.",
    "in-development": "Microsoft lists it as in development.",
    "backlog": "Microsoft lists it on its engineering backlog.",
}
SHORT = {"ga": "GA", "available": "available", "preview": "preview", "limited": "limited", "rolling-out": "rolling out"}
GROUP_OF = {
    "ga": "ok", "available": "ok", "preview": "note", "private-preview": "note", "limited": "note", "rolling-out": "note",
    "planned": "blocked", "in-development": "blocked", "backlog": "blocked",
    "not-available": "blocked", "no-plans": "blocked", "not-possible": "cross-cloud",
}
PERIOD_END = {"H1": (6, 30), "H2": (12, 31), "Q1": (3, 31), "Q2": (6, 30), "Q3": (9, 30), "Q4": (12, 31)}


class PlanError(ValueError):
    pass


@dataclass
class Plan:
    tenant: str
    azure: str | None
    features: list
    name: str = ""
    path: str = ""


@dataclass
class Finding:
    group: str
    feature: str | None
    title: str
    says: str
    url: str
    cite: str
    source_title: str
    page_updated: str
    checked: str
    confidence: str
    status: str | None = None
    note: str | None = None
    elsewhere: str | None = None
    verdict: str = ""
    cite_kind: str = "row"
    id: str = ""
    roadmap: list = field(default_factory=list)


@dataclass
class Report:
    plan: Plan
    findings: list
    unknown: dict = field(default_factory=dict)
    facts: int = 0
    checked: str = ""
    features: int = 0

    def groups(self) -> dict:
        out = {g: [] for g in GROUP_ORDER}
        for f in self.findings:
            out[f.group].append(f)
        return out

    def counts(self) -> dict:
        return {g: len(v) for g, v in self.groups().items()}

    def failed(self, strict: bool = False) -> bool:
        bad = {"blocked", "cross-cloud", "retiring"} if strict else {"blocked"}
        return any(f.group in bad for f in self.findings)


def load_plan(path: str | Path) -> Plan:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PlanError(f"{path}: file not found") from None
    except yaml.YAMLError as e:
        raise PlanError(f"{path}: not valid YAML ({e})") from None
    if not isinstance(data, dict):
        raise PlanError(f"{path}: expected a mapping with tenant, azure and features")
    extra = set(data) - {"name", "tenant", "azure", "features"}
    if extra:
        raise PlanError(f"{path}: unknown keys: {', '.join(sorted(extra))}")
    tenant, azure = data.get("tenant"), data.get("azure")
    if tenant not in TENANTS:
        raise PlanError(f"{path}: tenant must be one of {', '.join(TENANTS)} (got {tenant!r})")
    if azure is not None and azure not in CLOUDS:
        raise PlanError(f"{path}: azure must be one of {', '.join(CLOUDS)} (got {azure!r})")
    features = data.get("features") or []
    if not isinstance(features, list) or not all(isinstance(f, str) for f in features):
        raise PlanError(f"{path}: features must be a list of feature keys")
    return Plan(tenant, azure, list(dict.fromkeys(features)), str(data.get("name") or ""), str(path))


def where(by: str, key: str) -> str:
    if by == "azure":
        return f"in {CLOUD_LABEL[key]}"
    if by == "tenant":
        return f"in {TENANT_LABEL[key]}"
    t, c = key.split("+")
    return f"for {TENANT_LABEL[t]} tenants with {CLOUD_LABEL[c]}"


def plan_key(fact: Fact, plan: Plan) -> str | None:
    if fact.by == "tenant":
        return plan.tenant
    if plan.azure is None:
        return None
    return plan.azure if fact.by == "azure" else f"{plan.tenant}+{plan.azure}"


def eta_passed(eta: str, today: dt.date) -> bool:
    year, period = eta[2:6], eta[7:]
    month, day = PERIOD_END[period]
    return today > dt.date(int(year), month, day)


def elsewhere(fact: Fact, key: str, status: dict | None = None) -> str:
    status = status or fact.status
    alts = [(k, s) for k, s in status.items() if k != key and s in SHORT]
    if alts:
        return "Works " + "; ".join(f"{where(fact.by, k)} ({SHORT[s]})" for k, s in alts) + "."
    if fact.by == "tenant":
        covered = [TENANT_LABEL[t] for t in TENANTS if t in status]
        names = covered[0] if len(covered) == 1 else ", ".join(covered[:-1]) + " or " + covered[-1]
        return f"Microsoft lists it for none of {names}."
    return "Microsoft's table lists no cloud where it works."


def _finding(fact: Fact, group: str, says: str, **kw) -> Finding:
    return Finding(group=group, feature=fact.feature, title=fact.name, says=says, url=fact.url, cite=fact.row,
                   source_title=fact.source.title, page_updated=fact.source.page_updated,
                   checked=fact.source.checked, confidence=fact.confidence, note=fact.note, id=fact.id,
                   cite_kind=fact.cite, **kw)


def evaluate(fact: Fact, plan: Plan, today: dt.date, merged: dict | None = None) -> list:
    """Findings for one fact. merged holds the feature's statuses across all its facts (pages)."""
    out = []
    merged = merged or fact.status
    key = plan_key(fact, plan)
    status = fact.status.get(key) if key else None
    if key is None:
        out.append(_finding(fact, "note", f"{fact.name} depends on which Azure cloud you use, and the plan "
                                          "doesn't say. Add `azure: commercial` or `azure: government`."))
    elif status is None:
        out.append(_finding(fact, "note", f"{fact.name}: Microsoft's table doesn't cover it {where(fact.by, key)}, "
                                          "so fairfax can't say either way."))
    elif status.startswith("planned:"):
        eta = status.split(":", 1)[1]
        verdict = f"not available yet {where(fact.by, key)}"
        says = f"{fact.name}: {verdict}. Microsoft's target is {eta}."
        if eta_passed(eta, today):
            says += " That date has passed, so check Microsoft's current table."
        out.append(_finding(fact, "blocked", says, status=status, elsewhere=elsewhere(fact, key, merged),
                            verdict=verdict))
    else:
        group = GROUP_OF[status]
        if status == "not-possible":
            t, c = key.split("+")
            verdict = f"not possible {where(fact.by, key)}"
            says = (f"{fact.name} can't connect {TENANT_LABEL[t]} tenants to {CLOUD_LABEL[c]}. "
                    "Microsoft marks that pairing as not possible.")
        else:
            verdict = f"{PHRASE[status]} {where(fact.by, key)}"
            says = f"{fact.name}: {verdict}." + (f" {EXPLAIN[status]}" if status in EXPLAIN else "")
        alt = elsewhere(fact, key, merged) if group in ("blocked", "cross-cloud") else None
        out.append(_finding(fact, group, says, status=status, elsewhere=alt, verdict=verdict))
    if fact.retires:
        src = fact.retires_source
        out.append(Finding(
            group="retiring", feature=fact.feature, title=fact.name,
            says=f"{fact.name} retires on {fact.retires}." + (f" {fact.instead}" if fact.instead else ""),
            url=src.link(), cite=fact.retires_quote, source_title=src.title, page_updated=src.page_updated,
            checked=src.checked, confidence=fact.confidence, cite_kind="quote", id=fact.id + ".retires"))
    return out


def applies(rule: Rule, plan: Plan) -> bool:
    w = rule.when
    if "tenant" in w and plan.tenant not in w["tenant"]:
        return False
    if "azure" in w and plan.azure not in w["azure"]:
        return False
    if "uses" in w and not any(f.startswith(p) for f in plan.features for p in w["uses"]):
        return False
    return True


def _and(items) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def roadmap_note(item: RoadmapItem, today: dt.date) -> dict:
    """What Microsoft's 365 roadmap says about a blocked feature, as one sentence plus the link."""
    says = (f"Microsoft 365 roadmap {item.id}, \"{item.title}\": {item.status} for {_and(item.clouds)}, "
            f"target {item.ga}.")
    if item.status == "Launched":
        says += " The roadmap says it has launched while the table says it's missing, so check both."
    elif item.ga < today.strftime("%Y-%m"):
        says += " That month has passed, so check the roadmap for a newer date."
    return {"id": item.id, "title": item.title, "status": item.status, "clouds": list(item.clouds), "ga": item.ga,
            "url": item.url, "says": says}


def suggest(key: str, known) -> list:
    close = difflib.get_close_matches(key, known, n=3, cutoff=0.6)
    if close:
        return close
    tail = key.rsplit("/", 1)[-1]
    return sorted(k for k in known if tail and tail in k)[:3]


def check(ds: Dataset, plan: Plan, today: dt.date | None = None) -> Report:
    today = today or dt.date.today()
    index = ds.features()
    unknown = {f: suggest(f, index) for f in plan.features if f not in index}
    findings = []
    for feature in plan.features:
        facts = index.get(feature, [])
        merged = {k: v for f in facts for k, v in f.status.items()}
        # Some features cite one Microsoft page per cloud: use the page that covers this plan.
        covering = [f for f in facts if plan_key(f, plan) in f.status]
        for fact in covering or facts[:1]:
            for f in evaluate(fact, plan, today, merged):
                if f.group == "blocked":
                    cloud = ROADMAP_CLOUDS[plan.tenant]
                    f.roadmap = [roadmap_note(r, today) for r in ds.roadmap_for(feature) if cloud in r.clouds]
                findings.append(f)
    for rule in ds.rules:
        if applies(rule, plan):
            findings.append(Finding(
                group=rule.group, feature=None, title=rule.title, says=rule.says, url=rule.url, cite=rule.quote,
                source_title=rule.source.title, page_updated=rule.source.page_updated,
                checked=rule.source.checked, confidence=rule.confidence, cite_kind="quote", id=rule.id))
    findings.sort(key=lambda f: (GROUP_ORDER.index(f.group), f.feature is not None, f.feature or "", f.id))
    return Report(plan, findings, unknown, len(ds.facts), ds.checked, len(index))
