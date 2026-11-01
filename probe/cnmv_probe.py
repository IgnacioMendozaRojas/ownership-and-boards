"""One-off probe: the identifiers the CNMV uses for five issuers its NIF route does not find."""

import re

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0 Safari/537.36"
)
S = requests.Session()
S.headers["User-Agent"] = UA
ISIN = {
    "Iberdrola": "ES0144580Y14",
    "Endesa": "ES0130670112",
    "ACS": "ES0167050915",
    "Enagás": "ES0130960018",
    "Redeia": "ES0173093024",
}
NAMES = r"IBERDROLA|ENDESA|ACS,? ACTIVIDADES|ACTIVIDADES DE CONSTRUC|ENAG|REDEIA|RED EL[EÉ]CTRICA"


def note(title, msg, level="notice"):
    print(f"::{level} title={title}::{msg[:950]}", flush=True)


def get(url):
    try:
        return S.get(url, timeout=90)
    except requests.RequestException as e:
        note("error", f"{url}: {type(e).__name__}", "warning")
        return None


# 1. the issuer list: links next to the five names
for tipo in (0, 1):
    r = get(f"https://www.cnmv.es/portal/consultas/listadoentidad.aspx?id=1&tipoent={tipo}")
    if r is None:
        continue
    hits = re.findall(
        r'<a[^>]+href="([^"]+)"[^>]*>\s*([^<]*(?:' + NAMES + r")[^<]*)</a>", r.text, re.I
    )
    note(
        f"list tipoent={tipo}",
        f"{len(r.text)} bytes; " + " | ".join(f"{t.strip()} -> {h}" for h, t in hits[:12]),
    )

# 2. the governance page by ISIN
for name, isin in ISIN.items():
    for param in ("isin", "nif"):
        r = get(f"https://www.cnmv.es/portal/consultas/ee/informaciongobcorp?{param}={isin}")
        if r is None:
            continue
        title = re.search(r"<title>(.*?)</title>", r.text, re.S)
        docs = len(re.findall(r"verdocumento", r.text))
        note(
            f"{name} {param}", f"{(title.group(1).strip() if title else '')[60:140]} | docs {docs}"
        )
