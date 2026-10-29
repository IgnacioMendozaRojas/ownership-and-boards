"""CMF company pages: issuers list, 12 largest shareholders, number of shareholders, board history.

These are the public company pages of cmfchile.cl, not the CMF API, so they use none of its
monthly request quota.
"""

from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup

from .web import Web

BASE = "https://www.cmfchile.cl/institucional/mercados"
TABS = {"top12": 5, "holders": 21, "board": 46}


def norm(text: str) -> str:
    """Upper case without accents or repeated spaces, for matching names."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text).strip().upper()


def number(text: str) -> float | None:
    """'790.581.560' -> 790581560; '60,82%' -> 60.82; '' -> None."""
    t = text.replace("%", "").replace(".", "").replace(",", ".").strip()
    try:
        return float(t)
    except ValueError:
        return None


def entity_url(rut: str, tab: int) -> str:
    return (
        f"{BASE}/entidad.php?mercado=V&rut={rut}&grupo=&tipoentidad=RVEMI&row=&vig=VI"
        f"&control=svs&pestania={tab}"
    )


def form_data(rut: str, tab: int, **extra: str) -> dict:
    base = {"mercado": "V", "rut": rut, "grupo": "", "tipoentidad": "RVEMI", "row": ""}
    return {**base, "vig": "VI", "control": "svs", "pestania": str(tab), **extra}


def table_after(html: str, header: str) -> list[list[str]]:
    """Body rows of the first table whose header row contains `header`."""
    soup = BeautifulSoup(html, "lxml")
    for t in soup.find_all("table"):
        rows = [
            [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            for tr in t.find_all("tr")
        ]
        for i, r in enumerate(rows):
            if any(header.lower() in c.lower() for c in r):
                return [x for x in rows[i + 1 :] if x and any(x)]
    return []


# --- parsing (pure, tested offline) -----------------------------------------------------------


def parse_issuers(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for a in soup.find_all("a", href=re.compile(r"entidad\.php.*rut=\d+")):
        rut = re.search(r"rut=(\d+)", a["href"]).group(1)
        name = a.get_text(" ", strip=True)
        if name and not re.fullmatch(r"[\d\.\-kK]+", name):
            out.append({"rut": rut, "name": name})
    seen, unique = set(), []
    for x in out:
        if x["rut"] not in seen:
            seen.add(x["rut"])
            unique.append(x)
    return unique


def parse_top12(html: str) -> list[dict]:
    rows = table_after(html, "% de propiedad")
    out = []
    for rank, r in enumerate(rows, start=1):
        if len(r) < 4 or number(r[3]) is None:
            continue
        out.append(
            {
                "rank": rank,
                "holder": r[0],
                "shares_subscribed": number(r[1]),
                "shares_paid": number(r[2]),
                "pct": number(r[3]),
            }
        )
    return out


def parse_n_holders(html: str) -> int | None:
    text = BeautifulSoup(html, "lxml").get_text(" ")
    m = re.search(r"registros\s*:\s*([\d\.]+)", text)
    return int(m.group(1).replace(".", "")) if m else None


def parse_board(html: str, history: bool) -> list[dict]:
    """Current board (no end date) or the history table that carries 'Fecha término'."""
    rows = table_after(html, "Fecha término" if history else "Fecha Nombramiento")
    out = []
    for r in rows:
        if len(r) < 4 or not re.match(r"[\d\.]+-[\dkK]", r[0]):
            continue
        out.append(
            {
                "director_rut": r[0].replace(".", "").upper(),
                "director": re.sub(r"\s+", " ", r[1]),
                "role": r[2],
                "appointed": r[3],
                "ended": r[4] if history and len(r) > 4 else "",
            }
        )
    return out


# --- fetching -----------------------------------------------------------------------------------


def issuers(web: Web) -> list[dict]:
    r = web.get(f"{BASE}/consulta.php?mercado=V&Estado=VI&entidad=RVEMI")
    return parse_issuers(r.text)


def top12(web: Web, rut: str, year: int, month: int) -> list[dict]:
    tab = TABS["top12"]
    r = web.post(entity_url(rut, tab), data=form_data(rut, tab, mm=f"{month:02d}", aa=str(year)))
    return parse_top12(r.text)


def n_holders(web: Web, rut: str, year: int, month: int) -> int | None:
    tab = TABS["holders"]
    r = web.post(entity_url(rut, tab), data=form_data(rut, tab, mm=f"{month:02d}", aa=str(year)))
    return parse_n_holders(r.text)


def board(web: Web, rut: str, start: str, end: str) -> list[dict]:
    """Current board plus every director in office between start and end (dd/mm/yyyy).

    The history form only answers after a first visit to the page (session cookie)."""
    url = entity_url(rut, TABS["board"])
    current = parse_board(web.get(url).text, history=False)
    r = web.post(url, data={"txt_inicio": start, "txt_termino": end}, headers={"Referer": url})
    past = parse_board(r.text, history=True)
    return [{**x, "source": "current"} for x in current] + [
        {**x, "source": "history"} for x in past
    ]
