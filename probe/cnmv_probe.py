"""One-off probe: why the CNMV governance page lists no reports for some issuers."""

import re

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0 Safari/537.36"
)
URLS = {
    "gobcorp": "https://www.cnmv.es/portal/consultas/ee/informaciongobcorp?nif={nif}",
    "aspx": "https://www.cnmv.es/Portal/Consultas/EE/InformacionGobCorp.aspx?nif={nif}",
    "entidad": "https://www.cnmv.es/portal/consultas/datosentidad.aspx?nif={nif}",
}


def note(title, msg, level="notice"):
    print(f"::{level} title={title}::{msg[:950]}", flush=True)


for nif, name in (("A48010615", "Iberdrola"), ("A28023430", "Endesa"), ("A78374725", "Repsol")):
    for kind, url in URLS.items():
        s = requests.Session()
        s.headers["User-Agent"] = UA
        try:
            r = s.get(url.format(nif=nif), timeout=60)
        except requests.RequestException as e:
            note(f"{name} {kind}", f"error {type(e).__name__}: {e}", "warning")
            continue
        h = r.text
        title = re.search(r"<title>(.*?)</title>", h, re.S)
        docs = len(re.findall(r"verdocumento", h))
        grids = sorted(set(re.findall(r"wGrid\w+", h)))
        years = re.findall(r">\s*(20\d\d)\s*<", h)[:12]
        links = [
            x
            for x in dict.fromkeys(re.findall(r'href="([^"]+)"', h))
            if re.search(r"gobcorp|remuner|nif=|verdocumento", x, re.I) and "lang=" not in x
        ]
        note(
            f"{name} {kind}",
            f"HTTP {r.status_code} {r.url} | {len(h)} bytes | title "
            f"{(title.group(1).strip() if title else '')[:90]} | docs {docs} | grids {grids} | "
            f"years {years} | links {links[:6]}",
        )
