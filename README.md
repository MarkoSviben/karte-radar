# Karte radar 🎟

Prati nove koncerte, utakmice, festivale i stand-up u **HR, RS, BiH i SLO** i javlja na **Telegram**:

- **🔥 odmah:** veliki event (stadion/arena, izvođač ili klub s tvoje liste, ključne riječi tipa "rasprodano", "dodatni koncert", "počela prodaja")
- **⏰ podsjetnik** 24 h i oko 1–2 h prije početka prodaje, kad je poznat datum prodaje
- **➕ dodatni termin** za već javljen koncert
- **☀️ jutarnji sažetak u 9:00:** manji eventi i prodaje koje kreću idućih 7 dana
- **🔄 promjena** na Eventim eventu u velikoj dvorani: rasprodano, objavljen datum prodaje, prodaja otvorena (provjera svaka ~2 h)
- **⚠️ upozorenje** kad neki izvor prestane raditi (stranica promijenila dizajn)

Radi besplatno na GitHub Actionsu, svakih 30 min danju i svaki sat noću.

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

## Postavljanje (jednom, ~10 min)

### 1. Telegram bot
1. U Telegramu otvori **@BotFather** → `/newbot` → daj ime → dobiješ **token** (npr. `123456:ABC...`).
2. Otvori svog novog bota i pošalji mu bilo koju poruku (npr. "bok").
3. U browseru otvori `https://api.telegram.org/bot<TOKEN>/getUpdates` i nađi `"chat":{"id": 123456789`. To je tvoj **chat_id**.
   - Za grupu: dodaj bota u grupu, pošalji poruku u grupi; chat_id grupe počinje s `-`.
   - Više primatelja: `TELEGRAM_CHAT_ID` = `id1,id2`.

### 2. GitHub repo (privatni!)
```bash
cd Karte
git init -b main
git add .
git commit -m "Karte radar"
gh repo create karte-radar --private --source . --push
```

### 3. Secrets
Na GitHubu: **Settings → Secrets and variables → Actions → New repository secret**
- `TELEGRAM_BOT_TOKEN`: token od BotFathera
- `TELEGRAM_CHAT_ID`: tvoj chat_id
- `BANDSINTOWN_APP_ID` (opcionalno): zatraži na https://help.artists.bandsintown.com (API za partnere)

Ili iz terminala: `gh secret set TELEGRAM_BOT_TOKEN` i `gh secret set TELEGRAM_CHAT_ID`.

### 4. Prvo pokretanje
**Actions → radar → Run workflow.** Prvi run samo zapamti sve postojeće evente (~7000) i pošalje poruku "Karte radar je pokrenut". Od tada javlja samo **nove** stvari.

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
$env:TELEGRAM_BOT_TOKEN="..."; $env:TELEGRAM_CHAT_ID="..."; .venv\Scripts\python -m radar test-telegram
```

## Potrošnja GitHub minuta
Oko 42 runa dnevno, svaki traje manje od minute, pa je to ~1300 od 2000 besplatnih minuta mjesečno za privatni repo. Za češće provjere promijeni `cron` u [.github/workflows/radar.yml](.github/workflows/radar.yml), ali pazi na limit.

## Kad nešto pukne
- Dobiješ **⚠️ Izvor X ne radi** → stranica je promijenila HTML. Parser je u `radar/sources/<izvor>.py`; `python -m radar check --only <izvor>` pokazuje što vidi.
- Dobiješ **❌ run je pao** → link vodi na log u GitHub Actionsu.
- Stanje (što je već viđeno) je na grani `state`. Ako je obrišeš, idući run ponovno radi baseline (bez spama).
