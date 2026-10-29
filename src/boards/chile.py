"""Chile: ownership constellations from the 12 largest shareholders, and boards at each year end.

Measures per firm and year (December):
- concentration: largest holder's stake, top-3, Herfindahl over the 12 largest, and the
  second-to-first ratio (contestability of control)
- stakes by owner type (pension funds summed over AFPs and fund types)
- constellation: the owner types holding 5% or more
- board: size, and seats held by directors who also sit on the board of a listed shareholder in
  the sample (the controller's people on the board, a lower bound of over-appointment)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .cmf import norm
from .owners import owner_type

BLOCK = 5.0  # % stake that makes a blockholder
TYPE_LABEL = {
    "corporate": "corporate",
    "individual": "individual",
    "pension_fund": "pension funds",
    "custodian": "custodians",
    "broker": "brokers",
    "institutional": "institutional",
    "state": "state",
    "state_foreign": "foreign state",
    "nonprofit": "foundations and associations",
}


def clean_top12(top: pd.DataFrame) -> pd.DataFrame:
    """First block of the table only: some years repeat the rows with share counts in the %
    column (values above 100), which are dropped, and at most 12 holders are kept."""
    t = top.copy()
    t["pct"] = pd.to_numeric(t["pct"], errors="coerce")
    t["rank"] = pd.to_numeric(t["rank"], errors="coerce")
    t = t[t["pct"].between(0, 100) & t["holder"].notna() & (t["holder"].astype(str) != "")]
    t = t.sort_values(["rut", "period", "rank"])
    t = t.groupby(["rut", "period"], group_keys=False).head(12)
    t["type"] = t["holder"].map(owner_type)
    return t.reset_index(drop=True)


def constellations(t: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (rut, period), g in t.groupby(["rut", "period"]):
        g = g.sort_values("pct", ascending=False)
        p = g["pct"].tolist()
        blocks = g[g["pct"] >= BLOCK]
        types = sorted(set(blocks["type"]))
        row = {
            "rut": rut,
            "period": period,
            "year": int(str(period)[:4]),
            "top1_holder": g["holder"].iloc[0],
            "top1_type": g["type"].iloc[0],
            "top1_pct": p[0],
            "top3_pct": sum(p[:3]),
            "top12_pct": sum(p),
            "hhi": sum(x * x for x in p),
            "contest": p[1] / p[0] if len(p) > 1 and p[0] > 0 else 0.0,
            "n_block": len(blocks),
            "constellation": " + ".join(TYPE_LABEL[x] for x in types) or "no blockholder",
        }
        for tp in TYPE_LABEL:
            row[f"pct_{tp}"] = g.loc[g["type"] == tp, "pct"].sum()
        rows.append(row)
    return pd.DataFrame(rows)


def to_date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")


def board_spells(board: pd.DataFrame) -> pd.DataFrame:
    """One row per director spell (appointment to end, open if still in office)."""
    b = board.copy()
    b["appointed"] = to_date(b["appointed"])
    b["ended"] = to_date(b["ended"])
    b = b.dropna(subset=["appointed"])
    return b.drop_duplicates(["rut", "director_rut", "appointed"]).reset_index(drop=True)


def boards_at(spells: pd.DataFrame, years: range) -> pd.DataFrame:
    """Directors in office on 31 December of each year."""
    out = []
    for y in years:
        day = pd.Timestamp(year=y, month=12, day=31)
        on = spells[
            (spells["appointed"] <= day) & (spells["ended"].isna() | (spells["ended"] >= day))
        ]
        on = on.drop_duplicates(["rut", "director_rut"])
        out.append(on.assign(year=y)[["rut", "year", "director_rut", "director", "role"]])
    return pd.concat(out, ignore_index=True)


def holder_firm_map(top: pd.DataFrame, firms: pd.DataFrame) -> dict[tuple[str, int], set[str]]:
    """For each firm-year, the sample firms that appear among its 12 largest holders."""
    names = {
        norm(n).replace(".", "").replace(" ", ""): r
        for r, n in zip(firms["rut"], firms["name"], strict=True)
    }
    out: dict[tuple[str, int], set[str]] = {}
    for rut, period, holder in zip(top["rut"], top["period"], top["holder"], strict=True):
        key = norm(str(holder)).replace(".", "").replace(" ", "")
        for n, r in names.items():
            if r != rut and (key == n or key.startswith(n[: max(8, len(n) - 2)])):
                out.setdefault((rut, int(str(period)[:4])), set()).add(r)
    return out


def board_metrics(on: pd.DataFrame, top: pd.DataFrame, firms: pd.DataFrame) -> pd.DataFrame:
    links = holder_firm_map(top, firms)
    seats = on.groupby(["year", "director_rut"])["rut"].apply(set).to_dict()
    rows = []
    for (rut, year), g in on.groupby(["rut", "year"]):
        holders = links.get((rut, year), set())
        n = len(g)
        shared = sum(len(seats[(year, d)]) > 1 for d in g["director_rut"])
        holder_seats = sum(bool(seats[(year, d)] & holders) for d in g["director_rut"])
        rows.append(
            {
                "rut": rut,
                "year": year,
                "board_size": n,
                "interlocked": shared,
                "listed_holders_in_sample": len(holders),
                "seats_shared_with_holder": holder_seats,
            }
        )
    return pd.DataFrame(rows)


def build(raw: Path) -> dict[str, pd.DataFrame]:
    firms = pd.read_csv(raw / "firms.csv", dtype=str)
    top = clean_top12(pd.read_csv(raw / "top12.csv", dtype={"rut": str}))
    cons = constellations(top)
    holders = pd.read_csv(raw / "holders.csv", dtype={"rut": str})
    holders["year"] = holders["period"].str[:4].astype(int)
    cons = cons.merge(holders[["rut", "year", "n_holders"]], on=["rut", "year"], how="left")
    spells = board_spells(pd.read_csv(raw / "board.csv", dtype=str))
    years = range(int(cons["year"].min()), int(cons["year"].max()) + 1)
    on = boards_at(spells, years)
    bm = board_metrics(on, top, firms)
    panel = cons.merge(bm, on=["rut", "year"], how="left").merge(firms[["rut", "name"]], on="rut")
    return {"top12": top, "panel": panel, "board": on}
