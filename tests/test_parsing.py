from radar.jsonld import parse_events
from radar.sources.eventim import is_bot_check, split_slug
from radar.sources.gigstix import parse_slug
from radar.sources.kupikartu_ba import parse as parse_kupikartu
from radar.sources.news import parse_listing_title
from radar.sources.tickets_rs import parse as parse_tickets
from radar.sources.ulaznice_hr import parse as parse_ulaznice
from radar.textnorm import Phrase, norm, similar, tokens

EVENTIM_LD = """<html><script type="application/ld+json">{"@context":"https://schema.org","@type":"MusicEvent",
"startDate":"2028-03-10T20:00:00.000+01:00","name":"Psihomodo Pop @ Arena Zagreb",
"location":{"@type":"EventVenue","name":"Arena Zagreb","address":{"addressLocality":"Zagreb","addressCountry":"HR"}},
"offers":[{"@type":"AggregateOffer","lowPrice":"27.50","priceCurrency":"EUR","availability":"https://schema.org/PreSale",
"validFrom":"2026-11-25T10:00:00.000+01:00"}]}</script></html>"""


def test_norm_and_cyrillic():
    assert norm("Đorđe Balašević") == "djordje balasevic"
    assert norm("Ђорђе Балашевић") == "djordje balasevic"
    assert norm("ŠTARK ARENA!") == "stark arena"


def test_phrase_cases():
    assert Phrase("Dino Merlin").found_in(tokens("Novi koncert Dina Merlina u Zagrebu"))
    assert Phrase("Sting").found_in(tokens("Počela prodaja karata za Stingov koncert"))
    assert Phrase("Arena Zagreb").found_in(tokens("u Areni Zagreb"))
    assert not Phrase("Dino Merlin").found_in(tokens("Dinamo Merlin"))  # oba tokena moraju pasati
    assert Phrase("=Rasta").found_in(tokens("Rasta nastupa"))
    assert not Phrase("=Rasta").found_in(tokens("cijene rastu"))


def test_similar():
    assert similar("Bryan Adams @ Stožice", "BRYAN ADAMS @ Stozice") == 1.0
    assert similar("Coldplay Zagreb", "Severina Split") < 0.5


def test_jsonld():
    j = parse_events(EVENTIM_LD)[0]
    assert j["venue"] == "Arena Zagreb" and j["country"] == "HR"
    assert j["sale_start"].startswith("2026-11-25") and j["availability"] == "PreSale"
    assert j["price"] == "od 27.5 EUR"


def test_eventim_slug_split():
    venues = {"arena-zagreb": ("zagreb", "Arena zagreb", "u1"), "zagreb": ("zagreb", "Zagreb", "u2")}
    t, v, c, cs = split_slug("psihomodo-pop-arena-zagreb-arena-zagreb", venues)
    assert (t, v, c) == ("Psihomodo pop arena zagreb", "Arena zagreb", "Zagreb")
    assert is_bot_check('<html><div id="sec-if-cpt-container">Akamai</div></html>')


def test_gigstix_slug():
    assert parse_slug("negitiv-beograd-27-novembar-2026") == ("Negitiv", "Beograd", "27 novembar 2026")
    assert parse_slug("zoster-novi-sad-28-novembar-2026")[1] == "Novi Sad"


def test_google_news_listing_title():
    d = parse_listing_title("Ulaznice za ŽENOMRZAC U TUZLI, Bosanski kulturni centar TK, Tuzla Grad | Subota, 16.01.2027., 20:00h")
    assert d == {"title": "ŽENOMRZAC U TUZLI", "venue": "Bosanski kulturni centar TK", "city": "Tuzla Grad",
                 "date": "16.01.2027 20:00"}
    assert parse_listing_title("Počela prodaja karata za koncert") is None


def test_tickets_rs():
    html = """<a href="/tour/nazareth_2873"><div class="event-meta"><h3> Nazareth </h3>
    <div class="date-time">&nbsp;20 December 2026 &nbsp;</div><div class="place">&nbsp;mts dvorana, Belgrade&nbsp;</div>
    <div class="price">&nbsp;od &nbsp;3.500,00&nbsp;</div></div></a><a href="/tour/nazareth_2873">dup</a>"""
    [e] = parse_tickets(html, "https://tickets.rs/", "tickets_rs", "RS")
    assert (e.uid, e.title, e.venue, e.city, e.date) == ("tour:2873", "Nazareth", "mts dvorana", "Belgrade", "20 December 2026")


def test_ulaznice():
    html = """<article class="happeningContainer"><div class="happeningInfoContainer"><h3 class="smallTitle">
    <a href="/web/event/38/13800">Mistero buffo</a></h3><p><span>KunstTeatar &nbsp;</span>
    <span class="wrc-bold"> 27.11.2026. u 20:00 </span></p><p> Slobodna mjesta: <b>36</b> <br>
    Cijena ulaznica: <b class="priceWidth">12 €</b></p></div></article>"""
    [e] = parse_ulaznice(html, "https://www.ulaznice.hr/web/events", "ulaznice_hr", "HR")
    assert (e.uid, e.title, e.venue, e.date, e.price) == ("38/13800", "Mistero buffo", "KunstTeatar", "27.11.2026. u 20:00", "12 €")
    assert e.extra["free_seats"] == 36


def test_kupikartu():
    html = """<a class="item" href="/karte/event/7833/nova-godina"><div class="caption"><div class="date">12.12.2026</div>
    <div class="name">NOVA GODINA</div><div class="location">@ RKUD Proleter - Sarajevo City Centar</div></div></a>"""
    [e] = parse_kupikartu(html, "https://www.kupikartu.ba/", "kupikartu_ba", "BA")
    assert (e.title, e.venue, e.city, e.date) == ("NOVA GODINA", "RKUD Proleter", "Sarajevo City Centar", "12.12.2026")


def test_eventim_cards():
    from radar.sources.eventim import parse_cards
    html = """<article class="listing-item event-listing-item list-element" data-availability-indicator="1">
    <div onclick="setTimeout(function(){location.href='/event/magnifico-dvorana-stozice-21779046/';},0);"
    data-teaser-name="Bo&amp;amp;i&#269; Magnifico"><time datetime="2026-12-25T20:00:00.000+01:00"></time>
    <span>od <span class="js-tooltipster">€ 44,00*</span></span></div></article>
    <article class="listing-item event-listing-item list-element" data-availability-indicator="-1">
    <a href="/event/avsenik-dvorana-stozice-21096507/">x</a><h2>Avsenik</h2><span>Ni na voljo</span></article>"""
    a, b = parse_cards(html)
    assert (a["availability"], a["start"][:10], a["price"]) == ("LimitedAvailability", "2026-12-25", "od € 44,00")
    assert a["name"] == "Bo&ič Magnifico" and a["url"].endswith("21779046/")
    assert (b["availability"], b["name"]) == ("OutOfStock", "Avsenik")
