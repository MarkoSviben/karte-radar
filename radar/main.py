"""Glavni program.

  python -m radar scan [--dry-run] [--show-all] [--only IZVOR] [--digest-now]
  python -m radar digest [--dry-run]        # posalji jutarnji sazetak odmah
  python -m radar check [--only IZVOR]      # samo dohvati izvore i ispisi sto vide (ne dira stanje)
  python -m radar test-notify               # probna obavijest
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from radar import notify as N
from radar import overview
from radar.http import make_client
from radar.models import Event
from radar.scoring import Scorer
from radar.sources import ENRICHERS, REGISTRY
from radar.sources.bandsintown import Skip
from radar.sources.base import Context
from radar.state import State
from radar.textnorm import key_tokens, similar

TZ = ZoneInfo("Europe/Zagreb")
ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
STATE_PATH = Path(os.environ.get("RADAR_STATE", ROOT / "state" / "seen.json"))

MAX_INSTANT_PER_RUN = 15
FAIL_ALERT_AFTER = 3
DIGEST_HOUR = int(os.environ.get("RADAR_DIGEST_HOUR", "9"))

HEADERS = {"listing": "🔥 NOVI EVENT", "news": "📰 NAJAVA", "artist": "🎤 NOVI IZVOĐAČ NA EVENTIMU",
           "tour": "🗺 TURNEJA U REGIJI"}


def load_yaml(name: str) -> dict:
    return yaml.safe_load((CONFIG / name).read_text(encoding="utf-8")) or {}


def _when(e: Event) -> str:
    """Datum eventa kao usporediv string (ISO dan ili normalizirani tekst)."""
    if e.start:
        return e.start[:10]
    return " ".join(e.date.lower().split())


def parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=TZ)


# ---------------------------------------------------------------- izvori

def run_sources(ctx: Context, sources: dict, only: str | None = None) -> dict:
    """-> {ime: {"events": [...] | None, "error": str, "skipped": bool, "secs": float, "cfg": cfg}}"""
    jobs = {}
    for name, cfg in sources.items():
        if only and name != only:
            continue
        if not cfg.get("enabled", True):
            continue
        cfg = {**cfg, "_name": name}
        if cfg["type"] not in REGISTRY:
            print(f"! nepoznat tip izvora {cfg['type']} ({name})")
            continue
        every = int(cfg.get("every", 1))
        if not only and every > 1 and ctx.run_no % every != 0:
            jobs[name] = {"events": None, "error": "", "skipped": True, "secs": 0.0, "cfg": cfg}
            continue
        jobs[name] = {"cfg": cfg}

    def one(name):
        cfg = jobs[name]["cfg"]
        t = time.time()
        try:
            evs = REGISTRY[cfg["type"]](ctx, cfg)
            return name, {"events": evs, "error": "", "skipped": False}, time.time() - t
        except Skip as ex:
            return name, {"events": None, "error": str(ex), "skipped": True}, time.time() - t
        except Exception as ex:  # noqa: BLE001 - jedan izvor ne smije srusiti ostale
            return name, {"events": None, "error": f"{type(ex).__name__}: {str(ex)[:150]}", "skipped": False}, time.time() - t

    todo = [n for n, j in jobs.items() if "skipped" not in j]
    with cf.ThreadPoolExecutor(8) as ex:
        for name, res, secs in ex.map(one, todo):
            jobs[name].update(res, secs=secs)
    return jobs


# ---------------------------------------------------------------- obrada

class Run:
    def __init__(self, st: State, wl: dict, notifier: N.Notifier, ctx: Context, now: datetime,
                 show_all: bool = False):
        self.st, self.wl, self.nt, self.ctx, self.now = st, wl, notifier, ctx, now
        self.ts = now.timestamp()
        self.scorer = Scorer(wl)
        self.countries = set(wl.get("countries") or [])
        self.show_all = show_all
        self.health: list[str] = []
        self.baseline: list[tuple[str, int]] = []
        self.changes: list[tuple[Event, list, list]] = []  # (event, staro, novo) status/pocetak prodaje

    # 1) usporedi s vidjenim
    def collect_new(self, results: dict) -> list[Event]:
        new: list[Event] = []
        for name, res in results.items():
            if res.get("skipped"):
                continue
            s = self.st.source(name)
            events, err = res["events"], res["error"]
            if err or (not events and not res["cfg"].get("allow_empty")):
                s["fail"] = s.get("fail", 0) + 1
                s["last_error"] = err or "0 rezultata (promijenila se stranica?)"
                if s["fail"] >= FAIL_ALERT_AFTER and not s.get("alerted"):
                    self.health.append(f"⚠️ Izvor <b>{name}</b> ne radi već {s['fail']} runova: {N.esc(s['last_error'])}")
                    s["alerted"] = True
                continue
            if s.get("alerted"):
                self.health.append(f"✅ Izvor <b>{name}</b> ponovno radi ({len(events)} stavki)")
            s.update(fail=0, alerted=False, last_ok=self.ts, last_count=len(events), last_error="")
            seen = s.setdefault("seen", {})
            fresh = [e for e in events if e.uid not in seen]
            for e in events:
                seen[e.uid] = self.ts
            first = s.setdefault("first", {})
            if s.get("initialized"):
                for e in fresh:
                    first[e.uid] = self.ts
            if not s.get("initialized") and not self.show_all:
                self._track_changes(s, events, {e.uid for e in events})  # samo zapamti, bez obavijesti
                s["initialized"] = True
                self.baseline.append((name, len(events)))
                continue
            s["initialized"] = True
            new.extend(events if self.show_all else fresh)
            if res["cfg"]["type"] in ENRICHERS:
                batch = events if self.show_all else fresh
                ENRICHERS[res["cfg"]["type"]](self.ctx, batch)
            self._track_changes(s, events, {e.uid for e in fresh})
        return new

    def _track_changes(self, s: dict, events: list[Event], fresh: set[str]) -> None:
        """Pamti status i pocetak prodaje; promjena na vec poznatom eventu -> self.changes."""
        snap = s.setdefault("snap", {})
        for e in events:
            if not (e.availability or e.sale_start):
                continue
            cur = [e.availability, e.sale_start, self.ts]
            old = snap.get(e.uid)
            if old and e.uid not in fresh and (old[0], old[1]) != (cur[0], cur[1]):
                self.changes.append((e, old, cur))
            snap[e.uid] = cur
        # zaboravi snimke starije od 120 dana
        for uid in [u for u, v in snap.items() if self.ts - v[2] > 120 * 86400]:
            snap.pop(uid, None)

    # 2) filtriraj, boduj, ukloni duplikate
    def rank(self, events: list[Event]) -> list[Event]:
        out = []
        for e in events:
            if e.country and self.countries and e.country not in self.countries:
                continue
            out.append(self.scorer.score(e))
        out.sort(key=lambda e: -e.score)
        reps: list[Event] = []
        index: dict[tuple[str, str], list[Event]] = {}  # (klasa, token) -> kandidati
        for e in out:
            cls = "news" if e.kind == "news" else "listing"
            keys = [(cls, t) for t in key_tokens(e.title)]
            cands = {id(r): r for k in keys for r in index.get(k, [])}.values()
            dup = next((r for r in cands if similar(r.title, e.title) >= 0.85), None)
            if dup:
                # isti event vise puta u istom runu (vise termina ili vise izvora) -> jedna poruka
                if e.source not in dup.extra.setdefault("also", []) and e.source != dup.source:
                    dup.extra["also"].append(e.source)
                if _when(e) and _when(e) != _when(dup):
                    dup.extra["n_dates"] = dup.extra.get("n_dates", 1) + 1
                continue
            if cls == "listing":
                prev = [r for r in self.st.recent if r["kind"] == cls and similar(r["t"], e.title) >= 0.85]
                if prev:
                    # vec javljeno; ako je drugi datum -> DODATNI TERMIN, inace duplikat s drugog izvora
                    if _when(e) and all(r.get("when") and r["when"] != _when(e) for r in prev):
                        e.extra["extra_date"] = True
                        e.reasons.insert(0, "dodatni termin")
                    else:
                        continue
            reps.append(e)
            for k in keys:
                index.setdefault(k, []).append(e)
        return reps

    # 3) posalji / stavi u sazetak / zakazi podsjetnike
    def dispatch(self, events: list[Event]) -> None:
        instant_sent = 0
        for e in events:
            if e.score < self.scorer.digest:
                continue
            cls = "news" if e.kind == "news" else "listing"
            labels = e.extra.get("labels") or []
            go_instant = e.score >= self.scorer.instant
            # vise clanaka o istom izvodjacu unutar 24h -> samo prvi ide odmah
            if go_instant and cls == "news" and labels and any(
                    r.get("label") in labels and r["kind"] == "news" and self.ts - r["ts"] < 86400
                    for r in self.st.recent):
                go_instant = False
            if go_instant and instant_sent >= MAX_INSTANT_PER_RUN:
                go_instant = False
            sale = parse_iso(e.sale_start)
            header = "➕ DODATNI TERMIN" if e.extra.get("extra_date") else HEADERS.get(e.kind, "🔥 NOVO")
            if e.extra.get("n_dates", 1) > 1:
                header += f" ({e.extra['n_dates']} termina)"
            if sale and sale > self.now:
                header += f" · PRODAJA KREĆE {N.fmt_dt(e.sale_start)}"
            if go_instant:
                self.nt.send(N.event_message(e, header))
                instant_sent += 1
                self.st.recent.append({"t": e.title, "kind": cls, "label": labels[0] if labels else "",
                                       "when": _when(e), "ts": self.ts})
            else:
                self.st.digest_queue.append({**e.to_dict(), "_queued": self.ts})
            if sale and sale > self.now:
                sent = ["24h"] if go_instant and sale - self.now <= timedelta(hours=24) else []
                self.st.reminders[f"{e.source}:{e.uid}"] = {**e.to_dict(), "sent": sent}
        if instant_sent >= MAX_INSTANT_PER_RUN:
            self.nt.send(f"ℹ️ Ima još novih velikih evenata, poslao sam prvih {MAX_INSTANT_PER_RUN}; ostali su u jutarnjem sažetku.")

    # 4) podsjetnici prije pocetka prodaje
    def reminders(self) -> None:
        for key, r in list(self.st.reminders.items()):
            sale = parse_iso(r.get("sale_start", ""))
            if not sale or self.now - sale > timedelta(days=1):
                self.st.reminders.pop(key, None)
                continue
            left = sale - self.now
            e = Event.from_dict(r)
            sent = r.setdefault("sent", [])
            if timedelta(minutes=-30) < left <= timedelta(hours=2) and "2h" not in sent:
                mins = max(0, int(left.total_seconds() // 60))
                self.nt.send(N.event_message(e, f"🚨 PRODAJA KREĆE ZA ~{mins} MIN ({N.fmt_dt(r['sale_start'])})"))
                sent += ["2h", "24h"]
            elif timedelta(hours=2) < left <= timedelta(hours=24) and "24h" not in sent:
                hrs = int(left.total_seconds() // 3600)
                self.nt.send(N.event_message(e, f"⏰ PRODAJA KREĆE ZA ~{hrs} H ({N.fmt_dt(r['sale_start'])})"))
                sent.append("24h")

    # 5) promjene na poznatim eventima (rasprodano, objavljen datum prodaje, prodaja otvorena)
    def dispatch_changes(self) -> None:
        for e, old, cur in self.changes:
            if e.country and self.countries and e.country not in self.countries:
                continue
            e = self.scorer.score(e)
            if e.score < self.scorer.digest:
                continue
            bits = []
            if old[0] != cur[0] and cur[0]:
                bits.append(f"{N.status_hr(old[0]) or '?'} → {N.status_hr(cur[0])}")
            if old[1] != cur[1] and cur[1]:
                bits.append(("datum prodaje promijenjen: " if old[1] else "objavljen početak prodaje: ") + N.fmt_dt(cur[1]))
            if not bits:
                continue
            e.reasons.insert(0, "promjena")
            sale = parse_iso(e.sale_start)
            key = f"{e.source}:{e.uid}"
            if sale and sale > self.now and key not in self.st.reminders:
                self.st.reminders[key] = {**e.to_dict(), "sent": []}
            if e.score >= self.scorer.instant:
                self.nt.send(N.event_message(e, "🔄 PROMJENA: " + "; ".join(bits)))
            else:
                e.title = f"[{'; '.join(bits)}] {e.title}"
                self.st.digest_queue.append({**e.to_dict(), "_queued": self.ts})

    # 6) jutarnji sazetak
    def digest(self, results: dict | None, force: bool = False) -> None:
        today = self.now.strftime("%Y-%m-%d")
        if not force and (self.now.hour < DIGEST_HOUR or self.st.last_digest == today):
            return
        lines = []
        upcoming = []
        for r in self.st.reminders.values():
            sale = parse_iso(r.get("sale_start", ""))
            if sale and self.now < sale < self.now + timedelta(days=7):
                upcoming.append((sale, Event.from_dict(r)))
        if upcoming:
            lines.append("\n<b>🛒 Prodaje koje kreću u idućih 7 dana</b>")
            for sale, e in sorted(upcoming, key=lambda x: x[0]):
                lines.append(f"• {N.fmt_dt(e.sale_start)}: " + N.digest_line(e))
        queue = sorted((Event.from_dict(d) for d in self.st.digest_queue), key=lambda e: -e.score)
        if queue:
            lines.append(f"\n<b>🆕 Novo od zadnjeg sažetka ({len(queue)})</b>")
            for e in queue[:60]:
                lines.append(N.digest_line(e))
            if len(queue) > 60:
                lines.append(f"… i još {len(queue) - 60} manjih")
        if not lines:
            lines.append("\nNema novih evenata vrijednih spomena.")
        bad = [n for n, s in self.st.sources.items() if s.get("fail", 0) >= FAIL_ALERT_AFTER]
        lines.append(f"\n🩺 Izvori: {len(self.st.sources) - len(bad)} rade"
                     + (f", ne rade: {', '.join(bad)}" if bad else "")
                     + f" · evenata s detaljima: {sum(len(x.get('snap', {})) for x in self.st.sources.values())}")
        header = f"☀️ <b>Jutarnji sažetak {self.now.strftime('%d.%m.%Y.')}</b>"
        for part in N.chunk(lines, header):
            self.nt.send(part, silent=True)
        self.st.digest_queue = []
        self.st.last_digest = today


def scan(args) -> int:
    t0 = time.time()
    st = State.load(STATE_PATH)
    st.runs += 1
    wl = load_yaml("watchlist.yaml")
    sources = load_yaml("sources.yaml")
    nt = N.Notifier(dry_run=args.dry_run)
    now = datetime.now(TZ)
    with make_client() as client:
        ctx = Context(client=client, watchlist=wl, run_no=st.runs)
        results = run_sources(ctx, sources, only=args.only)
        for name, r in results.items():
            status = "preskočen" if r.get("skipped") else (f"GREŠKA {r['error']}" if r["error"] else f"{len(r['events'])} stavki")
            print(f"  {name:14} {r.get('secs', 0):5.1f}s  {status}")
        run = Run(st, wl, nt, ctx, now, show_all=args.show_all)
        new = run.collect_new(results)
        ranked = run.rank(new)
        print(f"Novih: {len(new)}, nakon filtera/duplikata: {len(ranked)}, "
              f"za odmah: {sum(e.score >= run.scorer.instant for e in ranked)}, "
              f"za sažetak: {sum(run.scorer.digest <= e.score < run.scorer.instant for e in ranked)}")
        if args.show_all:
            for e in ranked[:40]:
                print(f"   [{e.score:3}] {e.kind:7} {e.source:12} {e.title[:70]} | {e.city} {e.date or e.start[:10]} | {', '.join(e.reasons[:4])}")
            if not args.send:
                ranked = []  # --show-all bez --send samo ispisuje, ne salje
        run.dispatch(ranked)
        run.reminders()
        run.dispatch_changes()
        for h in run.health:
            nt.send(h)
        if run.baseline:
            total = sum(n for _, n in run.baseline)
            if not st.started:
                body = "\n".join(f"• {n}: {c}" for n, c in run.baseline)
                nt.send(f"✅ <b>Karte radar je pokrenut</b>\nZapamtio sam {total} postojećih evenata/članaka:\n{body}\n\n"
                        f"Od sada javljam samo NOVE stvari. Sažetak stiže svako jutro u {DIGEST_HOUR}:00.")
            else:
                print(f"Novi izvori inicijalizirani: {run.baseline}")
        st.started = True
        if not args.no_digest:
            run.digest(results, force=args.digest_now)
        write_overview(st, wl, results, now, None if args.dry_run else STATE_PATH.parent / "PREGLED.md")
    if args.dry_run:
        print("(dry-run: stanje NIJE spremljeno)")
    else:
        st.save()
    print(f"Gotovo za {time.time() - t0:.1f}s, poslano poruka: {nt.sent}")
    return 0


def write_overview(st: State, wl: dict, results: dict, now: datetime, path: Path | None) -> None:
    first = {f"{n}:{u}": ts for n, s in st.sources.items() for u, ts in s.get("first", {}).items()}
    md = overview.build(results, Scorer(wl), set(wl.get("countries") or []), now, first)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(md, encoding="utf-8")
        print(f"Pregled: {path} ({md.count(chr(10))} redaka)")


def pregled_cmd(args) -> int:
    """Napravi PREGLED.md lokalno (bez diranja stanja)."""
    st = State.load(STATE_PATH)
    wl = load_yaml("watchlist.yaml")
    with make_client() as client:
        results = run_sources(Context(client=client, watchlist=wl, run_no=4), load_yaml("sources.yaml"))
    write_overview(st, wl, results, datetime.now(TZ), Path(args.out))
    return 0


def check(args) -> int:
    sources = load_yaml("sources.yaml")
    wl = load_yaml("watchlist.yaml")
    scorer = Scorer(wl)
    with make_client() as client:
        ctx = Context(client=client, watchlist=wl, run_no=0)
        results = run_sources(ctx, sources, only=args.only)
    for name, r in results.items():
        if r.get("skipped"):
            print(f"\n=== {name}: preskočen {r.get('error', '')}")
            continue
        if r["error"]:
            print(f"\n=== {name}: GREŠKA {r['error']}")
            continue
        evs = [scorer.score(e) for e in r["events"]]
        print(f"\n=== {name}: {len(evs)} stavki ({r['secs']:.1f}s); top 8 po bodovima:")
        for e in sorted(evs, key=lambda e: -e.score)[:8]:
            print(f"   [{e.score:3}] {e.kind:7} {e.title[:70]} | {e.venue[:25]} {e.city} {e.date} | {', '.join(e.reasons[:4])}")
    return 0


def digest_cmd(args) -> int:
    st = State.load(STATE_PATH)
    nt = N.Notifier(dry_run=args.dry_run)
    with make_client() as client:
        run = Run(st, load_yaml("watchlist.yaml"), nt, Context(client=client), datetime.now(TZ))
        run.digest(None, force=True)
    if not args.dry_run:
        st.save()
    return 0


def test_notify(args) -> int:
    nt = N.Notifier(dry_run=False)
    ok = nt.send("👋 <b>Karte radar: probna poruka</b>\nAko ovo vidiš, obavijesti rade!")
    print("OK" if ok and not nt.dry_run else "Nije poslano (provjeri NTFY_TOPIC ili Telegram postavke)")
    return 0 if ok and not nt.dry_run else 1


def cli() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows konzola
    except AttributeError:
        pass
    p = argparse.ArgumentParser(prog="radar")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="glavni run (cron)")
    s.add_argument("--dry-run", action="store_true", help="ne salji na Telegram i ne spremaj stanje")
    s.add_argument("--show-all", action="store_true", help="tretiraj sve kao novo (test bodovanja)")
    s.add_argument("--send", action="store_true", help="uz --show-all stvarno posalji poruke")
    s.add_argument("--only", help="samo jedan izvor")
    s.add_argument("--digest-now", action="store_true", help="posalji sazetak odmah")
    s.add_argument("--no-digest", action="store_true")
    s.set_defaults(fn=scan)
    c = sub.add_parser("check", help="dohvati izvore i ispisi sto vide")
    c.add_argument("--only")
    c.set_defaults(fn=check)
    d = sub.add_parser("digest", help="posalji sazetak odmah")
    d.add_argument("--dry-run", action="store_true")
    d.set_defaults(fn=digest_cmd)
    pr = sub.add_parser("pregled", help="napravi PREGLED.md lokalno")
    pr.add_argument("--out", default="PREGLED.md")
    pr.set_defaults(fn=pregled_cmd)
    t = sub.add_parser("test-notify", aliases=["test-telegram"], help="probna obavijest")
    t.set_defaults(fn=test_notify)
    args = p.parse_args()
    sys.exit(args.fn(args))
