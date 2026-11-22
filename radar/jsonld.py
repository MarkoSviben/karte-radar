"""Generički parser schema.org JSON-LD Event objekata (Eventim i mnoge druge stranice)."""
from __future__ import annotations

import json
import re

_SCRIPT_RE = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)

EVENT_TYPES = ("Event", "MusicEvent", "SportsEvent", "TheaterEvent", "ComedyEvent",
               "Festival", "DanceEvent", "SocialEvent", "ExhibitionEvent", "EducationEvent",
               "ChildrensEvent", "LiteraryEvent", "ScreeningEvent")

COUNTRY_NAMES = {
    "croatia": "HR", "hrvatska": "HR", "serbia": "RS", "srbija": "RS",
    "bosnia and herzegovina": "BA", "bosna i hercegovina": "BA", "bih": "BA",
    "slovenia": "SI", "slovenija": "SI", "montenegro": "ME", "crna gora": "ME",
    "north macedonia": "MK", "austria": "AT", "germany": "DE", "hungary": "HU",
}


def _walk(obj):
    if isinstance(obj, list):
        for x in obj:
            yield from _walk(x)
    elif isinstance(obj, dict):
        yield obj
        for k in ("@graph", "itemListElement", "subEvent", "item"):
            if k in obj:
                yield from _walk(obj[k])


def _is_event(o: dict) -> bool:
    t = o.get("@type")
    types = t if isinstance(t, list) else [t]
    return any(isinstance(x, str) and x in EVENT_TYPES for x in types)


def _country(addr) -> str:
    if not isinstance(addr, dict):
        return ""
    c = addr.get("addressCountry")
    if isinstance(c, dict):
        c = c.get("name") or c.get("identifier") or ""
    c = (c or "").strip()
    if len(c) == 2:
        return c.upper()
    return COUNTRY_NAMES.get(c.lower(), c[:2].upper() if c else "")


def _offers(o) -> list[dict]:
    out = []
    for x in _walk(o.get("offers") or []):
        if isinstance(x, dict) and ("price" in x or "lowPrice" in x or "availability" in x or "validFrom" in x):
            out.append(x)
    return out


def parse_events(html: str) -> list[dict]:
    """Vrati listu normaliziranih dictova: name, start, venue, city, country, sale_start, availability, price."""
    res = []
    for raw in _SCRIPT_RE.findall(html or ""):
        try:
            data = json.loads(raw.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        for o in _walk(data):
            if not _is_event(o):
                continue
            loc = o.get("location") or {}
            if isinstance(loc, list):
                loc = loc[0] if loc else {}
            addr = loc.get("address") if isinstance(loc, dict) else {}
            offers = _offers(o)
            # Eventim ponekad stavi 1970-01-01 kao "nepoznato"
            valid = sorted(x["validFrom"] for x in offers
                           if isinstance(x.get("validFrom"), str) and x["validFrom"][:4] >= "2000")
            avail = sorted({str(x.get("availability", "")).rsplit("/", 1)[-1] for x in offers if x.get("availability")})
            prices = []
            currency = ""
            for x in offers:
                for k in ("lowPrice", "price"):
                    try:
                        prices.append(float(str(x[k]).replace(",", ".")))
                        currency = currency or x.get("priceCurrency", "")
                    except (KeyError, ValueError, TypeError):
                        pass
            res.append({
                "url": o.get("url") or "",
                "name": o.get("name") or "",
                "start": o.get("startDate") or "",
                "end": o.get("endDate") or "",
                "venue": loc.get("name", "") if isinstance(loc, dict) else "",
                "city": (addr or {}).get("addressLocality", "") if isinstance(addr, dict) else "",
                "country": _country(addr),
                "sale_start": valid[0] if valid else "",
                "availability": ",".join(a for a in avail if a),
                "price": f"od {min(prices):g} {currency}".strip() if prices else "",
                "status": str(o.get("eventStatus", "")).rsplit("/", 1)[-1],
            })
    return res
