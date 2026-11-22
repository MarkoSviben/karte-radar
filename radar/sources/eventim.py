"""Eventim (eventim.hr, eventim.si): javni sitemapi + javne stranice dvorana.

- events*.xml.gz  -> svi eventi; novi URL = novi event
- artist*.xml.gz  -> stranice izvodjaca; nova stranica cesto znaci da event stize
- venue*.xml.gz   -> dvorane; iz URL-a eventa se izvlace naslov, dvorana i grad
- stranice dvorana (/city/.../venue/...?pnum=N) imaju schema.org JSON-LD za svaki event:
  datum, POCETAK PRODAJE (offers.validFrom), dostupnost (InStock/SoldOut...), cijenu.

Stranice pojedinog eventa Eventim stiti Akamai bot-provjerom; njih NE diramo.
Stranice dvorana su javne (robots.txt ih dopusta) i dohvacaju se polako, jedna po jedna,
a na prvu bot-provjeru se staje do iduceg runa.
"""
from __future__ import annotations

import html as _html
import re
import time

from radar.http import get_text
from radar.jsonld import parse_events
from radar.models import Event
from radar.sources.base import Context, fetch_sitemap, sitemap_index, slug_title
from radar.textnorm import norm, tokens

_EVENT_RE = re.compile(r"/event/([a-z0-9-]+?)-(\d{6,})/?$")
_ARTIST_RE = re.compile(r"/artist/([a-z0-9-]+)/?$")
_VENUE_RE = re.compile(r"/city/([a-z0-9-]+?)-\d+/venue/([a-z0-9-]+?)-\d+/?$")

# gradovi izvan regije koje Eventim HR/SI takodjer prodaje -> event se odbacuje
FOREIGN_CITIES = {"bec", "wien", "graz", "klagenfurt", "linz", "salzburg", "innsbruck", "villach", "telfs",
                  "budimpesta", "budapest", "munchen", "trst", "trieste", "udine", "milano", "padova",
                  "verona", "venecija", "dornbirn", "st-polten", "wiener-neustadt", "wels", "leoben"}

# drzava po gradu iz URL-a (Eventim HR prodaje i SLO evente i obrnuto)
CITY_COUNTRY = {
    **{c: "SI" for c in ("ljubljana", "maribor", "koper", "celje", "kranj", "ptuj", "velenje", "loce", "domzale",
                         "bled", "portoroz", "piran", "izola", "nova-gorica", "novo-mesto", "murska-sobota",
                         "kartuzija", "bonifika", "golovec", "tabor", "lent", "stozice", "krsko", "brezice")},
    **{c: "HR" for c in ("zagreb", "split", "rijeka", "osijek", "pula", "zadar", "varazdin", "sibenik", "dubrovnik",
                         "karlovac", "slavonski-brod", "vukovar", "cakovec", "koprivnica", "porec", "rovinj",
                         "opatija", "makarska", "vinkovci", "sisak", "bjelovar")},
    **{c: "RS" for c in ("beograd", "novi-sad", "nis", "kragujevac", "subotica")},
    **{c: "BA" for c in ("sarajevo", "mostar", "banja-luka", "tuzla", "zenica", "bihac")},
    **{c: "XX" for c in FOREIGN_CITIES | {"salzburgarena", "wiener", "stadthalle", "gasometer", "worthersee"}},
}


def guess_country(slug: str, city_slug: str, default: str) -> str:
    if city_slug in CITY_COUNTRY:
        return CITY_COUNTRY[city_slug]
    toks = slug.split("-")
    pairs = [f"{a}-{b}" for a, b in zip(toks, toks[1:])]
    for t in reversed(toks + pairs):  # grad je obicno na kraju sluga
        if t in CITY_COUNTRY:
            return CITY_COUNTRY[t]
    return default


REQUEST_DELAY = 1.0  # s izmedju zahtjeva prema stranicama dvorana
MAX_PAGES_PER_VENUE = 5


class Blocked(Exception):
    pass


def _venue_map(lists) -> dict[str, tuple[str, str, str]]:
    """venue_slug -> (city_slug, naziv, url stranice dvorane)"""
    vm = {}
    for lst in lists:
        for loc, _ in lst:
            m = _VENUE_RE.search(loc)
            if m:
                vm[m.group(2)] = (m.group(1), slug_title(m.group(2)), loc)
    return vm


def best_venue(slug: str, venues: dict) -> str:
    best = ""
    for vslug in venues:
        if len(vslug) > len(best) and slug.endswith("-" + vslug):
            best = vslug
    return best


def split_slug(slug: str, venues: dict) -> tuple[str, str, str, str]:
    """'psihomodo-pop-arena-zagreb-arena-zagreb' -> ('Psihomodo pop arena zagreb', 'Arena zagreb', 'Zagreb', 'zagreb')"""
    best = best_venue(slug, venues)
    if not best:
        return slug_title(slug), "", "", ""
    city_slug, venue = venues[best][0], venues[best][1]
    return slug_title(slug[: -(len(best) + 1)]), venue, slug_title(city_slug), city_slug


def is_bot_check(html: str) -> bool:
    return len(html) < 20000 and ("akamai" in html.lower() or "sec-if-cpt" in html)


def uid_from_url(url: str) -> str:
    m = _EVENT_RE.search(url.split("?")[0])
    return m.group(2) if m else ""


def apply_detail(e: Event, j: dict) -> None:
    e.title = j["name"] or e.title
    e.venue = j["venue"] or e.venue
    e.city = j["city"] or e.city
    e.country = j["country"] or e.country
    e.start = j["start"] or e.start
    e.sale_start = j["sale_start"] or e.sale_start
    e.availability = j["availability"] or e.availability
    e.price = j["price"] or e.price
    e.extra.pop("needs_enrich", None)


def apply_jsonld(e: Event, html: str) -> bool:
    evs = parse_events(html)
    if not evs:
        return False
    apply_detail(e, evs[0])
    return True


_CARD_RE = re.compile(r'<article class="listing-item event-listing-item.*?</article>', re.S)


def parse_cards(html: str) -> list[dict]:
    """HTML kartice evenata na stranici dvorane (Eventim SI nema JSON-LD) -> isti format kao parse_events."""
    out = []
    for a in _CARD_RE.findall(html):
        href = re.search(r"href=['\"]?(/event/[a-z0-9-]+-\d{6,}/)", a) or re.search(r"location\.href='(/event/[^']+)'", a)
        if not href:
            continue
        name = re.search(r'data-teaser-name="([^"]*)"', a) or re.search(r"<h2[^>]*>([^<]+)</h2>", a)
        start = re.search(r'<time datetime="([^"]+)"', a)
        price = re.search(r"od\s*<span[^>]*>\s*([^<]+?)\*?\s*</span>", a)
        ind = re.search(r'data-availability-indicator="(-?\d+)"', a)
        text = norm(_html.unescape(re.sub(r"<[^>]+>", " ", a)))
        if re.search(r"\b(rasprodano|razprodano|sold out)\b", text):
            avail = "SoldOut"
        elif re.search(r"\b(ni na voljo|nije dostupno|nema karata|not available)\b", text):
            avail = "OutOfStock"
        elif ind and ind.group(1) == "1":
            avail = "LimitedAvailability"
        else:
            avail = "InStock"
        nm = _html.unescape(_html.unescape(name.group(1))) if name else ""
        out.append({"url": href.group(1), "name": nm.strip(),
                    "start": start.group(1) if start else "", "venue": "", "city": "", "country": "",
                    "sale_start": "", "availability": avail,
                    "price": f"od {price.group(1).strip()}" if price else "", "status": ""})
    return out


def scan_venue(ctx: Context, venue_url: str, want: set[str] | None = None,
               max_pages: int = MAX_PAGES_PER_VENUE) -> dict[str, dict]:
    """Procitaj stranice dvorane -> {uid: detalji}. `want`: stani cim su svi trazeni pronadjeni."""
    found: dict[str, dict] = {}
    for page in range(1, max_pages + 1):
        url = venue_url if page == 1 else f"{venue_url}?pnum={page}"
        html = get_text(ctx.client, url)
        time.sleep(REQUEST_DELAY)
        if is_bot_check(html):
            raise Blocked(url)
        page_evs = {uid_from_url(j["url"]): j for j in parse_cards(html) if uid_from_url(j["url"])}
        # JSON-LD (HR) ima vise detalja (pocetak prodaje) -> ima prednost pred karticama
        page_evs.update({uid_from_url(j["url"]): j for j in parse_events(html) if uid_from_url(j["url"])})
        new = {uid: j for uid, j in page_evs.items() if uid not in found}
        if not new:
            break
        found.update(new)
        if want and want <= found.keys():
            break
    return found


def _big_venues(ctx: Context, venues: dict, min_weight: int) -> list[str]:
    """Dvorane s watchliste (stadioni, arene) -> URL-ovi njihovih stranica."""
    from radar.scoring import Scorer

    rules = [r for r in Scorer(ctx.watchlist).rules if r.group == "venue" and r.weight >= min_weight]
    out = []
    for vslug, (city_slug, name, loc) in venues.items():
        toks = tokens(f"{name} {city_slug}")
        if any(p.found_in(toks) for r in rules for p in r.phrases):
            out.append(loc)
    return sorted(out)


def fetch(ctx: Context, cfg: dict) -> list[Event]:
    name = cfg["_name"]
    country = cfg.get("country", "")
    idx = sitemap_index(get_text(ctx.client, cfg["sitemap"]))
    ev_maps = [u for u, _ in idx if "/events" in u]
    ar_maps = [u for u, _ in idx if "/artist" in u] if cfg.get("artists", True) else []
    ve_maps = [u for u, _ in idx if "/venue" in u]
    if not ev_maps:
        raise RuntimeError("u sitemap indexu nema events sitemapa")
    ev_lists = [fetch_sitemap(ctx.client, u) for u in ev_maps]
    ar_lists = [fetch_sitemap(ctx.client, u) for u in ar_maps]
    venues = _venue_map(fetch_sitemap(ctx.client, u) for u in ve_maps)
    out: list[Event] = []
    by_uid: dict[str, Event] = {}
    for lst in ev_lists:
        for loc, lastmod in lst:
            m = _EVENT_RE.search(loc)
            if not m:
                continue
            title, venue, city, city_slug = split_slug(m.group(1), venues)
            bv = best_venue(m.group(1), venues)
            vurl = venues[bv][2] if bv else ""
            e = Event(source=name, uid=m.group(2), title=title, url=loc, kind="listing",
                      venue=venue, city=city, country=guess_country(m.group(1), city_slug, country),
                      extra={"lastmod": lastmod, "needs_enrich": True, "venue_url": vurl})
            out.append(e)
            by_uid[e.uid] = e
    for lst in ar_lists:
        for loc, lastmod in lst:
            m = _ARTIST_RE.search(loc)
            if not m:
                continue
            out.append(Event(source=name, uid="artist:" + m.group(1), title=slug_title(m.group(1)), url=loc,
                             kind="artist", country=country,
                             summary="Nova stranica izvodjaca na Eventimu", extra={"lastmod": lastmod}))

    # periodicki: velike dvorane -> detalji i statusi za sve njihove evente (za detekciju promjena)
    every = int(cfg.get("venue_scan_every", 4))
    if every and ctx.run_no % every == 0:
        try:
            for vurl in _big_venues(ctx, venues, int(cfg.get("venue_min_weight", 40)))[: int(cfg.get("max_venues", 15))]:
                for uid, j in scan_venue(ctx, vurl, max_pages=int(cfg.get("venue_pages", 3))).items():
                    if uid in by_uid:
                        apply_detail(by_uid[uid], j)
        except Blocked:
            print(f"  {name}: bot-provjera na stranicama dvorana, preskačem do idućeg runa")
        except Exception as ex:  # noqa: BLE001 - detalji su bonus, sitemap je glavni podatak
            print(f"  {name}: greška kod stranica dvorana: {ex}")
    return out


def enrich(ctx: Context, events: list[Event], max_venues: int = 8) -> None:
    """Za NOVE evente: dohvati stranicu njihove dvorane i uzmi datum, pocetak prodaje, status, cijenu."""
    todo: dict[str, list[Event]] = {}
    for e in events:
        if e.kind == "listing" and e.extra.get("needs_enrich") and e.country != "XX" and e.extra.get("venue_url"):
            todo.setdefault(e.extra["venue_url"], []).append(e)
    for vurl, evs in list(todo.items())[:max_venues]:
        try:
            found = scan_venue(ctx, vurl, want={e.uid for e in evs})
        except Blocked:
            for e in evs:
                e.extra["enrich_error"] = "bot-provjera"
            return
        except Exception as ex:  # noqa: BLE001
            for e in evs:
                e.extra["enrich_error"] = str(ex)[:100]
            continue
        for e in evs:
            if e.uid in found:
                apply_detail(e, found[e.uid])
