"""Processed panels, figures, latest.json and the README's 'Latest reading' block.

Everything here is computed from data/raw and data/cache, so it runs in a few seconds and can
be rerun after every download.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pandas as pd

from . import chile, iagc
from .figstyle import charts, picture

ROOT = Path(".")
OUT = ROOT / "data" / "processed"
FIG = ROOT / "docs" / "figures"
REPO = "github.com/IgnacioMendozaRojas/ownership-and-boards"
CL_SOURCE = f"Source: CMF company pages (12 largest shareholders, December of each year). {REPO}"
ES_SOURCE = f"Source: CNMV annual corporate governance reports (IAGC), sections A.2 and C.1. {REPO}"
MIN_BOARD = 5
OWNER_LABEL = {
    "nonprofit": "Foundation",
    "state": "State",
    "family": "Family",
    "institutional": "Institutional investor",
    "bank": "Bank",
    "corporate": "Corporation",
    "state_foreign": "Foreign state",
    "individual": "Individual",
    "other": "Other",
}  # board registers below this size are incomplete in the CMF data


def build() -> dict[str, pd.DataFrame]:
    cl = chile.build(ROOT / "data" / "raw" / "cl")["panel"]
    es = iagc.build(ROOT / "data" / "cache" / "iagc")
    rep, hold = es["reports"], es["holders"]
    rep["dom_share"] = rep["n_dom"] / rep["board_size"]
    rep["ind_share"] = rep["n_ind"] / rep["board_size"]
    rep["exec_share"] = rep["n_exec"] / rep["board_size"]
    rep["constellation"] = rep.apply(constellation, axis=1)
    rep["pay_per_director"] = rep["board_pay"] / rep["board_size"]
    cl["board_complete"] = cl["board_size"] >= MIN_BOARD
    OUT.mkdir(parents=True, exist_ok=True)
    cl.to_csv(OUT / "panel_cl.csv", index=False)
    rep.to_csv(OUT / "panel_es.csv", index=False)
    hold.to_csv(OUT / "holders_es.csv", index=False)
    return {"cl": cl, "es": rep, "holders": hold}


def fig_concentration(cl: pd.DataFrame) -> str:
    g = cl.groupby("year").agg(top1=("top1_pct", "median"), contest=("contest", "median"))
    y0, y1 = int(g.index.min()), int(g.index.max())
    a, b = g["top1"].iloc[0], g["top1"].iloc[-1]
    title = f"Chile: the largest shareholder's median stake rose from {a:.0f}% to {b:.0f}%"
    sub = (
        f"{cl['rut'].nunique()} large listed firms, {y0}-{y1}: median stake of the largest holder, "
        "and 2nd holder's stake / 1st's"
    )
    for c in charts(title, sub, CL_SOURCE):
        c.line(list(g.index), list(g["top1"] / 100), 0, "Largest holder's stake")
        c.line(list(g.index), list(g["contest"]), 1, "2nd / 1st holder")
        c.yaxis(pct=True)
        k = int(g["contest"].values.argmin())
        c.note(
            (g.index[k], g["contest"].iloc[k]),
            f"Contestability lowest in {g.index[k]}: {g['contest'].iloc[k]:.2f}",
            xytext=(-200, 70),
        )
        c.save(FIG, "concentration")
    return title


def fig_representation(es: pd.DataFrame) -> str:
    year = int(es["year"].max())
    now = es[es["year"] == year]
    last = now[now["holders_complete"]]
    left_out = sorted(now.loc[~now["holders_complete"], "firm"])
    gap = last.assign(gap=last["top1_pct"] / 100 - last["dom_share"]).sort_values("gap")
    top = gap.iloc[-1]
    title = (
        f"Spain: {top['firm']}'s largest owner holds {top['top1_pct']:.0f}% of votes "
        f"but {top['dom_share']:.0%} of seats as dominicales"
    )
    sub = (
        f"{len(last)} of {len(now)} IBEX firms in {year}: largest owner's votes vs. dominical seats"
    )
    if left_out:
        sub += f" ({', '.join(left_out)} left out: holdings table not read in full)"
    for c in charts(title, sub, ES_SOURCE, size=(9, 5.2)):
        ax = c.ax
        ax.plot([0, 1], [0, 1], color=c.t["muted"], linewidth=0.8, linestyle=(0, (2, 2)))
        ax.text(
            0.62,
            0.66,
            "Seats in proportion to votes",
            color=c.t["muted"],
            fontsize=8,
            rotation=33,
            rotation_mode="anchor",
        )
        kind = last["top1_type"].fillna("other").map(lambda t: OWNER_LABEL.get(t, t))
        for i, t in enumerate(sorted(kind.unique())):
            d = last[kind == t]
            ax.scatter(
                d["top1_pct"] / 100, d["dom_share"], s=46, color=c.color(i), label=t, zorder=3
            )
        many = last.sort_values("dom_share").iloc[-1]
        c.note(
            (many["top1_pct"] / 100, many["dom_share"]),
            f"{many['firm']}: {int(many['n_sig'])} significant holders,\nnone above "
            f"{many['top1_pct']:.0f}%, share the board",
            xytext=(60, -50),
        )
        for _, r in last.iterrows():
            ax.annotate(
                f" {r['firm']}",
                (r["top1_pct"] / 100, r["dom_share"]),
                fontsize=8.5,
                color=c.t["text"],
                va="center",
            )
        ax.set_xlim(0, 0.8)
        ax.set_ylim(0, 0.8)
        c.yaxis(pct=True)
        from matplotlib.ticker import PercentFormatter

        ax.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
        c.xlabel("Largest owner's voting stake")
        ax.set_ylabel("Dominical directors / board", color=c.t["muted"], fontsize=9)
        c.legend(loc="upper left")
        c.save(FIG, "representation")
    return title


def constellation(row) -> str:
    """Owner constellation of a Spanish firm-year, from its significant holdings (3% or more)."""
    if pd.isna(row["top1_pct"]):
        return "Unknown"
    if row["top1_pct"] >= 50:
        return "Controlled"
    if row["n_sig"] >= 2:
        return "Several significant owners"
    return "One minority blockholder"


GROUP_PHRASE = {
    "Controlled": "controlled firms",
    "Several significant owners": "firms with several owners",
    "One minority blockholder": "firms with one blockholder",
    "Unknown": "firms with unread holdings",
}


def pay_ready(es: pd.DataFrame) -> bool:
    """Draw the pay chart only when the latest year's pay is read for most firms and for more
    than one constellation; otherwise a partial read would look like a finding."""
    d = es[es["year"] == es["year"].max()]
    ok = d.dropna(subset=["board_pay"])
    return len(ok) >= 0.8 * len(d) and ok["constellation"].nunique() >= 2


def fig_pay(es: pd.DataFrame) -> str:
    """Board pay per director by firm in the latest year with pay, grouped by constellation."""
    d = es.dropna(subset=["board_pay", "board_size"])
    year = int(d["year"].max())
    now = d[(d["year"] == year) & d["holders_complete"]].copy()
    now["per_dir"] = now["board_pay"] / now["board_size"]
    med = now.groupby("constellation")["per_dir"].median()
    hi, lo = med.idxmax(), med.idxmin()
    title = (
        f"Spain: board pay per director, €{med[hi]:,.0f}k in {GROUP_PHRASE[hi]} "
        f"and €{med[lo]:,.0f}k in {GROUP_PHRASE[lo]}"
    )
    sub = (
        f"Median board pay per director, thousand euros, {len(now)} IBEX firms in {year}; "
        "the board's pay includes executive directors"
    )
    now = now.sort_values("per_dir", ascending=False)
    labels = [f"{r.firm} ({r.constellation.lower()})" for r in now.itertuples()]
    for c in charts(title, sub, ES_SOURCE):
        c.hbars(
            labels,
            list(now["per_dir"]),
            fmt="€{:,.0f}k",
            highlight={lab for lab, g in zip(labels, now["constellation"], strict=True) if g == hi},
            sort=False,
        )
        c.fig.subplots_adjust(left=0.42, right=0.9)
        c.save(FIG, "pay")
    return title


def fig_independence(es: pd.DataFrame) -> str:
    g = es.groupby("year")[["ind_share", "dom_share", "exec_share"]].mean()
    title = (
        f"Spain: independents rose from {g['ind_share'].iloc[0]:.0%} to "
        f"{g['ind_share'].iloc[-1]:.0%} of the board"
    )
    span = f"{g.index.min()}-{g.index.max()}"
    sub = f"Average board composition, {es['nif'].nunique()} IBEX firms, {span}"
    for c in charts(title, sub, ES_SOURCE):
        c.line(list(g.index), list(g["ind_share"]), 0, "Independent")
        c.line(list(g.index), list(g["dom_share"]), 1, "Dominical")
        c.line(list(g.index), list(g["exec_share"]), 2, "Executive")
        c.yaxis(pct=True)
        c.ax.set_ylim(0, 0.7)
        c.save(FIG, "independence")
    return title


def metric(id_, label, value, unit, period, previous=None) -> dict:
    m = {"id": id_, "label": label, "value": round(float(value), 4), "unit": unit, "period": period}
    if previous is not None:
        m["previous"] = round(float(previous), 4)
        m["change"] = round(float(value) - float(previous), 4)
        m["change_type"] = "absolute"
    return m


def latest(cl: pd.DataFrame, es: pd.DataFrame) -> dict:
    gcl = cl.groupby("year").median(numeric_only=True)
    ges = es.groupby("year").mean(numeric_only=True)
    y1, y0 = int(gcl.index.max()), int(gcl.index.min())
    e1, e0 = int(ges.index.max()), int(ges.index.min())
    metrics = [
        metric(
            "cl_top1_median",
            "Chile: largest holder's stake, median",
            gcl["top1_pct"][y1],
            "%",
            str(y1),
            gcl["top1_pct"][y0],
        ),
        metric(
            "cl_contest_median",
            "Chile: 2nd / 1st holder, median",
            gcl["contest"][y1],
            "ratio",
            str(y1),
            gcl["contest"][y0],
        ),
        metric(
            "cl_holders_median",
            "Chile: number of shareholders, median",
            gcl["n_holders"][y1],
            "holders",
            str(y1),
            gcl["n_holders"][y0],
        ),
        metric(
            "es_ind_share",
            "Spain: independent directors, average share",
            ges["ind_share"][e1],
            "share",
            str(e1),
            ges["ind_share"][e0],
        ),
        metric(
            "es_dom_share",
            "Spain: dominical directors, average share",
            ges["dom_share"][e1],
            "share",
            str(e1),
            ges["dom_share"][e0],
        ),
    ]
    headline = (
        f"In {y1} the largest shareholder of a large Chilean listed firm held a median "
        f"{gcl['top1_pct'][y1]:.0f}% (against {gcl['top1_pct'][y0]:.0f}% in {y0}); in Spain, "
        f"independents held {ges['ind_share'][e1]:.0%} of board seats and dominicales "
        f"{ges['dom_share'][e1]:.0%} in {e1}."
    )
    return {
        "schema": 1,
        "id": "ownership-and-boards",
        "repo": "ownership-and-boards",
        "title": "Ownership constellations and board seats in Chile and Spain",
        "question": "How do combinations of owners translate into board seats in two markets "
        "with concentrated ownership?",
        "as_of": str(max(y1, e1)),
        "frequency": "annual",
        "updated": date.today().isoformat(),
        "source": "CMF company pages (Chile); CNMV annual corporate governance reports (Spain)",
        "headline": headline,
        "metrics": metrics,
        "baseline": f"Chile {y0}, Spain {e0}",
        "sample": f"{cl['rut'].nunique()} Chilean and {es['nif'].nunique()} Spanish listed firms "
        "(pilot)",
    }


def fmt(m: dict, key: str) -> str:
    v = m.get(key)
    if v is None:
        return ""
    if m["unit"] == "%":
        return f"{v:.1f}%"
    if m["unit"] == "share":
        return f"{v:.0%}"
    if m["unit"] == "holders":
        return f"{v:,.0f}"
    return f"{v:.2f}"


def readme_block(doc: dict) -> str:
    rows = [
        "| Indicator | Latest | Baseline | Change |",
        "|---|---:|---:|---:|",
    ]
    for m in doc["metrics"]:
        ch = m.get("change")
        if m["unit"] == "share":
            chs = f"{ch * 100:+.0f} pp"
        elif m["unit"] == "%":
            chs = f"{ch:+.1f} pp"
        elif m["unit"] == "holders":
            chs = f"{ch:+,.0f}"
        else:
            chs = f"{ch:+.2f}"
        rows.append(f"| {m['label']} | {fmt(m, 'value')} | {fmt(m, 'previous')} | {chs} |")
    return (
        f"**Latest reading: {doc['as_of']}.** {doc['headline']}\n\n"
        + "\n".join(rows)
        + f"\n\n*Baseline: {doc['baseline']}. Sample: {doc['sample']}. "
        + f"Updated on {doc['updated']}.*"
    )


def write_readme(doc: dict, path: Path = ROOT / "README.md") -> None:
    text = path.read_text()
    block = f"<!-- latest:start -->\n{readme_block(doc)}\n<!-- latest:end -->"
    text = re.sub(r"<!-- latest:start -->.*?<!-- latest:end -->", block, text, flags=re.S)
    path.write_text(text)


def main() -> dict:
    data = build()
    titles = {
        "concentration": fig_concentration(data["cl"]),
        "representation": fig_representation(data["es"]),
        "independence": fig_independence(data["es"]),
        "pay": fig_pay(data["es"]) if pay_ready(data["es"]) else "",
    }
    doc = latest(data["cl"], data["es"])
    (ROOT / "latest.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    write_readme(doc)
    for k, t in titles.items():
        print(f"::notice title=figure {k}::{t}")
    es = data["es"]
    got = es["board_pay"].notna()
    missing = ", ".join(f"{r.firm} {r.year}" for r in es[~got].itertuples())
    print(
        f"::notice title=pay::board pay read in {got.sum()} of {len(es)} reports; "
        f"missing: {missing}"
    )
    print(f"::notice title=latest::{doc['headline']}")
    return {"titles": titles, "latest": doc, "picture": picture}
