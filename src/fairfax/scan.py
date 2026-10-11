"""Find Microsoft endpoints that belong to the wrong cloud in code and config files.

A GCC tenant keeps the worldwide Entra ID and Graph endpoints, while GCC High, DoD and Azure
Government have their own. The scanner knows which side each host belongs to, so it only flags
a host that is wrong for the tenant and Azure cloud you name.
"""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .check import CLOUD_LABEL, TENANT_LABEL
from .dataset import Dataset, Endpoint

TOKEN = re.compile(r"(?<![A-Za-z0-9-])[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", ".tox", ".mypy_cache",
             ".pytest_cache", ".ruff_cache", "dist", "build", ".terraform", ".next", "site-packages", "vendor"}
IGNORE_MARK = "fairfax: ignore"
MAX_BYTES = 5_000_000
SIDE = {"m365": "Microsoft 365 side", "azure": "Azure side"}


@dataclass
class Hit:
    path: str
    line: int
    col: int
    found: str
    kind: str  # "wrong" or "check"
    expected: list
    service: str
    why: str
    url: str
    id: str


class HostIndex:
    """Suffix lookup, longest match first, bucketed by the last two labels."""

    def __init__(self, endpoints: list):
        self.buckets: dict[str, list] = {}
        for e in endpoints:
            for hosts in e.hosts.values():
                for h in hosts:
                    self.buckets.setdefault(".".join(h.split(".")[-2:]), []).append((h, e))
        for v in self.buckets.values():
            v.sort(key=lambda t: -len(t[0]))

    def match(self, host: str):
        for suffix, e in self.buckets.get(".".join(host.split(".")[-2:]), ()):
            if host == suffix or host.endswith("." + suffix):
                return suffix, e
        return None


def expected(e: Endpoint, tenant: str | None, azure: str | None) -> list:
    """(host, side) pairs that are right for this tenant and Azure cloud."""
    if e.plane == "azure":
        return [(e.hosts[azure][0], "azure")] if azure in e.hosts else []
    if e.plane == "m365":
        return [(e.hosts[tenant][0], "m365")] if tenant in e.hosts else []
    pairs = []
    if tenant:
        pairs.append((e.hosts["government" if tenant in ("gcchigh", "dod") else "commercial"][0], "m365"))
    if azure:
        pairs.append((e.hosts[azure][0], "azure"))
    return list(dict.fromkeys(pairs))


def judge(host: str, suffix: str, e: Endpoint, tenant: str | None, azure: str | None):
    pairs = expected(e, tenant, azure)
    if not pairs:
        return None
    right = list(dict.fromkeys(h for h, _ in pairs))
    if suffix in right:
        if len(right) == 1:
            return None
        mine = next(side for h, side in pairs if h == suffix)
        other_host, other_side = next((h, side) for h, side in pairs if h != suffix)
        why = (f"{e.service}: right for the {SIDE[mine]} of your plan, but the {SIDE[other_side]} "
               f"({_where(other_side, tenant, azure)}) needs {other_host}. Check which one this call is for.")
        return "check", [other_host], why
    prefix = host[: len(host) - len(suffix)]
    fixes = [prefix + h for h in right]
    if len(right) == 1:
        who = " and ".join(_where(side, tenant, azure) for _, side in pairs)
        why = f"{e.service}: {who} {'use' if len(pairs) > 1 else 'uses'} {right[0]}."
    else:
        why = (f"{e.service}: the Microsoft 365 side uses {pairs[0][0]} and the Azure side uses {pairs[1][0]}; "
               f"{suffix} fits neither.")
    return "wrong", fixes, why


def _where(side: str, tenant: str | None, azure: str | None) -> str:
    if side == "m365":
        return f"a {TENANT_LABEL[tenant]} tenant"
    return CLOUD_LABEL[azure]


def iter_files(paths: list, exclude: list):
    for p in map(Path, paths):
        if p.is_file():
            yield p
            continue
        for root, dirs, files in os.walk(p):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for name in sorted(files):
                full = Path(root, name)
                rel = full.relative_to(p).as_posix()
                if not any(fnmatch.fnmatch(rel, pat) for pat in exclude):
                    yield full


def read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def scan(paths: list, ds: Dataset, tenant: str | None, azure: str | None, exclude: list = ()) -> tuple:
    index = HostIndex(ds.endpoints)
    hits, files = [], 0
    for path in iter_files(paths, list(exclude)):
        text = read_text(path)
        if text is None:
            continue
        files += 1
        for n, line in enumerate(text.splitlines(), 1):
            if IGNORE_MARK in line:
                continue
            for m in TOKEN.finditer(line):
                host = m.group(0).lower()
                found = index.match(host)
                if not found:
                    continue
                verdict = judge(host, found[0], found[1], tenant, azure)
                if verdict:
                    kind, fixes, why = verdict
                    e = found[1]
                    hits.append(Hit(path.as_posix(), n, m.start() + 1, host, kind, fixes, e.service, why, e.url, e.id))
    return hits, files
