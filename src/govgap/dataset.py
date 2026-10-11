"""The bundled dataset: Microsoft availability rows, stack-level rules and the endpoint map.

Every entry points at the Microsoft page it came from, the section anchor, and the row or quote
that backs it. The loader validates everything, so a typo in a YAML file fails loudly.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import yaml

TENANTS = ("gcc", "gcchigh", "dod")
CLOUDS = ("commercial", "government")
BY_KEYS = {
    "azure": set(CLOUDS),
    "tenant": set(TENANTS),
    "tenant+azure": {f"{t}+{c}" for t in TENANTS for c in CLOUDS},
}
STATUSES = {"ga", "available", "preview", "private-preview", "limited", "not-available", "no-plans", "not-possible"}
PLANNED = re.compile(r"planned:CY\d{4}-(?:H[12]|Q[1-4])")
GROUPS = ("blocked", "cross-cloud", "retiring", "note")
CONFIDENCE = ("high", "medium", "unverified")
PLANES = {"azure": set(CLOUDS), "identity": set(CLOUDS), "m365": {"commercial", *TENANTS}}
FEATURE_KEY = re.compile(r"[a-z0-9-]+(?:/[a-z0-9.-]+)+")
HOST = re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class DatasetError(ValueError):
    pass


@dataclass(frozen=True)
class Source:
    key: str
    title: str
    url: str
    page_updated: str
    checked: str

    def link(self, anchor: str = "") -> str:
        return f"{self.url}#{anchor}" if anchor else self.url


@dataclass(frozen=True)
class Fact:
    id: str
    feature: str
    name: str
    by: str
    status: dict
    source: Source
    anchor: str
    row: str
    confidence: str
    note: str | None = None
    retires: str | None = None
    retires_source: Source | None = None
    retires_quote: str | None = None
    instead: str | None = None

    @property
    def url(self) -> str:
        return self.source.link(self.anchor)


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    when: dict
    group: str
    says: str
    source: Source
    anchor: str
    quote: str
    confidence: str

    @property
    def url(self) -> str:
        return self.source.link(self.anchor)


@dataclass(frozen=True)
class Endpoint:
    id: str
    service: str
    plane: str
    hosts: dict  # key -> tuple of hosts, first one is the canonical spelling
    source: Source
    anchor: str
    row: str

    @property
    def url(self) -> str:
        return self.source.link(self.anchor)


@dataclass
class Dataset:
    sources: dict
    facts: list
    rules: list
    endpoints: list

    def features(self) -> dict:
        out: dict[str, list[Fact]] = {}
        for f in self.facts:
            out.setdefault(f.feature, []).append(f)
        return out

    @property
    def checked(self) -> str:
        """The oldest check date across every cited page."""
        return min(s.checked for s in self.sources.values())


def _date(v, where: str) -> str:
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, str) and DATE.fullmatch(v):
        return v
    raise DatasetError(f"{where}: expected a YYYY-MM-DD date, got {v!r}")


def _need(d: dict, keys: tuple, where: str) -> None:
    # anchor may be empty (a PDF has no anchors); every other required key needs a value
    missing = [k for k in keys if k not in d or (d[k] in (None, "") and k != "anchor")]
    if missing:
        raise DatasetError(f"{where}: missing {', '.join(missing)}")


def _status_ok(v) -> bool:
    return isinstance(v, str) and (v in STATUSES or PLANNED.fullmatch(v) is not None)


def load(path: str | Path | None = None) -> Dataset:
    root = Path(path) if path else resources.files("govgap") / "data"
    files = sorted((p for p in root.iterdir() if p.name.endswith(".yaml")), key=lambda p: p.name)
    raw = {p.name: yaml.safe_load(p.read_text(encoding="utf-8")) or {} for p in files}
    if "sources.yaml" not in raw:
        raise DatasetError(f"{root}: sources.yaml not found")

    sources = {}
    for key, s in (raw.pop("sources.yaml").get("sources") or {}).items():
        where = f"sources.yaml:{key}"
        _need(s, ("title", "url", "page_updated", "checked"), where)
        sources[key] = Source(key, s["title"], s["url"], _date(s["page_updated"], where), _date(s["checked"], where))

    def source(key, where):
        if key not in sources:
            raise DatasetError(f"{where}: unknown source {key!r}")
        return sources[key]

    ds, seen = Dataset(sources, [], [], []), set()

    def unique(item_id, where):
        if item_id in seen:
            raise DatasetError(f"{where}: duplicate id {item_id!r}")
        seen.add(item_id)

    for name, doc in raw.items():
        for f in doc.get("facts") or []:
            where = f"{name}:{f.get('id', '?')}"
            _need(f, ("id", "feature", "name", "by", "status", "source", "anchor", "row", "confidence"), where)
            unique(f["id"], where)
            if not FEATURE_KEY.fullmatch(f["feature"]):
                raise DatasetError(f"{where}: feature key {f['feature']!r} must look like service/feature")
            if f["by"] not in BY_KEYS:
                raise DatasetError(f"{where}: by must be one of {', '.join(BY_KEYS)}")
            status = f["status"]
            if not isinstance(status, dict) or not status:
                raise DatasetError(f"{where}: status must be a non-empty mapping")
            for k, v in status.items():
                if k not in BY_KEYS[f["by"]]:
                    raise DatasetError(f"{where}: status key {k!r} doesn't fit by: {f['by']}")
                if not _status_ok(v):
                    raise DatasetError(f"{where}: unknown status {v!r}")
            if f["confidence"] not in CONFIDENCE:
                raise DatasetError(f"{where}: confidence must be one of {', '.join(CONFIDENCE)}")
            retires = f.get("retires")
            if retires is not None:
                _need(f, ("retires_source", "retires_quote"), where)
            ds.facts.append(Fact(
                id=f["id"], feature=f["feature"], name=f["name"], by=f["by"], status=dict(status),
                source=source(f["source"], where), anchor=f["anchor"], row=f["row"], confidence=f["confidence"],
                note=f.get("note"), retires=_date(retires, where) if retires is not None else None,
                retires_source=source(f["retires_source"], where) if retires is not None else None,
                retires_quote=f.get("retires_quote"), instead=f.get("instead")))

        for r in doc.get("rules") or []:
            where = f"{name}:{r.get('id', '?')}"
            _need(r, ("id", "title", "when", "group", "says", "source", "anchor", "quote", "confidence"), where)
            unique(r["id"], where)
            if r["group"] not in GROUPS:
                raise DatasetError(f"{where}: group must be one of {', '.join(GROUPS)}")
            when = r["when"]
            for k, vals in when.items():
                allowed = {"tenant": set(TENANTS), "azure": set(CLOUDS)}.get(k)
                if k == "uses":
                    if not all(isinstance(v, str) for v in vals):
                        raise DatasetError(f"{where}: uses must be a list of feature-key prefixes")
                elif allowed is None or not set(vals) <= allowed:
                    raise DatasetError(f"{where}: bad when.{k}: {vals!r}")
            if r["confidence"] not in CONFIDENCE:
                raise DatasetError(f"{where}: confidence must be one of {', '.join(CONFIDENCE)}")
            ds.rules.append(Rule(r["id"], r["title"], {k: list(v) for k, v in when.items()}, r["group"], r["says"],
                                 source(r["source"], where), r["anchor"], r["quote"], r["confidence"]))

        for e in doc.get("endpoints") or []:
            where = f"{name}:{e.get('id', '?')}"
            _need(e, ("id", "service", "plane", "hosts", "source", "anchor", "row"), where)
            unique(e["id"], where)
            if e["plane"] not in PLANES:
                raise DatasetError(f"{where}: plane must be one of {', '.join(PLANES)}")
            hosts = {}
            for k, v in e["hosts"].items():
                if k not in PLANES[e["plane"]]:
                    raise DatasetError(f"{where}: host key {k!r} doesn't fit plane {e['plane']}")
                vals = tuple(v if isinstance(v, list) else [v])
                for h in vals:
                    if not isinstance(h, str) or not HOST.fullmatch(h):
                        raise DatasetError(f"{where}: {h!r} is not a bare lowercase host name")
                hosts[k] = vals
            ds.endpoints.append(Endpoint(e["id"], e["service"], e["plane"], hosts, source(e["source"], where),
                                         e["anchor"], e["row"]))
    return ds
