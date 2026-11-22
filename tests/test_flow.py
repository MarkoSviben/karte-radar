"""Testovi cijelog toka (bez interneta): baseline, nove stvari, duplikati, podsjetnici, sazetak."""
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from radar.main import TZ, Run
from radar.models import Event
from radar.scoring import Scorer
from radar.sources.base import Context
from radar.state import State

WL = yaml.safe_load((Path(__file__).parent.parent / "config" / "watchlist.yaml").read_text(encoding="utf-8"))


class FakeNotifier:
    def __init__(self):
        self.msgs = []
        self.sent = 0

    def send(self, text, silent=False):
        self.msgs.append(text)
        self.sent += 1
        return True


def res(events, typ="tickets_rs"):
    return {"events": events, "error": "", "skipped": False, "cfg": {"type": typ, "_name": "x"}}


def ev(uid, title, **kw):
    return Event(source="tickets_rs", uid=uid, title=title, url=f"https://x/{uid}", **kw)


def make_run(tmp_path, now=None, st=None):
    nt = FakeNotifier()
    st = st or State(tmp_path / "s.json")
    return Run(st, WL, nt, Context(client=None, watchlist=WL), now or datetime(2026, 11, 22, 12, 0, tzinfo=TZ)), nt


def test_scoring_examples():
    s = Scorer(WL)
    big = s.score(Event(source="t", uid="1", title="Severina", url="", venue="Arena Zagreb", kind="listing"))
    assert big.score >= s.instant
    tribute = s.score(Event(source="t", uid="2", title="Metallica tribute band", url="", kind="listing"))
    assert tribute.score < s.instant
    kids = s.score(Event(source="t", uid="3", title="Predstava za djecu Djeda Mraz", url="", kind="listing"))
    assert kids.score < s.digest
    gossip = s.score(Event(source="t", uid="4", title="Rasta neprepoznatljiv na aerodromu", url="", kind="news"))
    assert gossip.score == 0
    sale = s.score(Event(source="t", uid="5", title="Počela prodaja karata za Stingov koncert u Beogradu", url="", kind="news"))
    assert sale.score >= s.instant
    abroad = s.score(Event(source="t", uid="6", title="Aca Lukas koncert u Beču, karte u prodaji", url="", kind="news"))
    assert abroad.score < sale.score


def test_baseline_then_new(tmp_path):
    run, nt = make_run(tmp_path)
    assert run.collect_new({"tickets_rs": res([ev("1", "Stari event")])}) == []
    assert run.baseline == [("tickets_rs", 1)]
    run2, nt2 = make_run(tmp_path, st=run.st)
    new = run2.collect_new({"tickets_rs": res([ev("1", "Stari event"), ev("2", "Severina", venue="Arena Zagreb")])})
    assert [e.uid for e in new] == ["2"]
    run2.dispatch(run2.rank(new))
    assert len(nt2.msgs) == 1 and "Severina" in nt2.msgs[0]


def test_duplicates_and_extra_date(tmp_path):
    run, nt = make_run(tmp_path)
    a = ev("a", "Bryan Adams", venue="Arena Zagreb", date="1.6.2027")
    b = Event(source="eventim_hr", uid="b", title="BRYAN ADAMS", url="u", venue="Arena Zagreb", date="1.6.2027")
    run.dispatch(run.rank([a, b]))
    assert len(nt.msgs) == 1  # isti event s dva izvora -> jedna poruka
    # sutra: isti naslov, isti datum s treceg izvora -> nista; drugi datum -> DODATNI TERMIN
    run.dispatch(run.rank([ev("c", "Bryan Adams", venue="Arena Zagreb", date="1.6.2027"),
                           ev("d", "Bryan Adams", venue="Arena Zagreb", date="2.6.2027")]))
    assert len(nt.msgs) == 2 and "DODATNI TERMIN" in nt.msgs[1]


def test_failure_alert_after_3(tmp_path):
    st = State(tmp_path / "s.json")
    for i in range(4):
        run, nt = make_run(tmp_path, st=st)
        run.collect_new({"tickets_rs": {"events": None, "error": "HTTP 500", "skipped": False, "cfg": {"type": "x"}}})
        assert len(run.health) == (1 if i == 2 else 0)
    run, nt = make_run(tmp_path, st=st)
    run.collect_new({"tickets_rs": res([ev("1", "x")])})
    assert "ponovno radi" in run.health[0]


def test_sale_reminders(tmp_path):
    now = datetime(2026, 11, 22, 12, 0, tzinfo=TZ)
    run, nt = make_run(tmp_path, now=now)
    e = ev("r", "Coldplay", venue="Maksimir", sale_start=(now + timedelta(hours=30)).isoformat())
    run.dispatch(run.rank([e]))
    assert "PRODAJA KREĆE" in nt.msgs[0]
    # 10h prije prodaje -> 24h podsjetnik, 1h prije -> 2h podsjetnik, pa vise nista
    for hours_later, expect in ((20, "⏰"), (29, "🚨"), (29.5, None)):
        r2, nt2 = make_run(tmp_path, now=now + timedelta(hours=hours_later), st=run.st)
        r2.reminders()
        assert (nt2.msgs[0].startswith(f"<b>{expect}") if expect else nt2.msgs == [])


def test_digest_once_per_day(tmp_path):
    now = datetime(2026, 11, 23, 9, 5, tzinfo=TZ)
    run, nt = make_run(tmp_path, now=now)
    run.dispatch(run.rank([ev("m", "Mali koncert jazz trija", venue="Klub")]))
    assert nt.msgs == [] and len(run.st.digest_queue) == 1
    run.digest(None)
    assert len(nt.msgs) == 1 and "Mali koncert" in nt.msgs[0]
    run.digest(None)
    assert len(nt.msgs) == 1  # isti dan ne salje ponovno
    early, nt3 = make_run(tmp_path, now=now.replace(day=24, hour=7), st=run.st)
    early.digest(None)
    assert nt3.msgs == []  # prije 9h ne salje


def test_status_change_and_sale_date(tmp_path):
    now = datetime(2026, 11, 22, 12, 0, tzinfo=TZ)
    run, nt = make_run(tmp_path, now=now)
    run.collect_new({"tickets_rs": res([ev("1", "Coldplay", venue="Maksimir", availability="InStock")])})  # baseline
    run2, nt2 = make_run(tmp_path, now=now, st=run.st)
    sale = (now + timedelta(days=3)).isoformat()
    run2.collect_new({"tickets_rs": res([ev("1", "Coldplay", venue="Maksimir", availability="SoldOut", sale_start=sale)])})
    run2.dispatch_changes()
    assert len(nt2.msgs) == 1 and "RASPRODANO" in nt2.msgs[0] and "početak prodaje" in nt2.msgs[0]
    assert "tickets_rs:1" in run2.st.reminders
    run3, nt3 = make_run(tmp_path, now=now, st=run.st)  # bez promjene -> nista
    run3.collect_new({"tickets_rs": res([ev("1", "Coldplay", venue="Maksimir", availability="SoldOut", sale_start=sale)])})
    run3.dispatch_changes()
    assert nt3.msgs == []
