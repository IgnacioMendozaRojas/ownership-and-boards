"""Polite HTTP access to the CMF and CNMV websites, with a per-run request budget."""

from __future__ import annotations

import time

import requests

# The CNMV drops requests from non-browser user agents, so both sites get an ordinary one.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0 Safari/537.36"
)


class BudgetSpent(RuntimeError):
    """This run's request budget is used up: stop and let the next run resume."""


class Web:
    def __init__(self, pause: float = 1.0, budget: int = 3000, retries: int = 3):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": BROWSER_UA, "Accept-Language": "es-ES,es;q=0.9"})
        self.pause, self.budget, self.retries, self.used = pause, budget, retries, 0

    def request(self, method: str, url: str, **kw) -> requests.Response:
        for attempt in range(1, self.retries + 1):
            if self.used >= self.budget:
                raise BudgetSpent(f"request budget of {self.budget} spent")
            self.used += 1
            try:
                r = self.s.request(method, url, timeout=90, **kw)
                time.sleep(self.pause)
                if r.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {r.status_code}")
                if r.encoding is None or r.encoding.lower() == "iso-8859-1":
                    r.encoding = r.apparent_encoding
                return r
            except requests.RequestException:
                if attempt == self.retries:
                    raise
                time.sleep(5 * attempt)
        raise RuntimeError("unreachable")

    def get(self, url: str, **kw) -> requests.Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw) -> requests.Response:
        return self.request("POST", url, **kw)
