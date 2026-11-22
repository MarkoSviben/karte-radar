"""Slanje obavijesti: ntfy.sh stranica (glavno), Telegram (opcija) ili ispis u konzolu (--dry-run)."""
from __future__ import annotations

import html
import os
import re
import time

import httpx

from radar.models import Event

MAX_LEN = 3000  # ntfy prima do 4096 bajtova, a nasa slova su 2 bajta
COUNTRY_FLAG = {"HR": "🇭🇷", "RS": "🇷🇸", "BA": "🇧🇦", "SI": "🇸🇮", "ME": "🇲🇪", "MK": "🇲🇰"}
KIND_ICON = {"listing": "🎟", "news": "📰", "artist": "🎤", "tour": "🗺"}


STATUS_HR = {"InStock": "u prodaji", "SoldOut": "RASPRODANO", "OutOfStock": "nema karata",
             "LimitedAvailability": "malo karata", "PreSale": "pretprodaja", "PreOrder": "uskoro u prodaji",
             "OnlineOnly": "samo online", "Discontinued": "prodaja završena"}


def status_hr(av: str) -> str:
    """'InStock,OutOfStock' -> 'u prodaji / nema karata (dio kategorija)'"""
    parts = [STATUS_HR.get(a, a) for a in (av or "").split(",") if a]
    if len(parts) > 1:
        return " / ".join(parts) + " (ovisno o kategoriji)"
    return parts[0] if parts else ""


def esc(s: str) -> str:
    return html.escape(s or "", quote=False)


def fmt_dt(iso: str) -> str:
    """'2026-11-12T12:24:00.000+01:00' -> '12.11.2026. 12:24'"""
    if not iso or len(iso) < 10 or iso[4] != "-":
        return iso
    d = f"{iso[8:10]}.{iso[5:7]}.{iso[0:4]}."
    if len(iso) >= 16 and iso[10] == "T":
        hm = iso[11:16]
        if hm != "00:00":
            d += f" {hm}"
    return d


def event_message(e: Event, header: str = "") -> str:
    icon = KIND_ICON.get(e.kind, "🎟")
    lines = []
    if header:
        lines.append(f"<b>{esc(header)}</b>")
    lines.append(f"{icon} <b>{esc(e.title)}</b>")
    place = ", ".join(x for x in (e.venue, e.city) if x)
    if place or e.country:
        lines.append(f"📍 {esc(place)} {COUNTRY_FLAG.get(e.country, e.country)}".rstrip())
    when = fmt_dt(e.start) or e.date
    if when:
        lines.append(f"📅 {esc(when)}")
    if e.sale_start or e.availability:
        bits = []
        if e.sale_start:
            bits.append(f"prodaja od {fmt_dt(e.sale_start)}")
        if e.availability:
            bits.append(status_hr(e.availability))
        lines.append("🛒 " + esc(" · ".join(bits)))
    if e.price:
        lines.append(f"💶 {esc(e.price)}")
    if e.summary and e.kind == "news":
        lines.append(f"<i>{esc(e.summary[:250])}</i>")
    lines.append(f"⭐ {e.score} ({esc(', '.join(e.reasons[:5]))}) · {esc(e.source)}")
    lines.append(f'🔗 <a href="{html.escape(e.url)}">Otvori</a>')
    return "\n".join(lines)


def digest_line(e: Event) -> str:
    when = fmt_dt(e.start) or e.date
    meta = " · ".join(x for x in (e.city, when, e.source) if x)
    return f'{KIND_ICON.get(e.kind, "•")} <a href="{html.escape(e.url)}">{esc(e.title[:90])}</a> <i>{esc(meta)}</i> [{e.score}]'


def chunk(text_lines: list[str], header: str = "") -> list[str]:
    out, cur = [], header
    for ln in text_lines:
        if len(cur) + len(ln) + 1 > MAX_LEN:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n{ln}" if cur else ln
    if cur:
        out.append(cur)
    return out


def html_to_markdown(text: str) -> tuple[str, str, str]:
    """Telegram HTML -> (naslov, markdown tijelo, prvi link) za ntfy."""
    first_link = ""
    m = re.search(r'<a href="([^"]+)"', text)
    if m:
        first_link = html.unescape(m.group(1))
    md = re.sub(r'<a href="([^"]+)">(.*?)</a>', lambda x: f"[{x.group(2)}]({x.group(1)})", text, flags=re.S)
    md = re.sub(r"</?b>", "**", md)
    md = re.sub(r"</?i>", "_", md)
    md = html.unescape(re.sub(r"<[^>]+>", "", md))
    lines = md.strip().split("\n")
    title = lines[0].replace("**", "").strip()
    body = "\n".join(lines[1:]).strip() or title
    return title[:200], body, first_link


def _priority(title: str, silent: bool) -> int:
    if silent:
        return 2
    if title.startswith(("🚨", "🔥", "➕", "🔄", "⏰", "🎤", "🗺")):
        return 4
    return 3


class Notifier:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        self.chat_ids = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
        self.ntfy_topic = os.environ.get("NTFY_TOPIC", "").strip()
        self.ntfy_server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
        self.sent = 0
        if not dry_run and not self.ntfy_topic and not (self.token and self.chat_ids):
            print("! NTFY_TOPIC (ili TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID) nije postavljen -> ispisujem u konzolu")
            self.dry_run = True

    def send(self, text: str, silent: bool = False) -> bool:
        if self.dry_run:
            print("----- [OBAVIJEST] -----")
            print(text)
            self.sent += 1
            return True
        ok = True
        if self.ntfy_topic:
            ok &= self._ntfy(text, silent)
        if self.token and self.chat_ids:
            ok &= self._telegram(text, silent)
        self.sent += 1
        return ok

    def _ntfy(self, text: str, silent: bool) -> bool:
        title, body, link = html_to_markdown(text)
        payload = {"topic": self.ntfy_topic, "title": title, "message": body, "markdown": True,
                   "priority": _priority(title, silent)}
        if link:
            payload["click"] = link
            payload["actions"] = [{"action": "view", "label": "Otvori", "url": link}]
        for _ in range(3):
            try:
                r = httpx.post(self.ntfy_server, json=payload, timeout=20)
                if r.status_code == 429:
                    time.sleep(5)
                    continue
                if r.status_code != 200:
                    print(f"! ntfy greska {r.status_code}: {r.text[:200]}")
                    return False
                time.sleep(0.3)
                return True
            except httpx.HTTPError as ex:
                print(f"! ntfy greska: {ex}")
                time.sleep(2)
        return False

    def _telegram(self, text: str, silent: bool) -> bool:
        ok = True
        for chat in self.chat_ids:
            for _ in range(3):
                try:
                    r = httpx.post(
                        f"https://api.telegram.org/bot{self.token}/sendMessage",
                        json={"chat_id": chat, "text": text, "parse_mode": "HTML",
                              "disable_web_page_preview": True, "disable_notification": silent},
                        timeout=20,
                    )
                    if r.status_code == 429:
                        time.sleep(int(r.json().get("parameters", {}).get("retry_after", 3)) + 1)
                        continue
                    if r.status_code != 200:
                        print(f"! Telegram greska {r.status_code}: {r.text[:200]}")
                        ok = False
                    break
                except httpx.HTTPError as ex:
                    print(f"! Telegram greska: {ex}")
                    time.sleep(2)
            time.sleep(0.4)
        return ok
