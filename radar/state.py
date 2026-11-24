"""Trajno stanje izmedju runova (state/seen.json). Na GitHubu se cuva na zasebnoj grani 'state'."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

DAY = 86400
SEEN_TTL_DAYS = 45  # uid koji se nije pojavio 45 dana se brise


class State:
    def __init__(self, path: Path, data: dict | None = None):
        self.path = path
        d = data or {}
        self.sources: dict = d.get("sources", {})
        self.digest_queue: list = d.get("digest_queue", [])
        self.reminders: dict = d.get("reminders", {})
        self.watch: dict = d.get("watch", {})
        self.recent: list = d.get("recent", [])
        self.news: dict = d.get("news", {})  # najave iz medija za web stranicu (7 dana)  # [{"t": naslov, "kind": .., "ts": ..}]
        self.history: list = d.get("history", [])  # promjene karata (status, faza/cijena, prodaja) za stranicu
        self.last_digest: str = d.get("last_digest", "")
        self.runs: int = d.get("runs", 0)
        self.started: bool = d.get("started", False)

    @classmethod
    def load(cls, path: Path) -> "State":
        if path.exists() and path.stat().st_size > 0:
            try:
                return cls(path, json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass
        return cls(path)

    def save(self) -> None:
        self.prune()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "sources": self.sources, "digest_queue": self.digest_queue, "reminders": self.reminders,
            "watch": self.watch, "recent": self.recent, "news": self.news, "history": self.history, "last_digest": self.last_digest,
            "runs": self.runs, "started": self.started,
        }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, self.path)

    def source(self, name: str) -> dict:
        return self.sources.setdefault(name, {"seen": {}, "initialized": False, "fail": 0, "alerted": False})

    def prune(self, now: float | None = None) -> None:
        now = now or time.time()
        for s in self.sources.values():
            s["seen"] = {k: v for k, v in s.get("seen", {}).items() if now - v < SEEN_TTL_DAYS * DAY}
            s["first"] = {k: v for k, v in s.get("first", {}).items() if now - v < 14 * DAY}
        self.history = [h for h in self.history if now - h.get("ts", now) < 45 * DAY][-800:]
        self.recent = [r for r in self.recent if now - r["ts"] < 7 * DAY]
        self.news = {k: v for k, v in self.news.items() if now - v.get("ts", now) < 7 * DAY}
        self.digest_queue = [e for e in self.digest_queue if now - e.get("_queued", now) < 3 * DAY][-500:]
