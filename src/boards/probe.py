"""Cheap probes of the public sources: what each one returns, in what format and how far back.

Each probe fetches a handful of pages, saves a raw sample and a JSON summary under the output
folder, and prints one GitHub Actions annotation per finding. Nothing here is the pipeline: the
probes only decide which sources the pipeline can rely on.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import time
import traceback
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (X11; Linux x86_64) ownership-and-boards research probe"
# The CNMV drops requests from non-browser user agents (rounds 2 and 4 got no response at all)
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0 Safari/537.36"
)
CMF = "https://www.cmfchile.cl/institucional/mercados"
CNMV = "https://www.cnmv.es/portal/consultas/ee/informaciongobcorp"

# A few large listed firms per country; enough to see the format, not to build the panel.
CL_FIRMS = {"90690000": "Empresas Copec", "90222000": "Empresas CMPC", "90749000": "Falabella"}
# CMF company tabs: 12 largest shareholders, shareholder list, board register, directors'
# committee, annual report, governance practices, board gender
CL_TABS = {
    5: "12 mayores accionistas",
    21: "lista de accionistas",
    46: "registro de directores",
    48: "comite de directores",
    49: "memoria anual",
    76: "practicas de gobierno corporativo",
    115: "evolucion sexo directorios",
}
ES_FIRMS = {"A86212420": "Aena", "A08055741": "Mapfre", "A15075062": "Inditex"}
DOC_LINKS = r"\.pdf|\.xls|\.xbrl|\.zip|ver_?doc"
IAGC_MARKERS = ["A.2", "A.6", "C.1.2", "C.1.3", "dominical", "independiente"]


# --- pure helpers (tested offline) -----------------------------------------------------------


def form_fields(html: str) -> list[dict]:
    """Forms on a page with their inputs and the first options of each select."""
    soup = BeautifulSoup(html, "lxml")
    forms = []
    for f in soup.find_all("form"):
        fields = []
        for el in f.find_all(["input", "select"]):
            item = {"tag": el.name, "name": el.get("name"), "type": el.get("type")}
            if el.name == "select":
                opts = [o.get("value") or o.get_text(strip=True) for o in el.find_all("option")]
                item["options"] = opts[:6] + (["..."] + opts[-3:] if len(opts) > 9 else opts[6:])
                item["n_options"] = len(opts)
            else:
                item["value"] = el.get("value")
            fields.append(item)
        forms.append({"action": f.get("action"), "method": f.get("method"), "fields": fields})
    return forms


def find_links(html: str, base: str, pattern: str) -> list[dict]:
    """Links whose href or text matches the pattern, with the text of their table row."""
    soup = BeautifulSoup(html, "lxml")
    rx = re.compile(pattern, re.I)
    out = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        if rx.search(a["href"]) or rx.search(text):
            row = a.find_parent("tr")
            context = row.get_text(" | ", strip=True) if row else text
            out.append({"text": text, "href": urljoin(base, a["href"]), "row": context[:200]})
    return out


def years_in(text: str) -> list[int]:
    return sorted({int(y) for y in re.findall(r"\b(19[89]\d|20[0-4]\d)\b", text)})


def table_shapes(html: str) -> list[dict]:
    """Shape and header of every HTML table pandas can read."""
    try:
        tables = pd.read_html(io.StringIO(html))
    except ValueError:
        return []
    out = []
    for t in tables:
        cols = [" ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in t.columns]
        out.append(
            {"rows": len(t), "cols": cols[:8], "first": t.head(3).astype(str).values.tolist()}
        )
    return out


def pdf_markers(pages: list[str]) -> dict:
    """Where the IAGC model sections appear in a PDF's page texts."""
    found = {m: [i + 1 for i, p in enumerate(pages) if m in p] for m in IAGC_MARKERS}
    return {m: v[:5] for m, v in found.items()}


# --- fetching ---------------------------------------------------------------------------------


class Fetcher:
    def __init__(self, pause: float = 1.0):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.pause = pause

    def get(self, url: str, **kw) -> requests.Response | None:
        for attempt in range(3):
            try:
                r = self.s.get(url, timeout=60, **kw)
                time.sleep(self.pause)
                if r.encoding is None or r.encoding.lower() == "iso-8859-1":
                    r.encoding = r.apparent_encoding
                return r
            except requests.RequestException:
                time.sleep(2 ** (attempt + 1))
        return None


def meta(r: requests.Response | None) -> dict:
    if r is None:
        return {"status": None, "error": "no response"}
    return {
        "status": r.status_code,
        "type": r.headers.get("Content-Type", ""),
        "bytes": len(r.content),
        "url": r.url,
    }


def save(out: Path, name: str, r: requests.Response | None, limit: int = 40_000_000) -> None:
    if r is not None and r.content:
        (out / "raw").mkdir(parents=True, exist_ok=True)
        (out / "raw" / name).write_bytes(r.content[:limit])


def notice(title: str, msg: str, level: str = "notice") -> None:
    print(f"::{level} title={title}::{msg}", flush=True)


# --- Chile --------------------------------------------------------------------------------------


def cmf_url(rut: str, tab: int) -> str:
    return (
        f"{CMF}/entidad.php?mercado=V&rut={rut}&grupo=&tipoentidad=RVEMI&row=&vig=VI"
        f"&control=svs&pestania={tab}"
    )


def probe_cl_universe(f: Fetcher, out: Path) -> dict:
    url = f"{CMF}/consulta.php?mercado=V&Estado=VI&entidad=RVEMI"
    r = f.get(url)
    save(out, "cl_universe.html", r)
    res = {"source": "CMF listado emisores vigentes", **meta(r)}
    if r is not None and r.ok:
        res["tables"] = table_shapes(r.text)
        res["entity_links"] = len(find_links(r.text, url, r"entidad\.php"))
        res["forms"] = form_fields(r.text)
    n = res.get("entity_links", 0)
    notice(
        "cl_universe",
        f"HTTP {res['status']}, {n} entity links, tables {len(res.get('tables', []))}",
    )
    return res


def probe_cl_tabs(f: Fetcher, out: Path) -> dict:
    res = {"source": "CMF company tabs", "tabs": {}}
    for tab, label in CL_TABS.items():
        per_firm = {}
        for i, (rut, name) in enumerate(CL_FIRMS.items()):
            url = cmf_url(rut, tab)
            r = f.get(url)
            if i == 0:
                save(out, f"cl_tab{tab}_{rut}.html", r)
            item = meta(r)
            if r is not None and r.ok and "html" in item["type"]:
                item["tables"] = table_shapes(r.text)
                item["forms"] = form_fields(r.text)
                item["doc_links"] = find_links(r.text, url, DOC_LINKS)[:20]
                item["years"] = years_in(r.text)
            per_firm[name] = item
        res["tabs"][f"{tab} {label}"] = per_firm
        first = next(iter(per_firm.values()))
        shapes = [f"{t['rows']}x{len(t['cols'])}" for t in first.get("tables", [])][:4]
        yrs = first.get("years", [])
        span = f"{yrs[0]}-{yrs[-1]}" if yrs else "none"
        n_docs = len(first.get("doc_links", []))
        fields = sorted(
            {x["name"] for fm in first.get("forms", []) for x in fm["fields"] if x["name"]}
        )
        notice(
            f"cl_tab{tab}",
            f"{label}: HTTP {first.get('status')}, tables {shapes}, doc links {n_docs}, "
            f"years {span}, form fields {fields[:8]}",
        )
    return res


def probe_cl_pensions(f: Fetcher, out: Path) -> dict:
    """Superintendencia de Pensiones: where the fund holdings by issuer and the AFP-elected
    directors are published (searched from the portal pages, one level deep)."""
    seeds = [
        "https://www.spensiones.cl/portal/institucional/594/w3-channel.html",
        "https://www.spensiones.cl/apps/centroEstadisticas/paginaCuadrosCCEE.php?menu=sci&menuN1=estfinfp&menuN2=NOID",
        "https://www.spensiones.cl/portal/institucional/594/w3-article-11264.html",
    ]
    pattern = r"emisor|cartera|director|junta|\.xls|\.csv"
    res = {"source": "Superintendencia de Pensiones", "pages": {}}
    for i, url in enumerate(seeds):
        r = f.get(url)
        save(out, f"cl_sp_{i}.html", r)
        item = meta(r)
        if r is not None and r.ok:
            item["links"] = find_links(r.text, url, pattern)[:40]
        res["pages"][url] = item
        notice(
            "cl_pensions", f"{url[:70]}: HTTP {item['status']}, {len(item.get('links', []))} links"
        )
    return res


# --- Spain --------------------------------------------------------------------------------------


def probe_es_index(f: Fetcher, out: Path) -> dict:
    res = {"source": "CNMV informacion de gobierno corporativo", "firms": {}}
    for i, (nif, name) in enumerate(ES_FIRMS.items()):
        url = f"{CNMV}?nif={nif}"
        r = f.get(url)
        if i == 0:
            save(out, f"es_index_{nif}.html", r)
        item = meta(r)
        if r is not None and r.ok:
            docs = find_links(r.text, url, r"verdocumento")
            item["docs"] = docs[:40]
            item["n_docs"] = len(docs)
            item["years"] = years_in(" ".join(d["row"] for d in docs))
            item["forms"] = form_fields(r.text)
            item["tabs"] = find_links(r.text, url, r"informaciongobcorp|IARC|remuner")[:15]
        res["firms"][name] = item
        yrs = item.get("years", [])
        span = f"{yrs[0]}-{yrs[-1]}" if yrs else "none"
        notice("es_index", f"{name}: HTTP {item['status']}, {item.get('n_docs', 0)} docs, {span}")
    return res


def probe_es_iagc(f: Fetcher, out: Path, index: dict) -> dict:
    """Download the latest and the oldest IAGC of each firm and look for the model sections."""
    import pdfplumber

    res = {"source": "CNMV IAGC documents", "docs": []}
    for name, item in index.get("firms", {}).items():
        docs = item.get("docs", [])
        if not docs:
            continue
        for label, d in (("latest", docs[0]), ("oldest", docs[-1])):
            r = f.get(d["href"])
            entry = {"firm": name, "which": label, "row": d["row"], **meta(r)}
            if r is not None and r.ok and r.content[:4] == b"%PDF":
                safe = re.sub(r"\W+", "_", f"{name}_{label}")
                save(out, f"es_iagc_{safe}.pdf", r)
                try:
                    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
                        pages = [(p.extract_text() or "") for p in pdf.pages]
                        entry["pages"] = len(pages)
                        entry["text_chars"] = sum(len(p) for p in pages)
                        entry["markers"] = pdf_markers(pages)
                        target = entry["markers"].get("C.1.2") or []
                        if target:
                            tables = pdf.pages[target[0] - 1].extract_tables()
                            entry["c12_tables"] = [
                                {"rows": len(t), "first": t[:3]} for t in tables if t
                            ][:3]
                except Exception as e:  # a broken PDF is a finding, not a crash
                    entry["pdf_error"] = repr(e)
            elif r is not None:
                entry["head"] = r.content[:200].decode("latin-1", "replace")
            res["docs"].append(entry)
            mk = entry.get("markers", {})
            hits = [m for m, v in mk.items() if v]
            notice(
                "es_iagc",
                f"{name} {label} ({d['row'][:40]}): HTTP {entry['status']}, "
                f"{entry.get('pages', '?')} pages, {entry.get('text_chars', 0)} chars, "
                f"sections {hits}, C.1.2 tables {len(entry.get('c12_tables', []))}",
            )
    return res


# --- round 2: history, coverage and the sources round 1 did not reach ---------------------------


def first_table_rows(html: str, must: str) -> list[list[str]]:
    """Rows of the first table whose text contains `must` (empty if none)."""
    soup = BeautifulSoup(html, "lxml")
    for t in soup.find_all("table"):
        if must.lower() in t.get_text(" ").lower():
            return [
                [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                for tr in t.find_all("tr")
            ]
    return []


def cmf_post(f: Fetcher, rut: str, tab: int, data: dict) -> requests.Response | None:
    base = {
        "mercado": "V",
        "rut": rut,
        "grupo": "",
        "tipoentidad": "RVEMI",
        "row": "",
        "vig": "VI",
        "control": "svs",
        "pestania": str(tab),
    }
    for attempt in range(3):
        try:
            r = f.s.post(cmf_url(rut, tab), data={**base, **data}, timeout=60)
            time.sleep(f.pause)
            r.encoding = r.encoding or r.apparent_encoding
            return r
        except requests.RequestException:
            time.sleep(2 ** (attempt + 1))
    return None


def probe_cl_history(f: Fetcher, out: Path) -> dict:
    """How far back the 12 largest shareholders, the shareholder ranges and the board go."""
    rut = "90690000"
    res: dict = {"source": "CMF history (Copec)", "shareholders": {}, "ranges": {}, "board": {}}
    for year in (2025, 2020, 2015, 2010, 2005, 2000, 1995):
        r = cmf_post(f, rut, 5, {"mm": "12", "aa": str(year)})
        rows = first_table_rows(r.text, "% de propiedad") if r is not None else []
        res["shareholders"][year] = {
            "status": meta(r)["status"],
            "rows": len(rows),
            "top": rows[1:3],
        }
        r = cmf_post(f, rut, 21, {"mm": "12", "aa": str(year)})
        txt = BeautifulSoup(r.text, "lxml").get_text(" ") if r is not None else ""
        m = re.search(r"registros\s*:\s*([\d\.]+)", txt)
        res["ranges"][year] = {"status": meta(r)["status"], "n_holders": m.group(1) if m else None}
        notice(
            "cl_history",
            f"Copec 12/{year}: top-12 rows {len(rows) - 1 if rows else 0}, "
            f"holders {res['ranges'][year]['n_holders']}",
        )
    for start, end in (("01/01/2020", "31/12/2025"), ("01/01/2010", "31/12/2012")):
        r = cmf_post(f, rut, 46, {"txt_inicio": start, "txt_termino": end})
        save(out, f"cl_board_{start[-4:]}.html", r)
        rows = first_table_rows(r.text, "Cargo") if r is not None else []
        res["board"][f"{start}-{end}"] = {"status": meta(r)["status"], "rows": rows[:30]}
        notice("cl_history", f"Copec board {start}-{end}: {max(len(rows) - 1, 0)} rows, {rows[:2]}")
    return res


def probe_cl_coverage(f: Fetcher, out: Path) -> dict:
    """Share of the CMF issuers list with a 12-largest-shareholders table and a board."""
    url = f"{CMF}/consulta.php?mercado=V&Estado=VI&entidad=RVEMI"
    r = f.get(url)
    links = find_links(r.text, url, r"entidad\.php") if r is not None else []
    ruts = sorted({m.group(1) for x in links if (m := re.search(r"rut=(\d+)", x["href"]))})
    sample = ruts[:: max(1, len(ruts) // 25)][:25]
    res: dict = {"source": "CMF coverage", "n_issuers": len(ruts), "sample": {}}
    with_sh = with_board = 0
    for rut in sample:
        r5 = f.get(cmf_url(rut, 5))
        r46 = f.get(cmf_url(rut, 46))
        sh = first_table_rows(r5.text, "% de propiedad") if r5 is not None else []
        bd = first_table_rows(r46.text, "Cargo") if r46 is not None else []
        name = ""
        if r5 is not None:
            m = re.search(r"Raz.n Social:\s*</dt>\s*<dd>([^<]+)", r5.text)
            name = m.group(1).strip() if m else ""
        res["sample"][rut] = {"name": name, "top12": len(sh) - 1 if sh else 0, "board": len(bd) - 1}
        with_sh += bool(sh)
        with_board += len(bd) > 1
    res["with_top12"], res["with_board"] = with_sh, with_board
    notice(
        "cl_coverage",
        f"{len(ruts)} issuers listed; sample {len(sample)}: {with_sh} with top-12 table, "
        f"{with_board} with board",
    )
    return res


def probe_cl_pension_issuers(f: Fetcher, out: Path) -> dict:
    """Pension fund portfolios by issuer (Superintendencia de Pensiones, section 11)."""
    res: dict = {"source": "SP cartera por emisor", "periods": {}}
    for period in ("202512", "201512", "200512"):
        url = (
            "https://www.spensiones.cl/apps/loadCarteras/loadCarInv.php?menu=sci&menuN1=estfinfp"
            f"&menuN2=NOID&orden=11&periodo={period}&ext=.php"
        )
        r = f.get(url)
        save(out, f"cl_sp11_{period}.html", r)
        item = meta(r)
        if r is not None and r.ok:
            item["links"] = find_links(r.text, url, r"xls|html|zip|emisor")[:30]
            item["tables"] = table_shapes(r.text)[:3]
            xls = [x for x in item["links"] if "xls" in x["href"].lower()]
            if xls:
                rx = f.get(xls[0]["href"])
                save(out, f"cl_sp11_{period}.xls", rx)
                item["xls"] = meta(rx)
        res["periods"][period] = item
        notice(
            "cl_pension_issuers",
            f"{period}: HTTP {item['status']}, {len(item.get('links', []))} links, "
            f"xls {item.get('xls', {}).get('status')} {item.get('xls', {}).get('type')}",
        )
    return res


def probe_es_more(f: Fetcher, out: Path) -> dict:
    """Inditex (no documents in round 1), pagination, remuneration reports and the universe."""
    res: dict = {"source": "CNMV round 2", "firms": {}}
    for nif in ("A15075062", "A08055741"):
        url = f"{CNMV}?nif={nif}"
        r = f.get(url)
        save(out, f"es_index_{nif}.html", r)
        item = meta(r)
        if r is not None and r.ok:
            item["docs"] = len(find_links(r.text, url, r"verdocumento"))
            item["pager"] = find_links(r.text, url, r"page|pag=|__doPostBack")[:10]
            item["iarc"] = find_links(r.text, url, r"remuner|IARC")[:10]
            item["title"] = BeautifulSoup(r.text, "lxml").title.get_text(strip=True)[:120]
        res["firms"][nif] = item
        notice(
            "es_more", f"{nif}: HTTP {item['status']}, docs {item.get('docs')}, {item.get('title')}"
        )
    for nif in ("A86212420",):
        for tipo in ("IARC", "iarc"):
            url = f"{CNMV}?nif={nif}&tipo={tipo}"
            r = f.get(url)
            save(out, f"es_iarc_{nif}_{tipo}.html", r)
            docs = find_links(r.text, url, r"verdocumento") if r is not None else []
            res[f"iarc_{tipo}"] = {**meta(r), "docs": [d["row"] for d in docs][:15]}
            notice("es_more", f"IARC probe tipo={tipo}: {len(docs)} docs")
    r = f.get("https://www.cnmv.es/DocPortal/Publicaciones/Informes/CNMV_IAGC_2025_DEF.pdf")
    save(out, "es_cnmv_iagc_2025.pdf", r)
    res["cnmv_report"] = meta(r)
    notice("es_more", f"CNMV IAGC 2025 report: HTTP {res['cnmv_report']['status']}")
    return res


# --- round 3: the three loose ends --------------------------------------------------------------


def probe_cl_board_history(f: Fetcher, out: Path) -> dict:
    """Board history: the date-range form posted alone, and the PDF version of the register."""
    import pdfplumber

    rut, res = "90690000", {"source": "CMF board history (Copec)"}
    r = f.s.post(
        cmf_url(rut, 46), data={"txt_inicio": "01/01/2010", "txt_termino": "31/12/2012"}, timeout=60
    )
    rows = first_table_rows(r.text, "Cargo")
    res["post_dates_only"] = {**meta(r), "rows": rows[:25]}
    notice("cl_board_history", f"POST dates only: {len(rows) - 1} rows, {rows[1:3]}")
    for start, end in (("01/01/2010", "31/12/2012"), ("01/01/2000", "31/12/2025")):
        url = (
            f"{CMF}/inc/directores_pdf.php?rut={rut}&razon=&comite_aux=N&info=1"
            f"&txt_inicio={start}&txt_termino={end}"
        )
        r = f.get(url)
        item = meta(r)
        if r is not None and r.content[:4] == b"%PDF":
            save(out, f"cl_board_{start[-4:]}_{end[-4:]}.pdf", r)
            with pdfplumber.open(io.BytesIO(r.content)) as pdf:
                text = "\n".join((p.extract_text() or "") for p in pdf.pages)
                item["pages"] = len(pdf.pages)
            item["text"] = text[:1500]
        elif r is not None:
            item["head"] = r.text[:300]
        res[f"pdf_{start[-4:]}_{end[-4:]}"] = item
        lines = [x for x in item.get("text", "").splitlines() if re.search(r"\d{1,2}\.\d{3}", x)]
        notice("cl_board_history", f"PDF {start}-{end}: {item['type']}, {len(lines)} RUT lines")
    return res


def probe_cl_pension_links(f: Fetcher, out: Path) -> dict:
    """Every Excel link on the portfolio page for 2025-12, with the title row of each file."""
    url = (
        "https://www.spensiones.cl/apps/loadCarteras/loadCarInv.php?menu=sci&menuN1=estfinfp"
        "&menuN2=NOID&orden=11&periodo=202512&ext=.php"
    )
    r = f.get(url)
    soup = BeautifulSoup(r.text, "lxml")
    res: dict = {"source": "SP portfolio files 2025-12", "files": []}
    for i, a in enumerate(soup.find_all("a", href=re.compile(r"xls", re.I))[:20]):
        row = a.find_parent("tr")
        heading = a.find_previous(["h1", "h2", "h3", "h4", "b", "strong"])
        rx = f.get(urljoin(url, a["href"]))
        title = ""
        if rx is not None and rx.ok:
            save(out, f"cl_sp_file_{i:02d}.xls", rx)
            try:
                t = pd.read_html(io.BytesIO(rx.content))[0]
                title = (
                    " | ".join(map(str, t.columns[:3]))
                    + f" ; {t.shape}; "
                    + str(t.iloc[:5, 0].tolist())
                )
            except Exception as e:
                title = repr(e)[:120]
        res["files"].append(
            {
                "i": i,
                "row": row.get_text(" | ", strip=True)[:150] if row else "",
                "heading": heading.get_text(" ", strip=True)[:150] if heading else "",
                "title": title[:400],
            }
        )
        notice("cl_pension_links", f"{i}: {res['files'][-1]['heading'][:60]} :: {title[:150]}")
    return res


def probe_es_retry(f: Fetcher, out: Path) -> dict:
    """CNMV slowly, with ordinary browser headers, to tell a block from a timeout."""
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
            "Accept-Language": "es-ES,es;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
        }
    )
    res: dict = {"source": "CNMV retry"}
    for nif in ("A86212420", "A15075062"):
        url = f"{CNMV}?nif={nif}"
        try:
            r = s.get(url, timeout=90)
            docs = find_links(r.text, url, r"verdocumento")
            res[nif] = {**meta(r), "docs": [d["row"][:80] for d in docs][:20]}
            if nif == "A15075062":
                save(out, f"es_index_{nif}.html", r)
            notice("es_retry", f"{nif}: HTTP {r.status_code}, {len(docs)} docs")
        except requests.RequestException as e:
            res[nif] = {"error": repr(e)[:300]}
            notice("es_retry", f"{nif}: {e!r}"[:300], level="warning")
        time.sleep(8)
    return res


# --- round 4 ------------------------------------------------------------------------------------


def probe_cl_board_pdf(f: Fetcher, out: Path) -> dict:
    """Board register as PDF (correct path), and the history form posted after a first visit."""
    import pdfplumber

    rut, res = "90690000", {"source": "CMF board PDF and form with cookies"}
    for start, end in (("", ""), ("01/01/2010", "31/12/2012")):
        url = (
            "https://www.cmfchile.cl/institucional/inc/directores_pdf.php"
            f"?rut={rut}&razon=&comite_aux=N&info=1&txt_inicio={start}&txt_termino={end}"
        )
        r = f.get(url)
        item = meta(r)
        if r is not None and r.content[:4] == b"%PDF":
            save(out, f"cl_board_pdf_{start[-4:] or 'now'}.pdf", r)
            with pdfplumber.open(io.BytesIO(r.content)) as pdf:
                item["pages"] = len(pdf.pages)
                item["text"] = "\n".join((p.extract_text() or "") for p in pdf.pages)[:1500]
        elif r is not None:
            item["head"] = r.text[:200]
        res[f"pdf_{start[-4:] or 'now'}"] = item
        notice("cl_board_pdf", f"PDF {start or 'current'}: {item['type']}, {item.get('pages')} pp")
    page = cmf_url(rut, 46)
    f.get(page)  # first visit sets the session cookie the form may expect
    r = f.s.post(
        page,
        data={"txt_inicio": "01/01/2010", "txt_termino": "31/12/2012"},
        headers={"Referer": page},
        timeout=60,
    )
    rows = first_table_rows(r.text, "Cargo")
    tables = [first_table_rows(r.text, h) for h in ("Fecha Cese", "Término", "Desde")]
    res["form_with_cookie"] = {**meta(r), "rows": rows[:12], "other": [t[:5] for t in tables]}
    save(out, "cl_board_form_2010.html", r)
    notice("cl_board_pdf", f"form after visit: {len(rows) - 1} rows; first {rows[1:2]}")
    return res


def probe_cl_pension_zip(f: Fetcher, out: Path) -> dict:
    """The disaggregated portfolio ZIP: its files and the header of the first one."""
    import zipfile

    url = (
        "https://www.spensiones.cl/apps/loadCarteras/loadCarInv.php?menu=sci&menuN1=estfinfp"
        "&menuN2=NOID&orden=11&periodo=202512&ext=.php"
    )
    r = f.get(url)
    zips = find_links(r.text, url, r"\.zip") if r is not None else []
    if not zips:  # the 2005 page linked cinv200512.zip; try the same pattern
        zips = [{"href": "https://www.spensiones.cl/apps/loadCarteras/cinv202512.zip"}]
    res: dict = {"source": "SP disaggregated portfolio", "zip_links": [z["href"] for z in zips]}
    if zips:
        rz = f.get(zips[0]["href"])
        res["zip"] = meta(rz)
        if rz is not None and rz.ok:
            try:
                zf = zipfile.ZipFile(io.BytesIO(rz.content))
                names = zf.namelist()
                res["members"] = names[:30]
                head = zf.read(names[0])[:3000].decode("latin-1", "replace")
                res["first_head"] = head
                (out / "raw").mkdir(parents=True, exist_ok=True)
                (out / "raw" / "cl_sp_zip_head.txt").write_text(head)
            except zipfile.BadZipFile as e:
                res["zip_error"] = repr(e)
    notice(
        "cl_pension_zip",
        f"{len(zips)} zip links; zip {res.get('zip', {}).get('bytes')} bytes; "
        f"members {res.get('members', [])[:5]}",
    )
    return res


def probe_es_universe(f: Fetcher, out: Path) -> dict:
    """Candidate lists of Spanish listed companies with their NIF."""
    res: dict = {"source": "CNMV universe"}
    f = Fetcher(pause=3)
    f.s.headers.update({"User-Agent": BROWSER_UA, "Accept-Language": "es-ES,es;q=0.9"})
    urls = {
        "iagc_report_2025": (
            "https://www.cnmv.es/DocPortal/Publicaciones/Informes/CNMV_IAGC_2025_DEF.pdf"
        ),
        "entidades": "https://www.cnmv.es/portal/consultas/busqueda.aspx?id=29",
        "cotizadas": "https://www.cnmv.es/portal/Consultas/EE/ListadoEntidadesCotizadas.aspx",
    }
    for key, url in urls.items():
        r = f.get(url)
        item = meta(r)
        if r is not None and r.ok and r.content[:4] == b"%PDF":
            import pdfplumber

            save(out, f"es_{key}.pdf", r)
            with pdfplumber.open(io.BytesIO(r.content)) as pdf:
                item["pages"] = len(pdf.pages)
                tail = "\n".join((p.extract_text() or "") for p in pdf.pages[-12:])
            item["sa_names_in_annex"] = len(re.findall(r"\bS\.A\.", tail))
            item["tail"] = tail[:1200]
        elif r is not None and r.ok:
            item["nif_links"] = len(find_links(r.text, url, r"nif="))
            item["title"] = (BeautifulSoup(r.text, "lxml").title or "").__str__()[:120]
        res[key] = item
        notice("es_universe", f"{key}: HTTP {item['status']}, {item.get('pages')} pp, {item}"[:250])
        time.sleep(4)
    return res


# --- runner -------------------------------------------------------------------------------------

LATEST = ["cl_pension_zip", "es_universe"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="probes")
    ap.add_argument("--only", nargs="*", help="probe names; default: the latest round")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    f = Fetcher()
    wanted = set(args.only or LATEST)
    results: dict[str, dict] = {}
    steps = [
        ("cl_universe", lambda: probe_cl_universe(f, out)),
        ("cl_tabs", lambda: probe_cl_tabs(f, out)),
        ("cl_pensions", lambda: probe_cl_pensions(f, out)),
        ("es_index", lambda: probe_es_index(f, out)),
        ("es_iagc", lambda: probe_es_iagc(f, out, results.get("es_index", {}))),
        ("cl_history", lambda: probe_cl_history(f, out)),
        ("cl_coverage", lambda: probe_cl_coverage(f, out)),
        ("cl_pension_issuers", lambda: probe_cl_pension_issuers(f, out)),
        ("es_more", lambda: probe_es_more(f, out)),
        ("cl_board_history", lambda: probe_cl_board_history(f, out)),
        ("cl_pension_links", lambda: probe_cl_pension_links(f, out)),
        ("es_retry", lambda: probe_es_retry(f, out)),
        ("cl_board_pdf", lambda: probe_cl_board_pdf(f, out)),
        ("cl_pension_zip", lambda: probe_cl_pension_zip(f, out)),
        ("es_universe", lambda: probe_es_universe(f, out)),
    ]
    for name, run in steps:
        if name not in wanted:
            continue
        try:
            results[name] = run()
        except Exception as e:  # one failed source must not hide the others
            results[name] = {"error": repr(e), "trace": traceback.format_exc()}
            notice(name, f"failed: {e!r}", level="warning")
        (out / f"{name}.json").write_text(json.dumps(results[name], indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
