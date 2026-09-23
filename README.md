# DAMP

Poängliga och medlemsregister för DAMP (Datasektionens Allmänna Mötesplats för Poker, LTU).

- **Publik sida** (ingen inloggning, bara läsning): topplista per LP, graf över poäng över tid, sök och välj spelare, nyheter, om DAMP.
- **Admin** (`/admin`, lösenord + TOTP): lägg in kvällar bord för bord med förhandsvisning av poäng, hantera medlemmar och betalningar, LP, nyheter, ändringslogg.

Flask + Jinja + SQLite, med vanilla JS och Chart.js (vendorad, inget byggsteg).

## Kom igång

```bash
uv sync
uv run flask --app damp db upgrade          # skapar instance/damp.db
uv run flask --app damp create-admin nils   # frågar efter lösenord (minst 12 tecken)
uv run flask --app damp run --debug
```

Öppna http://127.0.0.1:5000 och sedan `/admin/login`. Första inloggningen visar en QR-kod att skanna med en autentiseringsapp.

### Befintliga poäng (från kalkylarket)

`data/` innehåller ställningarna som fanns innan sajten. Skapa LP:na under Admin → LP och importera sedan:

```bash
uv run flask --app damp import-points data/lp1-26-27.tsv --lp "LP1 26/27" --date 2026-09-22
uv run flask --app damp import-points data/lp4-25-26.tsv --lp "LP4 25/26" --spread --seed 2526
```

Filerna har en rad per spelare, `namn<TAB>poäng`, precis som när man kopierar två kolumner från ett kalkylark (decimalkomma går bra). Poängen blir *manuella poäng*: de har ett datum men ingen placering. De räknas i topplistan, grafen och antal spelade kvällar, men inte i vinster, snitt eller wipes. Namn som inte finns bland medlemmarna läggs till som nya medlemmar, utan startdatum och utan betalning.

`--spread` hittar på en kurva: varje total fördelas slumpmässigt över LP:ets tisdagar. Bara totalen är riktig. Enskilda poster kan rättas eller tas bort under Admin → LP → Manuella poäng.

## Ändra poängsystemet

Poängen räknas i **`damp/scoring.py` → `points_for(placement, table_size, wipes)`**. Admin-förhandsvisningen och commit anropar samma funktion.

Poängen sparas på varje resultat när kvällen committas, och decimaler (t.ex. 14,5) går bra. Efter en ändring i funktionen, räkna om gamla resultat:

- Admin → LP → **Räkna om poäng**, eller
- `uv run flask --app damp recalc-points` (alla LP), `--lp <id>` för ett LP.

## Admin-CLI

| Kommando | Vad |
|---|---|
| `create-admin <namn>` | Nytt adminkonto (inga konton kan skapas via webben) |
| `set-password <namn>` | Byt lösenord |
| `reset-totp <namn>` | Tappad telefon: ny QR-kod vid nästa inloggning |
| `delete-admin <namn>` | Ta bort konto |
| `list-admins` | Lista konton |
| `recalc-points [--lp id]` | Räkna om poäng med nuvarande `points_for` (manuella poäng påverkas inte) |
| `import-points FIL --lp "LP1 26/27" (--date D \| --spread) [--replace]` | Importera `namn poäng`-rader som manuella poäng |

Alla körs som `uv run flask --app damp <kommando>`.

## Regler i koden

- Medlemskap gäller 1 år (eller N år) från betalningsdagen. Betalar man i förtid läggs tiden på slutet. Logik: `damp/membership.py`.
- En spelare måste ha aktivt medlemskap **på kvällens datum** för att kunna läggas till. Utgångna medlemmar kan förnyas direkt i kvällseditorn ("Förnya nu").
- Varje bord poängsätts för sig. En medlem kan bara vara med vid ett bord per kväll, och det kan bara finnas en kväll per datum.
- Den publika sidan visar visningsnamn (eller namn), aldrig LTU-id.

## Struktur

```
damp/scoring.py      poängfunktionen
damp/membership.py   medlemskapsperioder
damp/nights.py       validering + sparande av kvällar
damp/manual.py       manuella poäng: tolka inklistrade listor, import, --spread
damp/stats.py        ställning, kurvor, spelarstatistik
damp/public.py       publika sidor (endast GET)
damp/admin/          inloggning, adminsidor, JSON-API för kvällseditorn
damp/static/css/themes.css   färgtemana DATA / AI SLOP / DARK
migrations/          Alembic (flask db migrate / upgrade)
data/                poäng från innan sajten fanns (för import-points)
```

## Tester

```bash
uv run pytest
```

## Inför lansering (inte gjort än)

- Sätt `DAMP_ENV=production`, `DAMP_SECRET_KEY=<lång slumpsträng>` och `DAMP_SECURE_COOKIES=1`. Appen vägrar starta i produktion med dev-nyckeln.
- Kör med gunicorn bakom en HTTPS-proxy (t.ex. Caddy), på en server med beständig disk för `instance/damp.db`, och säkerhetskopiera filen regelbundet.
- Login-spärren (Flask-Limiter) sparar räknare i minnet, vilket räcker för en process. Använd Redis om ni kör flera workers.
