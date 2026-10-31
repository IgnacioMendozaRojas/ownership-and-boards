"""Parse the CNMV annual corporate governance report (IAGC): board composition by category, the
significant shareholdings (section A.2) and the voting rights represented on the board.

Board counts come from the model's summary lines ('Número total de consejeros dominicales 6'),
which every report since 2015 carries. Section A.2 is a table whose long names wrap above and
below the row of percentages, so it is read from word positions: each line with a total % is an
anchor, and each name fragment joins the nearest anchor vertically.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import yaml

from . import cnmv
from .cmf import norm
from .owners import owner_type

HOLDERS_FILE = Path("config") / "holders_es.yaml"

COUNTS = {
    "board_size": r"N[uú]mero total de consejeros\s+(\d+)\b",
    "n_exec": r"N[uú]mero total de consejeros ejecutivos\s+(\d+)",
    "n_dom": r"N[uú]mero total de consejeros dominicales\s+(\d+)",
    "n_ind": r"N[uú]mero total de consejeros independientes\s+(\d+)",
}
# Pay in thousand euros. The board's figure includes executive directors' pay as directors and
# as executives; senior management excludes executive directors.
PAY = {
    "board_pay": r"Remuneraci[oó]n\s+(?:devengada\s+en\s+el\s+ejercicio\s+a\s+favor\s+)?del\s+"
    r"consejo\s+de\s+administraci[oó]n\s*\((?:en\s+)?miles\s+de\s+euros\)[^\d\n]{0,40}"
    r"\n?[^\d\n]{0,20}(\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?)",
    "mgmt_pay": r"Remuneraci[oó]n\s+total\s+(?:de\s+la\s+)?alta\s+direcci[oó]n\s*"
    r"\((?:en\s+)?miles\s+de\s+euros\)[^\d\n]{0,40}\n?[^\d\n]{0,20}"
    r"(\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?)",
}


def thousands(token: str) -> float:
    """'12.345' -> 12345.0; '1.234,5' -> 1234.5 (Spanish separators)."""
    return float(token.replace(".", "").replace(",", "."))


VOTES_ON_BOARD = r"derechos de voto representados en el consejo de administraci[oó]n\s+([\d\.,]+)"
NUM = re.compile(r"^\d{1,3}(\.\d{3})*(,\d+)?%?$|^\d+(,\d+)?%?$")
HEADER = re.compile(
    r"nombre|denominaci|accionista|directo|indirecto|derechos|voto|social del|instrumentos|"
    r"atribuidos|financieros|% total|n[uú]mero de|sobre el total|participaci[oó]n|ejercicio|"
    r"consejeros",
    re.I,
)
# running headers and footers of reports in free format
NOISE = re.compile(
    r"Informe|Memoria|Índice|Bloque C|IAGC|Estructura de la|Operaciones vinculadas|SCIIF|"
    r"Grado de seguimiento|gesti[oó]n de riesgos|^corporativo$|^\d+$"
)
END = re.compile(
    r"Detalle de la participaci[oó]n indirecta|A trav[eé]s de:|Indique los movimientos|"
    r"^A\.3\b|Observaciones",
    re.I,
)


def pct(token: str) -> float | None:
    t = token.replace("%", "").replace(".", "").replace(",", ".")
    try:
        v = float(t)
    except ValueError:
        return None
    return v if 0 <= v <= 100 else None


def lines_of(words: list[list], tol: float = 3.0) -> list[dict]:
    """Group words [x0, x1, top, text] into lines by their top coordinate."""
    lines: list[dict] = []
    for w in sorted(words, key=lambda w: (w[2], w[0])):
        if lines and abs(lines[-1]["top"] - w[2]) <= tol:
            lines[-1]["words"].append(w)
        else:
            lines.append({"top": w[2], "words": [w]})
    for ln in lines:
        ln["words"].sort(key=lambda w: w[0])
        ln["text"] = " ".join(w[3] for w in ln["words"])
    return lines


def a2_sections(pages: list[dict]) -> list[list[dict]]:
    """Lines of each A.2 section (heading to the next sub-table), across a page break.

    Reports in free format repeat A.2 in the statistical annex, sometimes after an empty table
    in the main text, so every section is returned and the first one with rows is used."""
    sections: list[list[dict]] = []
    cur: list[dict] | None = None
    for p in pages:
        for ln in lines_of(p["words"]):
            if re.match(r"A\.2\.?\s.*(Detalle|titulares)", ln["text"]):
                if cur:
                    sections.append(cur)
                cur = []
                continue
            if cur is not None and END.search(ln["text"]):
                sections.append(cur)
                cur = None
                continue
            if cur is not None:
                cur.append({**ln, "page": p["page"]})
    if cur:
        sections.append(cur)
    return sections


def split_gaps(above_first: int, gaps: list[int], below_last: int) -> list[int]:
    """How many fragments of each gap between anchors belong to the upper anchor.

    A name cell is centred on its row of percentages, so each anchor should have about as many
    name lines above it as below; the split that best balances every anchor is chosen."""
    n = len(gaps)
    if n == 0:
        return []
    # best[i][s]: minimal imbalance of anchors 0..i when gap i gives s lines to anchor i
    best = [dict() for _ in range(n)]
    for s0 in range(gaps[0] + 1):
        best[0][s0] = (abs(above_first - s0), [s0])
    for i in range(1, n):
        for si in range(gaps[i] + 1):
            cands = []
            for sp, (cost, path) in best[i - 1].items():
                above_i = gaps[i - 1] - sp
                cands.append((cost + abs(above_i - si), path + [si]))
            best[i][si] = min(cands, key=tie_break)
    final = min(
        ((cost + abs((gaps[-1] - s) - below_last), path) for s, (cost, path) in best[-1].items()),
        key=tie_break,
    )
    return final[1]


def tie_break(item: tuple[int, list[int]]) -> tuple:
    """Lowest imbalance first; on a tie, a wrapped line stays with the name above it."""
    cost, path = item
    return (cost, [-x for x in path])


def parse_section(lines: list[dict]) -> list[dict]:
    lines = [ln for ln in lines if not NOISE.search(ln["text"])]
    anchors = []
    for i, ln in enumerate(lines):
        nums = [w for w in ln["words"] if NUM.match(w[3])]
        if nums and pct(nums[-1][3]) is not None and ("," in nums[-1][3] or "%" in nums[-1][3]):
            anchors.append({"i": i, "x_num": nums[0][0], "total": pct(nums[-1][3]), "name": []})
    if not anchors:
        return []
    # Table rows start their numbers in the numeric columns; a footnote that quotes a
    # percentage starts its numbers at the left margin, so it is not a row.
    xs = sorted(a["x_num"] for a in anchors)
    column = xs[len(xs) // 2]
    anchors = [a for a in anchors if a["x_num"] >= column - 60]
    limit = min(a["x_num"] for a in anchors) - 2
    first = anchors[0]["i"]
    frag = {}
    for i, ln in enumerate(lines):
        text = " ".join(w[3] for w in ln["words"] if w[1] <= limit).strip()
        if text and not (i < first and HEADER.search(text)):
            frag[i] = text
    idx = [a["i"] for a in anchors]
    # name lines just above the first anchor (a cell spans a few lines at most) and below the last
    above_first = [i for i in frag if first - 4 <= i < first]
    below_last = [i for i in frag if idx[-1] < i <= idx[-1] + 4]
    gaps = [[i for i in frag if lo < i < hi] for lo, hi in zip(idx, idx[1:], strict=False)]
    splits = split_gaps(len(above_first), [len(g) for g in gaps], len(below_last))
    for k, a in enumerate(anchors):
        parts = []
        if k == 0:
            parts += above_first
        else:
            parts += gaps[k - 1][splits[k - 1] :]
        parts.append(a["i"])
        if k < len(gaps):
            parts += gaps[k][: splits[k]]
        else:
            parts += below_last
        a["name"] = [frag[i] for i in sorted(parts) if i in frag]
        a["parts"] = sorted(i for i in parts if i in frag)
    # A row of percentages with no name line at all has lost its name to a neighbour that
    # already has its own: give it back the wrapped lines between the two rows.
    for k, a in enumerate(anchors):
        if a["parts"]:
            continue
        for nb in (anchors[k - 1] if k else None, anchors[k + 1] if k + 1 < len(anchors) else None):
            if nb is None or nb["i"] not in nb["parts"]:
                continue
            lo, hi = sorted((nb["i"], a["i"]))
            moved = [i for i in nb["parts"] if lo < i < hi]
            if moved:
                nb["parts"] = [i for i in nb["parts"] if i not in moved]
                nb["name"] = [frag[i] for i in nb["parts"]]
                a["parts"] = moved
                a["name"] = [frag[i] for i in moved]
                break
    # Matching runs in two passes. First, a row whose assembled name holds exactly one known
    # holder takes it. Then the remaining rows (no known name, or two names mixed by wrapping)
    # take the holder from an order-preserving alignment of name lines with rows. Rows left
    # unmatched keep the assembled text and are flagged downstream.
    known = known_holders()
    hits = sorted(
        {(i, j) for i, t in frag.items() for j, h in enumerate(known) if h["rx"].search(norm(t))}
    )
    aligned = align([a["i"] for a in anchors], hits)
    chosen: dict[int, int] = {}
    for k, a in enumerate(anchors):
        raw = " ".join(a["name"])
        in_raw = [j for j, h in enumerate(known) if h["rx"].search(norm(raw))]
        if len(in_raw) == 1:
            chosen[k] = in_raw[0]
    for k, j in aligned.items():
        if k not in chosen and j not in chosen.values():
            chosen[k] = j
    out, used = [], set()
    for k, a in enumerate(anchors):
        raw = re.sub(r"\s+", " ", " ".join(a["name"])).strip(" ,")
        words = raw.split()
        lower = sum(w[:1].islower() for w in words)
        prose = (len(words) >= 2 and lower >= len(words) / 2) or (len(words) > 10 and lower >= 3)
        if k in chosen and chosen[k] not in used:
            h = known[chosen[k]]
            used.add(chosen[k])
            out.append({"holder": h["name"], "type": h["type"], "pct": a["total"], "raw": raw})
        elif raw and not prose:  # footnote prose that carries a percentage is not a holder
            out.append({"holder": raw, "type": None, "pct": a["total"], "raw": raw})
    return out


def align(anchors: list[int], hits: list[tuple[int, int]], reach: int = 4) -> dict[int, int]:
    """Order-preserving alignment of anchor lines with holder hits (line, holder): most pairs,
    then smallest total distance. Returns anchor position -> holder index."""
    hits = sorted(hits)
    n, m = len(anchors), len(hits)
    best = [[(0, 0)] * (m + 1) for _ in range(n + 1)]
    move = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            options = [(best[i - 1][j], "skip_a"), (best[i][j - 1], "skip_h")]
            d = abs(anchors[i - 1] - hits[j - 1][0])
            if d <= reach:
                c, dist = best[i - 1][j - 1]
                options.append(((c + 1, dist - d), "pair"))
            best[i][j], move[i][j] = max(options, key=lambda o: o[0])
    out, i, j = {}, n, m
    while i > 0 and j > 0:
        step = move[i][j]
        if step == "pair":
            out[i - 1] = hits[j - 1][1]
            i, j = i - 1, j - 1
        elif step == "skip_a":
            i -= 1
        else:
            j -= 1
    return out


def firm_names() -> dict[str, str]:
    path = Path(__file__).resolve().parents[2] / "config" / "pilot.yaml"
    if not path.exists():
        path = Path("config") / "pilot.yaml"
    if not path.exists():
        return {}
    return {str(k): v for k, v in yaml.safe_load(path.read_text())["spain"]["firms"].items()}


_KNOWN: list[dict] | None = None


def known_holders() -> list[dict]:
    global _KNOWN
    if _KNOWN is None:
        path = Path(__file__).resolve().parents[2] / HOLDERS_FILE
        if not path.exists():
            path = HOLDERS_FILE
        rows = yaml.safe_load(path.read_text()) if path.exists() else []
        _KNOWN = [{**r, "rx": re.compile(r["pattern"])} for r in rows]
    return _KNOWN


def parse_a2(pages: list[dict]) -> list[dict]:
    for section in a2_sections(pages):
        rows = parse_section(section)
        if rows:
            return rows
    return []


def parse_report(rec: dict) -> dict:
    text = "\n".join(p["text"] for p in rec["pages"])
    row: dict = {"nif": rec["nif"], "firm": rec["firm"], "year": rec["year"]}
    for key, rx in COUNTS.items():
        m = re.search(rx, text, re.I)
        row[key] = int(m.group(1)) if m else None
    if row["board_size"] is not None:
        row["n_dom"] = row["n_dom"] or 0  # the line is absent when there are none
        known = sum(row[k] or 0 for k in ("n_exec", "n_dom", "n_ind"))
        row["n_other"] = row["board_size"] - known
    m = re.search(VOTES_ON_BOARD, text, re.I)
    row["votes_on_board"] = pct(m.group(1)) if m else None
    for key, rx in PAY.items():
        m = re.search(rx, text, re.I)
        row[key] = thousands(m.group(1)) if m else None
    row["holders"] = parse_a2(rec["pages"])
    return row


def build(cache: Path) -> dict[str, pd.DataFrame]:
    reports, holders = [], []
    for path in sorted(cache.glob("*.json.gz")):
        r = parse_report(cnmv.load_cache(path))
        for h in r.pop("holders"):
            holders.append({"nif": r["nif"], "firm": r["firm"], "year": r["year"], **h})
        reports.append(r)
    rep = pd.DataFrame(reports)
    hold = pd.DataFrame(holders)
    # display names come from the sample configuration (with accents), not from the cache
    names = firm_names()
    rep["firm"] = rep["nif"].map(names).fillna(rep["firm"])
    if not hold.empty:
        hold["firm"] = hold["nif"].map(names).fillna(hold["firm"])
    if not hold.empty:
        guess = hold["holder"].map(lambda n: owner_type(n, country="es"))
        hold["matched"] = hold["type"].notna()
        hold["type"] = hold["type"].fillna(guess)
        # family vehicles count together: 'Tussen de Grachten (Entrecanales)' -> 'Entrecanales'
        fam = hold["holder"].str.extract(r"\(([^)]*)\)$")[0].str.replace(" family", "")
        hold["owner"] = hold["holder"].where(hold["type"] != "family", fam + " family")
        owners = (
            hold.groupby(["nif", "year", "owner"], as_index=False)
            .agg(pct=("pct", "sum"), type=("type", "first"))
            .rename(columns={"owner": "holder"})
        )
        agg = owners.sort_values("pct", ascending=False).groupby(["nif", "year"])
        top = agg.agg(
            top1_holder=("holder", "first"),
            top1_type=("type", "first"),
            top1_pct=("pct", "first"),
            sig_pct=("pct", "sum"),
            n_sig=("pct", "size"),
        ).reset_index()
        rep = rep.merge(top, on=["nif", "year"], how="left")
        # a year's holdings table counts as read in full when every row matched a known holder
        unmatched = hold.groupby(["nif", "year"])["matched"].apply(lambda m: (~m).sum())
        rep = rep.merge(
            unmatched.rename("n_unmatched").reset_index(), on=["nif", "year"], how="left"
        )
        rep["holders_complete"] = rep["n_sig"].notna() & (rep["n_unmatched"] == 0)
    return {"reports": rep, "holders": hold}
