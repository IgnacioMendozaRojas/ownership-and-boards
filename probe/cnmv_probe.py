"""One-off probe: why the CNMV governance page lists no reports for some issuers."""

import re

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0 Safari/537.36"
)
BASE = "https://www.cnmv.es/portal/consultas/ee/informaciongobcorp"


def note(title, msg, level="notice"):
    print(f"::{level} title={title}::{msg[:950]}", flush=True)


for nif, name in (("A78374725", "Repsol"), ("A48010615", "Iberdrola"), ("A28023430", "Endesa")):
    s = requests.Session()
    s.headers["User-Agent"] = UA
    r = s.get(f"{BASE}?nif={nif}", timeout=90)
    h = r.text
    hrefs = re.findall(r'href="([^"]+)"', h)
    keep = [x for x in hrefs if re.search(r"gobcorp|verdocumento|IAGC|IARC|tipo|nif=", x, re.I)]
    opts = re.findall(r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)', h)
    tabs = re.findall(r"<a[^>]*>\s*(Informe[^<]{0,80})</a>", h)
    note(f"{name} page", f"final {r.url} | {len(h)} bytes | tabs {tabs[:8]} | options {opts[:10]}")
    note(f"{name} links", " | ".join(dict.fromkeys(keep))[:900])
    forms = re.findall(r"<form[^>]*>", h)
    inputs = re.findall(r'<input[^>]+name="([^"]+)"[^>]*value="([^"]*)"', h)
    note(f"{name} form", f"{forms[:3]} | {inputs[:12]}")
