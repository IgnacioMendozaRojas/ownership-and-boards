"""CNMV annual corporate governance reports (IAGC): index by NIF, download, and cache the pages
that hold the ownership and board sections as text plus word positions.

The PDFs themselves are not kept: only the pages the parser needs, as gzipped JSON.
"""

from __future__ import annotations

import gzip
import io
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

from .web import Web

INDEX = "https://www.cnmv.es/portal/consultas/ee/informaciongobcorp"
# Pages worth keeping: the model's ownership (A) and board (C.1) sections, and the board's and
# senior management's pay (C.1.13-C.1.14 since 2018; C.1.15-C.1.16 before)
KEEP = re.compile(
    r"A\.2\b|A\.3\b|C\.1\.2\b|C\.1\.3\b|consejeros? (externos )?dominicales|"
    r"derechos de voto representados|N[uú]mero total de consejeros|"
    r"Remuneraci[oó]n[^\n]{0,90}\((en )?miles de euros|remuneraci[oó]n global del consejo",
    re.I,
)
# Version of what a cached report holds; older caches are downloaded again
CACHE_VERSION = 2
MAX_PAGES = 60


def parse_index(html: str, base: str = INDEX) -> list[dict]:
    """One entry per report: exercise year, register date and document URL (newest first)."""
    from urllib.parse import urljoin

    soup = BeautifulSoup(html, "lxml")
    out = []
    for a in soup.find_all("a", href=re.compile(r"verdocumento")):
        tr = a.find_parent("tr")
        cells = [c.get_text(" ", strip=True) for c in tr.find_all("td")] if tr else []
        years = [c for c in cells if re.fullmatch(r"(19|20)\d\d", c)]
        dates = [c for c in cells if re.fullmatch(r"\d\d/\d\d/\d{4}", c)]
        if not years:
            continue
        out.append(
            {
                "company": cells[0] if cells else "",
                "year": int(years[0]),
                "registered": dates[0] if dates else "",
                "url": urljoin(base, a["href"]),
            }
        )
    return out


def plain(text: str) -> str:
    import unicodedata

    t = unicodedata.normalize("NFKD", text.upper())
    return "".join(c for c in t if c.isalnum() or c == " ")


def belongs(entries: list[dict], names: list[str]) -> bool:
    """True when every report on the page is the issuer's own. An unknown identifier returns a
    generic page that lists other entities' reports, which must not be cached as the issuer's."""
    keys = [plain(n).split()[0] for n in names if n]
    return bool(entries) and all(any(k in plain(e["company"]) for k in keys) for e in entries)


def index(web: Web, nif: str, names: list[str]) -> list[dict]:
    """The issuer's reports. The CNMV records some issuers with a hyphen in the NIF
    ('A-48010615'), so that form is tried when the plain one does not return the issuer."""
    for key in (nif, f"{nif[0]}-{nif[1:]}"):
        entries = parse_index(web.get(f"{INDEX}?nif={key}").text)
        if belongs(entries, names):
            return entries
    return []


def pdf_pages(content: bytes) -> list[dict]:
    """Text and word boxes of the pages that matter, in page order."""
    import pdfplumber

    keep = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if not KEEP.search(text):
                continue
            words = [
                [round(w["x0"], 1), round(w["x1"], 1), round(w["top"], 1), w["text"]]
                for w in page.extract_words(keep_blank_chars=False)
            ]
            keep.append({"page": i + 1, "text": text, "words": words, "width": page.width})
            if len(keep) >= MAX_PAGES:
                break
    return keep


def is_current(path: Path) -> bool:
    """A cached report is reused only if it was saved with the current page selection."""
    return path.exists() and load_cache(path).get("v", 1) >= CACHE_VERSION


def cache_path(root: Path, nif: str, year: int) -> Path:
    return root / f"{nif}_{year}.json.gz"


def save_cache(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False)


def load_cache(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def fetch_report(web: Web, entry: dict) -> dict:
    r = web.get(entry["url"])
    if r.content[:4] != b"%PDF":
        return {
            **entry,
            "error": f"not a PDF ({r.headers.get('Content-Type')})",
            "pages": [],
            "v": 0,
        }
    return {**entry, "pages": pdf_pages(r.content), "v": CACHE_VERSION}
