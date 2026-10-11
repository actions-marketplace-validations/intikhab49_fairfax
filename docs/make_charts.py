"""Generate the README chart from the bundled dataset. Regenerate with:  python docs/make_charts.py

Counts are of the features govgap tracks, not a share of each product, and the caption says so.
Azure OpenAI is left out: the dataset lists only the models Microsoft sells in Azure Government,
so its gap count would always be zero.
Palette and style follow the Open Jev charts.
"""
import pathlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from govgap import dataset  # noqa: E402

SURFACE, INK, INK_2, MUTED, BASELINE = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#c3c2b7"
S1, CRITICAL = "#2a78d6", "#d03b3b"
GAP = {"not-available", "no-plans"}
OUT = pathlib.Path(__file__).parent / "charts"


def style():
    matplotlib.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "text.color": INK, "axes.labelcolor": INK_2, "xtick.color": MUTED, "ytick.color": INK_2,
        "axes.edgecolor": BASELINE, "axes.linewidth": 1.0,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": BASELINE, "grid.alpha": 0.45, "grid.linewidth": 0.8,
        "font.size": 11, "axes.titlesize": 13, "axes.titleweight": "bold",
        "axes.titlelocation": "left", "axes.titlepad": 12, "figure.dpi": 120,
    })


def counts(ds):
    pp = [f for f in ds.facts if f.by == "tenant"]
    tiers = []
    for key, label in (("gcc", "GCC"), ("gcchigh", "GCC High"), ("dod", "DoD")):
        n = sum(1 for f in pp if f.status[key] in GAP or f.status[key].startswith("planned:"))
        tiers.append((label, n))
    services = []
    for prefix, label in (("azure-ml/", "Azure Machine Learning"), ("sentinel/", "Microsoft Sentinel"),
                          ("defender-for-cloud/", "Defender for Cloud"), ("ai-language/", "Azure AI Language")):
        fs = [f for f in ds.facts if f.feature.startswith(prefix) and f.by == "azure"]
        gap = sum(1 for f in fs if f.status.get("government") in GAP)
        services.append((label, gap, len(fs)))
    return len(pp), tiers, services


def main():
    ds = dataset.load()
    style()
    n_pp, tiers, services = counts(ds)
    fig, (a, b) = plt.subplots(1, 2, figsize=(12.5, 4.6), gridspec_kw={"width_ratios": [1, 1.25]})

    labels = [t for t, _ in tiers][::-1]
    vals = [n for _, n in tiers][::-1]
    a.barh(labels, vals, color=S1, height=0.55)
    for y, v in enumerate(vals):
        a.text(v + 0.8, y, f"{v} of {n_pp}", va="center", fontsize=11, color=INK, fontweight="bold")
    a.set_xlim(0, n_pp)
    a.set_title(f"Power Platform: the same {n_pp} features, by tier")
    a.set_xlabel("features not available today (includes ones Microsoft lists with a future date)")
    a.grid(axis="y", visible=False)

    labels = [s for s, _, _ in services][::-1]
    gaps = [g for _, g, _ in services][::-1]
    totals = [t for _, _, t in services][::-1]
    b.barh(labels, totals, color=BASELINE, height=0.55, label="available in Azure Government")
    b.barh(labels, gaps, color=CRITICAL, height=0.55, label="not available in Azure Government")
    for y, (g, t) in enumerate(zip(gaps, totals)):
        b.text(t + 0.6, y, f"{g} of {t}", va="center", fontsize=11, color=INK, fontweight="bold")
    b.set_xlim(0, max(totals) + 8)
    b.set_title("Azure services: tracked features missing in Azure Government")
    b.set_xlabel("features govgap tracks for each service")
    b.grid(axis="y", visible=False)
    b.legend(loc="lower right", frameon=False, fontsize=9)

    for ax in (a, b):
        ax.set_axisbelow(True)
    fig.text(0.0, 1.0, f"Gaps in govgap's dataset, from Microsoft's own tables (pages checked {ds.checked}). "
                       "Counts are of tracked features, not a share of each product.",
             ha="left", va="bottom", fontsize=10, color=INK_2, transform=fig.transFigure)
    fig.tight_layout()
    OUT.mkdir(exist_ok=True)
    out = OUT / "gaps.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")
    print("tiers", tiers)
    print("services", services)


if __name__ == "__main__":
    main()
