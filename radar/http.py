from __future__ import annotations

import gzip

import httpx

# Iskren User-Agent: neke stranice (npr. Eventim) blokiraju lazne "Chrome" UA, a ovaj puste.
USER_AGENT = "KarteRadar/1.0 (personal event alerts; low-frequency)"


def make_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "hr,sr;q=0.9,sl;q=0.8,en;q=0.7"},
        timeout=httpx.Timeout(20.0, connect=10.0),
        follow_redirects=True,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )


def get_text(client: httpx.Client, url: str) -> str:
    r = client.get(url)
    r.raise_for_status()
    body = r.content
    if url.endswith(".gz") or body[:2] == b"\x1f\x8b":
        try:
            body = gzip.decompress(body)
        except OSError:
            pass
        return body.decode("utf-8", errors="replace")
    return r.text
