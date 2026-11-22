"""Registar izvora. Svaki izvor je funkcija fetch(ctx, cfg) -> list[Event]."""
from __future__ import annotations

from radar.sources import (bandsintown, eventim, gigstix, kupikartu_ba, mojekarte_si, news,
                           tickets_rs, ulaznice_hr)

REGISTRY = {
    "eventim": eventim.fetch,
    "tickets_rs": tickets_rs.fetch,
    "gigstix": gigstix.fetch,
    "ulaznice_hr": ulaznice_hr.fetch,
    "kupikartu_ba": kupikartu_ba.fetch,
    "mojekarte_si": mojekarte_si.fetch,
    "google_news": news.fetch_google_news,
    "rss": news.fetch_rss,
    "bandsintown": bandsintown.fetch,
}

# izvori koji znaju dohvatiti detalje (datum, dvorana, pocetak prodaje) za NOVE evente
ENRICHERS = {
    "eventim": eventim.enrich,
}
