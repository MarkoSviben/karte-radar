# Karte radar 🎟

Prati nove koncerte, utakmice, festivale i stand-up u **HR, RS, BiH i SLO** i šalje obavijesti na tvoju **privatnu ntfy stranicu** (`https://ntfy.sh/<tajno-ime>`). Otvoriš je u browseru ili u ntfy aplikaciji na mobitelu i poruke stižu uživo. Telegram je opcija.

- **🔥 odmah:** veliki event (stadion/arena, izvođač ili klub s tvoje liste, ključne riječi tipa "rasprodano", "dodatni koncert", "počela prodaja")
- **⏰ podsjetnik** 24 h i oko 1–2 h prije početka prodaje, kad je poznat datum prodaje
- **➕ dodatni termin** za već javljen koncert
- **☀️ jutarnji sažetak u 9:00:** manji eventi i prodaje koje kreću idućih 7 dana
- **🔄 promjena** na Eventim eventu u velikoj dvorani: rasprodano, objavljen datum prodaje, prodaja otvorena (provjera svaka ~2 h)
- **⚠️ upozorenje** kad neki izvor prestane raditi (stranica promijenila dizajn)

Radi besplatno na GitHub Actionsu, svakih 30 min danju i svaki sat noću.

## Pregledna stranica

**https://markosviben.github.io/karte-pregled/** prikazuje sve evente koji su trenutno u prodaji, s filterima po državi, mjesecu i statusu te pretragom. Osvježava se svakim runom.
- Stranica i njezini podaci (`data.json`) su u **javnom** repou `karte-pregled`. Tamo su samo javni podaci o eventima, bez koda, watchliste i ntfy imena.
- Radar u taj repo piše preko deploy ključa (secret `PAGES_DEPLOY_KEY`), koji smije pisati samo u njega.
- Izgled stranice je u [site/index.html](site/index.html).

## Izvori

| Izvor | Kako | Što daje |
|---|---|---|
| Eventim HR / SI | javni sitemap + javne stranice dvorana | novi eventi, **nove stranice izvođača** (često prije eventa), datum, **početak prodaje**, status (rasprodano...) i cijena |
| tickets.rs | početna stranica | eventi u Srbiji |
| Gigs Tix | sitemap | eventi u Srbiji/CG |
| ulaznice.hr | lista evenata | HR eventi, klubovi |
| kupikartu.ba | početna stranica | BiH eventi |
| mojekarte.si | sitemap | SLO eventi |
| Google News | 20 pretraga | **Entrio** eventi (Google ih indeksira), najave, klubovi, dvorane |
| 11 portala (RSS) | Index, 24sata, Večernji, tportal, Blic, Kurir, Telegraf, Klix, Avaz, 24ur, RTV SLO | najave koncerata i prodaje |
| Bandsintown | API (opcionalno) | turneje stranih izvođača u regiji |

**Napomena:** Entrio i stranice pojedinih eventa na Eventimu imaju anti-bot zaštitu (Cloudflare/Akamai). Radar je **ne zaobilazi**. Entrio prati preko Google Newsa. Za Eventim čita javni sitemap i javne stranice dvorana, koje sadrže sve detalje: polako, jednu po jednu, i staje na prvu bot-provjeru. Detalji (datum prodaje, status) postoje za evente u dvoranama koje Eventim ima u sitemapu. Za ostale stiže samo naslov, dvorana i grad. Radar ništa ne kupuje, samo javlja.

## Postavljanje

Repo i tajno ime stranice (GitHub secret `NTFY_TOPIC`) su već postavljeni. Tebi ostaje:

1. Otvori svoju stranicu `https://ntfy.sh/<NTFY_TOPIC>` (link je u poruci od Claudea) i spremi je u bookmarke.
   - Na mobitelu: instaliraj aplikaciju **ntfy** (Android/iOS) → **+** → upiši isto tajno ime, pa dobivaš push obavijesti.
   - U browseru klikni na zvonce, pa dobivaš obavijesti na desktopu.
2. Tajno ime čuvaj kao lozinku: tko ga zna, može čitati poruke.
3. ntfy.sh čuva poruke 12 sati. Stranica i aplikacija ih poslije pamte lokalno, ali samo dok su pretplaćene na temu.

Ručno pokretanje: `gh workflow run radar`, ili na webu **Actions → radar → Run workflow**.

**Telegram (opcionalno, umjesto ntfy ili uz njega):** kod @BotFather napravi bota, pa postavi `gh secret set TELEGRAM_BOT_TOKEN` i `gh secret set TELEGRAM_CHAT_ID`.

**Bandsintown (opcionalno):** `gh secret set BANDSINTOWN_APP_ID`.

## Prilagodba

Sve se uređuje direktno na GitHubu (ikona olovke), bez programiranja:

- **[config/watchlist.yaml](config/watchlist.yaml):** izvođači, klubovi, dvorane, ključne riječi, pragovi bodova
  - `threshold_instant: 50`: od koliko bodova ide odmah. Ako stiže previše poruka, podigni na 60–70.
  - Dodaj izvođača: `- "Ime Izvođača|Alternativno ime"`, ili s posebnom težinom `- {"Coldplay": 95}`
- **[config/sources.yaml](config/sources.yaml):** izvori, Google News pretrage, RSS portali (`enabled: false` gasi izvor)

## Lokalno (Windows)

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt pytest
.venv\Scripts\python -m radar check                  # što svaki izvor trenutno vidi + bodovi
.venv\Scripts\python -m radar scan --dry-run --show-all   # sve tretira kao novo, ispiše top 40
.venv\Scripts\python -m pytest -q                    # testovi
$env:NTFY_TOPIC="..."; .venv\Scripts\python -m radar test-notify
```

## Potrošnja GitHub minuta
Oko 42 runa dnevno, svaki traje manje od minute, pa je to ~1300 od 2000 besplatnih minuta mjesečno za privatni repo. Za češće provjere promijeni `cron` u [.github/workflows/radar.yml](.github/workflows/radar.yml), ali pazi na limit.

## Kad nešto pukne
- Dobiješ **⚠️ Izvor X ne radi** → stranica je promijenila HTML. Parser je u `radar/sources/<izvor>.py`; `python -m radar check --only <izvor>` pokazuje što vidi.
- Dobiješ **❌ run je pao** → link vodi na log u GitHub Actionsu.
- Stanje (što je već viđeno) je na grani `state`. Ako je obrišeš, idući run ponovno radi baseline (bez spama).
