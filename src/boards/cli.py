"""Command line: download the pilot data (resumable), parse it and build the descriptives."""

from __future__ import annotations

import argparse
import os
import re
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

from . import cmf, cnmv
from .web import BudgetSpent, Web

# Paths are relative to the repository checkout (the working directory), not the installed package
ROOT = Path(os.environ.get("BOARDS_ROOT", "."))
CONFIG = ROOT / "config" / "pilot.yaml"
RAW = ROOT / "data" / "raw"
CACHE = ROOT / "data" / "cache" / "iagc"


def notice(title: str, msg: str, level: str = "notice") -> None:
    print(f"::{level} title={title}::{msg}", flush=True)


def read_csv(path: Path, columns: list[str]) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    return pd.DataFrame(columns=columns)


def append_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=columns)
    df.to_csv(path, mode="a", header=not path.exists(), index=False)


# --- Chile --------------------------------------------------------------------------------------

LOG_COLS = ["rut", "kind", "period", "rows"]
TOP_COLS = ["rut", "period", "rank", "holder", "shares_subscribed", "shares_paid", "pct"]
HOLD_COLS = ["rut", "period", "n_holders"]
BOARD_COLS = ["rut", "director_rut", "director", "role", "appointed", "ended", "source"]


def year_range(cfg: dict, today: date | None = None) -> tuple[int, int]:
    """First and last year to cover; 'latest' means the last full year, whose December
    shareholders and annual governance reports are published by the spring."""
    y0, y1 = cfg["years"]
    if y1 == "latest":
        y1 = (today or date.today()).year - 1
    return int(y0), int(y1)


def match_firms(issuers: list[dict], patterns: list[str]) -> tuple[list[dict], list[str]]:
    found, missing = [], []
    for p in patterns:
        rx = re.compile(p)
        hits = [x for x in issuers if rx.search(cmf.norm(x["name"]))]
        if hits:
            found.append({"rut": hits[0]["rut"], "name": hits[0]["name"], "pattern": p})
        else:
            missing.append(p)
    return found, missing


def fetch_cl(web: Web, cfg: dict) -> None:
    out = RAW / "cl"
    firms_path = out / "firms.csv"
    if firms_path.exists():
        firms = pd.read_csv(firms_path, dtype=str).to_dict("records")
    else:
        firms, missing = match_firms(cmf.issuers(web), cfg["firms"])
        out.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(firms).to_csv(firms_path, index=False)
        notice("fetch_cl", f"{len(firms)} firms matched; not found: {missing}")
    log = read_csv(out / "log.csv", LOG_COLS)
    done = set(zip(log["rut"], log["kind"], log["period"], strict=True))
    y0, y1 = year_range(cfg)
    month = cfg.get("month", 12)
    for firm in firms:
        rut = firm["rut"]
        for year in range(y0, y1 + 1):
            period = f"{year}-{month:02d}"
            if (rut, "top12", period) not in done:
                rows = cmf.top12(web, rut, year, month)
                append_csv(
                    out / "top12.csv", [{"rut": rut, "period": period, **r} for r in rows], TOP_COLS
                )
                append_csv(
                    out / "log.csv",
                    [{"rut": rut, "kind": "top12", "period": period, "rows": len(rows)}],
                    LOG_COLS,
                )
            if (rut, "holders", period) not in done:
                n = cmf.n_holders(web, rut, year, month)
                append_csv(
                    out / "holders.csv", [{"rut": rut, "period": period, "n_holders": n}], HOLD_COLS
                )
                append_csv(
                    out / "log.csv",
                    [{"rut": rut, "kind": "holders", "period": period, "rows": int(n is not None)}],
                    LOG_COLS,
                )
        if (rut, "board", "all") not in done:
            rows = cmf.board(web, rut, f"01/01/{y0 - 2}", f"31/12/{y1}")
            append_csv(out / "board.csv", [{"rut": rut, **r} for r in rows], BOARD_COLS)
            append_csv(
                out / "log.csv",
                [{"rut": rut, "kind": "board", "period": "all", "rows": len(rows)}],
                LOG_COLS,
            )
        notice("fetch_cl", f"{firm['name']}: done ({web.used} requests so far)")


# --- Spain --------------------------------------------------------------------------------------


def fetch_es(web: Web, cfg: dict) -> None:
    y0, y1 = year_range(cfg)
    rows = []
    for nif, name in cfg["firms"].items():
        entries = cnmv.index(web, nif)
        if not entries:
            # say what the page holds, to see why no report was found
            html = web.get(f"{cnmv.INDEX}?nif={nif}").text
            links = len(re.findall(r"verdocumento", html))
            title = re.search(r"<title>(.*?)</title>", html, re.S)
            body = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
            i = body.find("Ejercicio")
            notice(
                "fetch_es",
                f"{name} ({nif}): {links} document links; title "
                f"{title.group(1).strip()[:60] if title else ''}; text {body[max(i, 0) : i + 300]}",
                level="warning",
            )
        rows += [
            {"nif": nif, "firm": name, **{k: e[k] for k in ("year", "registered")}} for e in entries
        ]
        if not entries:
            notice("fetch_es", f"{name} ({nif}): no reports listed", level="warning")
            continue
        got = 0
        for e in entries:
            if not y0 <= e["year"] <= y1:
                continue
            path = cnmv.cache_path(CACHE, nif, e["year"])
            if cnmv.is_current(path):
                continue
            rec = cnmv.fetch_report(web, e)
            cnmv.save_cache(path, {"nif": nif, "firm": name, **rec})
            got += 1
        notice("fetch_es", f"{name}: {len(entries)} reports listed, {got} new cached")
    if rows:
        (RAW / "es").mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(RAW / "es" / "index.csv", index=False)


# --- entry point --------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="boards")
    ap.add_argument("command", choices=["fetch-cl", "fetch-es", "report"])
    ap.add_argument("--budget", type=int, default=2500, help="max requests this run")
    args = ap.parse_args(argv)
    if args.command == "report":
        from . import report

        report.main()
        return 0
    cfg = yaml.safe_load(CONFIG.read_text())
    web = Web(pause=1.0 if args.command == "fetch-cl" else 3.0, budget=args.budget)
    try:
        if args.command == "fetch-cl":
            fetch_cl(web, cfg["chile"])
        else:
            fetch_es(web, cfg["spain"])
    except BudgetSpent as e:
        notice(args.command, f"stopped: {e}; the next run resumes", level="warning")
    notice(args.command, f"finished with {web.used} requests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
