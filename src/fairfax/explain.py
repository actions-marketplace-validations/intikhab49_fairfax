"""Decode the sign-in errors that cross-cloud setups cause, from a code or a pasted error message."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .check import CLOUD_LABEL, TENANT_LABEL
from .dataset import Dataset, ErrorCode
from .scan import expected

CODE = re.compile(r"\bAADSTS(\d{5,8})\b|^\s*(\d{5,8})\s*$", re.IGNORECASE)


@dataclass
class Explained:
    error: ErrorCode
    hosts: list = field(default_factory=list)  # (host, who it's for) for the clouds you named


@dataclass
class Result:
    matches: list
    unknown: list  # AADSTS codes in the input that fairfax doesn't decode


def codes_in(text: str) -> list:
    out = []
    for m in CODE.finditer(text):
        out.append("AADSTS" + (m.group(1) or m.group(2)))
    return list(dict.fromkeys(out))


def sign_in_hosts(ds: Dataset, err: ErrorCode, tenant: str | None, azure: str | None) -> list:
    """The right sign-in host for each side of your plan, or the whole map when no cloud is named."""
    e = next((x for x in ds.endpoints if x.id == err.endpoint), None)
    if e is None:
        return []
    if tenant or azure:
        out = []
        for host, side in expected(e, tenant, azure):
            who = f"a {TENANT_LABEL[tenant]} tenant" if side == "m365" else CLOUD_LABEL[azure]
            out.append((host, who))
        return list(dict.fromkeys(out))
    gov, com = e.hosts.get("government", ("",))[0], e.hosts.get("commercial", ("",))[0]
    return [(com, "commercial Azure and GCC tenants"), (gov, "GCC High and DoD tenants and Azure Government")]


def explain(ds: Dataset, text: str, tenant: str | None = None, azure: str | None = None) -> Result:
    by_code = {e.code: e for e in ds.errors}
    codes = codes_in(text)
    found = [by_code[c] for c in codes if c in by_code]
    if not codes:
        # No code in the text: match the error's name or Microsoft's wording instead.
        needle = text.strip().lower()
        found = [e for e in ds.errors if needle and (needle in e.name.lower() or needle in e.row.lower()
                                                     or e.name.lower() in needle)]
    unknown = [c for c in codes if c not in by_code]
    return Result([Explained(e, sign_in_hosts(ds, e, tenant, azure)) for e in found], unknown)
