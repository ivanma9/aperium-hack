"""Chart the image-only CPI forecasts against actual CPI.

Reads results/forecast_YYYY-MM.md (Stage 2 output), results/hsai_YYYY-MM.json
(Stage 1 ship counts) and data/cpi_combined_data_2026.csv, and writes
results/forecast_vs_actual.png: Energy and All Items panels with the actual
value per month and the forecast with its 80% range, and below them the
monthly ship count measured from the images.

Usage: python scripts/plot_results.py
"""
import csv
import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
OUT = RESULTS / "forecast_vs_actual.png"

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e4e3df"
ACTUAL = "#2a78d6"    # categorical slot 1 (blue)
FORECAST = "#eb6834"  # categorical slot 2 (orange)
SHIPS = "#1baf7a"     # categorical slot 3 (aqua); bars carry value labels
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def load_actuals():
    act = {}
    for r in csv.DictReader(open(ROOT / "data" / "cpi_combined_data_2026.csv", encoding="utf-8")):
        m = f"20{r['Data_Period'][-2:]}-{MON.index(r['Data_Period'][:3]) + 1:02d}"
        act[m] = {"Energy": float(r["Energy_MoM_Percent"]),
                  "All Items": float(r["All_Items_MoM_Percent"])}
    return act


def load_forecasts():
    fc = {}
    for f in sorted(RESULTS.glob("forecast_*.md")):
        m = f.stem.split("_")[1]
        text = f.read_text(encoding="utf-8")
        fc[m] = {}
        for name in ("Energy", "All Items"):
            g = re.search(rf"\| {name} \| (-?[\d.]+) \| (-?[\d.]+) to (-?[\d.]+) \|", text)
            fc[m][name] = tuple(map(float, g.groups()))
    return fc


def load_ships():
    """month -> (large + medium vessels per image, number of images)."""
    ships = {}
    for f in sorted(RESULTS.glob("hsai_*.json")):
        j = json.loads(f.read_text(encoding="utf-8"))
        s = j["summary"]
        ships[j["period"]] = (s["large_per_image"] + s["medium_per_image"], len(j["images"]))
    return ships


def style(ax, months, extra=None):
    labels = [f"{MON[int(m[5:]) - 1]}\n{m[2:4]}" + (f"\n{extra[m]}" if extra else "") for m in months]
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRID, lw=0.8, zorder=0)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=TEXT_2, length=0, labelsize=9)
    ax.set_xticks(range(len(months)), labels)
    ax.set_xlim(-0.6, len(months) - 0.1)


def cpi_panel(ax, name, months, act, fc):
    style(ax, months)
    ax.axhline(0, color=TEXT_2, lw=0.8, zorder=1)

    # forecast: 80% range as a thin bar, point estimate as a marker
    for i, m in enumerate(months):
        if m not in fc:
            continue
        f, lo, hi = fc[m][name]
        ax.plot([i + 0.12, i + 0.12], [lo, hi], color=FORECAST, lw=2, alpha=0.45,
                solid_capstyle="round", zorder=2)
        ax.scatter(i + 0.12, f, s=55, color=FORECAST, edgecolor=SURFACE, lw=2, zorder=4)

    # actual: line + markers over the months that have published CPI
    ia = [i for i, m in enumerate(months) if m in act]
    ya = [act[months[i]][name] for i in ia]
    ax.plot([i - 0.12 for i in ia], ya, color=ACTUAL, lw=2, zorder=3)
    ax.scatter([i - 0.12 for i in ia], ya, s=55, color=ACTUAL, edgecolor=SURFACE, lw=2, zorder=5)

    # direct labels: biggest miss (actual) and the unpublished month
    miss = max(ia, key=lambda i: abs(fc[months[i]][name][0] - act[months[i]][name]))
    ax.annotate(f"actual {act[months[miss]][name]:+g}", (miss - 0.12, act[months[miss]][name]),
                xytext=(-8, 0), textcoords="offset points", ha="right", va="center",
                fontsize=9, color=TEXT)
    for i, m in enumerate(months):
        if m in fc and m not in act:
            ax.annotate(f"forecast {fc[m][name][0]:+g}\n(actual not yet\npublished)",
                        (i + 0.12, fc[m][name][0]), xytext=(10, 0), textcoords="offset points",
                        ha="left", va="center", fontsize=8.5, color=TEXT_2)

    ax.set_title(f"{name} CPI, month-over-month %", loc="left", fontsize=11, color=TEXT, pad=8)


def ship_panel(ax, months, ships):
    style(ax, months, {m: f"{ships[m][1]} img" for m in months})
    vals = [ships[m][0] for m in months]
    ax.bar(range(len(months)), vals, width=0.5, color=SHIPS, zorder=2)
    for i, v in enumerate(vals):
        ax.annotate(f"{v:.1f}", (i, v), xytext=(0, 3), textcoords="offset points",
                    ha="center", va="bottom", fontsize=9, color=TEXT)
    ax.set_ylim(0, max(vals) * 1.2)
    ax.set_title("Ships seen in the images: average large + medium vessels per image",
                 loc="left", fontsize=11, color=TEXT, pad=8)


def main():
    act, fc, ships = load_actuals(), load_forecasts(), load_ships()
    months = sorted(set(fc) | set(ships))
    scored = [m for m in fc if m in act]
    errs = {n: sum(abs(fc[m][n][0] - act[m][n]) for m in scored) / len(scored)
            for n in ("Energy", "All Items")}

    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Segoe UI", "Arial", "DejaVu Sans"]
    fig, axes = plt.subplots(3, 1, figsize=(10, 11.8), facecolor=SURFACE,
                             gridspec_kw={"height_ratios": [1, 1, 0.8]})
    cpi_panel(axes[0], "Energy", months, act, fc)
    cpi_panel(axes[1], "All Items", months, act, fc)
    ship_panel(axes[2], months, ships)

    fig.suptitle("CPI forecast from satellite images only vs actual",
                 x=0.06, y=0.99, ha="left", fontsize=15, fontweight="bold", color=TEXT)
    fig.text(0.06, 0.957,
             "The only input is Sentinel-2 ship counts in the Strait of Hormuz: no prices, news or economic data.\n"
             f"Each month is forecast with its own CPI held out (leave-one-out). "
             f"Mean absolute error: Energy {errs['Energy']:.1f} pts, All Items {errs['All Items']:.2f} pts.\n"
             "Dec 2025 has no forecast: it is only the baseline for January's change in ship counts.",
             ha="left", va="top", fontsize=9.5, color=TEXT_2)
    handles = [
        plt.Line2D([], [], color=ACTUAL, lw=2, marker="o", ms=7, mec=SURFACE, mew=2, label="Actual (BLS)"),
        plt.Line2D([], [], color=FORECAST, lw=0, marker="o", ms=7, mec=SURFACE, mew=2, label="Forecast (images only)"),
        plt.Line2D([], [], color=FORECAST, lw=2, alpha=0.45, label="Forecast 80% range"),
    ]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.055, 0.9), ncol=3,
               frameon=False, fontsize=9.5, labelcolor=TEXT, handlelength=1.8, columnspacing=2)
    fig.tight_layout(rect=(0.03, 0, 1, 0.875), h_pad=2.5)
    fig.savefig(OUT, dpi=160, facecolor=SURFACE)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
