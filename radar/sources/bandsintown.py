"""Bandsintown: najave turneja izvodjaca s watchliste u nasoj regiji (rani signal).

Treba BANDSINTOWN_APP_ID (env / GitHub secret). Bez njega se izvor preskace.
Pokrece se samo svaki `every`-ti run da se ne trose minute i API.
"""
from __future__ import annotations

import concurrent.futures as cf
import os
import urllib.parse as up

from radar.models import Event
from radar.sources.base import Context

COUNTRIES = {"Croatia": "HR", "Serbia": "RS", "Bosnia and Herzegovina": "BA", "Slovenia": "SI",
             "Montenegro": "ME", "North Macedonia": "MK"}


class Skip(Exception):
    """Izvor se namjerno preskace (nije greska)."""


def _artist_names(wl: dict, groups: list[str]) -> list[str]:
    names = []
    arts = wl.get("artists") or {}
    for g in groups:
        sec = arts.get(g) or {}
        for item in (sec.get("list") if isinstance(sec, dict) else sec) or []:
            raw = next(iter(item)) if isinstance(item, dict) else str(item)
            names.append(raw.split("|")[0].lstrip("="))
    return names


def fetch(ctx: Context, cfg: dict) -> list[Event]:
    app_id = os.environ.get("BANDSINTOWN_APP_ID", "").strip()
    if not app_id:
        raise Skip("nema BANDSINTOWN_APP_ID")
    names = _artist_names(ctx.watchlist, cfg.get("artist_groups", ["strani"]))
    out: list[Event] = []
    errors = 0

    def one(name: str):
        url = f"https://rest.bandsintown.com/artists/{up.quote(name, safe='')}/events?app_id={up.quote(app_id)}&date=upcoming"
        r = ctx.client.get(url, headers={"Accept": "application/json"})
        if r.status_code == 404:
            return name, []
        r.raise_for_status()
        data = r.json()
        return name, data if isinstance(data, list) else []

    with cf.ThreadPoolExecutor(6) as ex:
        futs = [ex.submit(one, n) for n in names]
        for f in cf.as_completed(futs):
            try:
                name, events = f.result()
            except Exception:  # noqa: BLE001
                errors += 1
                continue
            for ev in events:
                v = ev.get("venue") or {}
                cc = COUNTRIES.get(v.get("country", ""))
                if not cc:
                    continue
                offers = ev.get("offers") or []
                status = ", ".join(sorted({o.get("status", "") for o in offers if o.get("status")}))
                out.append(Event(
                    source=cfg["_name"], uid=str(ev.get("id")), title=f"{name} @ {v.get('name', '')}".strip(" @"),
                    url=ev.get("url", ""), kind="tour", venue=v.get("name", ""), city=v.get("city", ""),
                    country=cc, start=ev.get("datetime", ""), sale_start=ev.get("on_sale_datetime") or "",
                    availability=status, summary=ev.get("description", "")[:200],
                ))
    if names and errors == len(names):
        raise RuntimeError("Bandsintown API ne odgovara (provjeri BANDSINTOWN_APP_ID)")
    return out
