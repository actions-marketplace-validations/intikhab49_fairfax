"""Write roadmap.yaml: Microsoft 365 roadmap items linked by hand to the features they deliver.

A link is only made when the roadmap item is the feature itself, for a cloud where fairfax's table
says the feature is missing. Title, status, clouds and dates are copied from Microsoft's public
roadmap API, never typed. `fairfax verify` compares them with the live API.

Usage:
  curl -s -o roadmap.json https://www.microsoft.com/releasecommunications/api/v2/m365
  python tools/build_roadmap.py roadmap.json <out_dir>
"""
import json
import sys
from pathlib import Path

CHECKED = "2026-10-12"
API = "https://www.microsoft.com/releasecommunications/api/v2/m365"
LINKS = {  # roadmap id -> fairfax feature keys it delivers
    501438: ["intune/windows-backup-for-organizations"],
    93269: ["purview/ediscovery/hold-reports"],
    558859: ["purview/records-management/power-automate-integration"],
    564606: ["m365-copilot/declarative-agents"],
    542181: ["m365-copilot/edit-in-office-apps"],
    570428: ["m365-copilot/copilot-analytics"],
}


def main():
    items = {i["id"]: i for i in json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["value"]}
    out = Path(sys.argv[2])
    lines = ["# Microsoft 365 roadmap items linked by hand to the features they deliver, for a cloud where the",
             "# feature is missing. Title, status, clouds and target month are copied from Microsoft's public API.",
             "sources:",
             "  m365-roadmap:",
             '    title: "Microsoft 365 roadmap (public API)"',
             f"    url: {json.dumps(API)}",
             f"    page_updated: {max(items[i]['modified'][:10] for i in LINKS)}",
             f"    checked: {CHECKED}",
             "roadmap:"]
    for rid, features in LINKS.items():
        it = items.get(rid) or sys.exit(f"roadmap item {rid} not in the API")
        clouds = [c for c in it["cloudInstances"] if c in ("GCC", "GCC High", "DoD")]
        lines += [f"  - id: {rid}",
                  f"    features: [{', '.join(features)}]",
                  f"    title: {json.dumps(it['title'].strip(), ensure_ascii=False)}",
                  f"    status: {json.dumps(it['status'])}",
                  f"    clouds: [{', '.join(json.dumps(c) for c in clouds)}]",
                  f"    ga: {json.dumps(it['generalAvailabilityDate'])}",
                  "    source: m365-roadmap",
                  ""]
    (out / "roadmap.yaml").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")
    print(f"roadmap.yaml: {len(LINKS)}")


if __name__ == "__main__":
    main()
