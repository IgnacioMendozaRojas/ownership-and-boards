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


def save(out: Path, name: str, r: requests.Response | None, limit: int = 8_000_000) -> None:
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


# --- runner -------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="probes")
    ap.add_argument("--only", nargs="*", help="cl_universe cl_tabs cl_pensions es_index es_iagc")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    f = Fetcher()
    wanted = set(args.only or ["cl_universe", "cl_tabs", "cl_pensions", "es_index", "es_iagc"])
    results: dict[str, dict] = {}
    steps = [
        ("cl_universe", lambda: probe_cl_universe(f, out)),
        ("cl_tabs", lambda: probe_cl_tabs(f, out)),
        ("cl_pensions", lambda: probe_cl_pensions(f, out)),
        ("es_index", lambda: probe_es_index(f, out)),
        ("es_iagc", lambda: probe_es_iagc(f, out, results.get("es_index", {}))),
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
