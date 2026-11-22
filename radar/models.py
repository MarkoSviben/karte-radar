from __future__ import annotations

from dataclasses import asdict, dataclass, field

# kind:
#   "listing" - event na ticketing stranici (moze se kupiti / uskoro u prodaji)
#   "news"    - clanak / najava (portal, Google News)
#   "artist"  - nova stranica izvodjaca na ticketing stranici (rani signal)
#   "tour"    - najava turneje (Bandsintown)


@dataclass
class Event:
    source: str
    uid: str
    title: str
    url: str
    kind: str = "listing"
    venue: str = ""
    city: str = ""
    country: str = ""  # HR / RS / BA / SI / ME ...
    date: str = ""  # human readable datum eventa
    start: str = ""  # ISO datum/vrijeme eventa ako je poznat
    sale_start: str = ""  # ISO pocetak prodaje ako je poznat
    availability: str = ""  # InStock / PreSale / SoldOut ...
    price: str = ""
    summary: str = ""
    extra: dict = field(default_factory=dict)

    # popunjava scoring
    score: int = 0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.uid}"
