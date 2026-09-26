# DAMP

obs: README claudad

Poängliga för DAMP (Datasektionens Allmänna Mötesplats för Poker, LTU).

- **Publik sida:** topplista per LP, graf över poäng över tid, sök och välj spelare, nyheter, om DAMP.
- **Admin (`/admin`):** lägg in ett bord i taget med förhandsvisning av poäng, och hantera medlemmar, LP, manuella poäng och nyheter. Alla ändringar loggas i historiken, som går att filtrera per LP.

## Så funkar det

Sidan är **helt statisk** och kostar bara domänen. Det finns ingen server och ingen databas.

```
data/*.json  ──(python -m damp.build)──▶  dist/  ──▶  Cloudflare Pages (publik sida + /admin)
     ▲                                                          │
     └──── commit via GitHub ◀── Pages Function /admin/api ◀────┘  (bakom Cloudflare Access)
```

- **All data är JSON-filer i `data/`.** Formatet beskrivs överst i [damp/store.py](damp/store.py).
- **Bygget** ([damp/build.py](damp/build.py)) validerar datan och renderar alla sidor till `dist/`. Är datan ogiltig byggs sidan inte, och den gamla ligger kvar.
- **Admin** är statisk JS ([damp/static/admin/](damp/static/admin/)). I produktion sparar den via en Cloudflare Pages Function ([functions/admin/api/\[\[path\]\].js](functions/admin/api/[[path]].js)). Funktionen committar ändringen till GitHub, och då bygger Cloudflare om sidan (ungefär en minut).
- **Inloggning** sköts av Cloudflare Access (Google, även @datasektionen.com-konton) mot en lista med tillåtna adresser. Varje ändring blir en commit, så **git-historiken är både ändringslogg och backup**.

Uppsättning: [docs/cloudflare.md](docs/cloudflare.md) (Pages, Access, domän) och [docs/github-app.md](docs/github-app.md) (nyckeln som låter admin spara).

## Kör lokalt

```bash
uv sync
uv run flask --app damp run --debug
```

Öppna http://127.0.0.1:5000. Admin finns på http://127.0.0.1:5000/admin/.

**Lokalt finns ingen inloggning.** Admin skriver då direkt till filerna i `data/` via [damp/devapi.py](damp/devapi.py), som bara finns lokalt och aldrig publiceras. Datan valideras innan något skrivs. Committa ändringarna med git som vanligt.

Bygga som i produktion:

```bash
uv run python -m damp.build          # -> dist/
python -m http.server -d dist 8000   # titta på resultatet (admin kan inte spara här)
```

## Poängsystemet

Poängen räknas i **`damp/scoring.py` → `points_for(placement, table_size, wipes)`**. Admin kör i webbläsaren, så bygget gör om funktionen till en tabell (`/admin/poang.json`). Bordseditorn tar både förhandsvisningen och de sparade poängen därifrån, så de stämmer alltid överens.

**Poängen sparas i varje bordsfil.** En ändrad funktion påverkar bara bord som sparas efter nästa deploy. Så här räknar du om gamla bord:

- Admin → LP → **Räkna om poäng**, eller
- `uv run flask --app damp recalc-points [--lp "LP1 26/27"]`

Redigerar du ett gammalt bord efter att funktionen har ändrats, varnar editorn att bordet räknas om när du sparar.

## Historik

**Varje ändring loggas**: bord, medlemmar, LP, manuella poäng och nyheter. Loggen innehåller vem, när och vad (för bord hela resultatet, för ändringar före → efter). Den sparas i `data/history/ÅÅÅÅ-MM.json` i samma commit som ändringen. Servern skriver loggen, så admins kan inte ändra eller ta bort händelser. Varje händelse vet vilka LP den rör, så historiken i admin kan filtreras per LP, inklusive när LP:t skapades. Även `import-points` och `recalc-points` loggar.

## Manuella poäng

Poäng med datum men utan placering, till exempel totaler från ett kalkylark. De räknas i topplistan och grafen, men inte som spelade bord, vinster, snitt eller wipes. Enstaka poster läggs in och ändras under Admin → Manuella poäng. Många på en gång (en fil med `namn poäng`-rader) importeras från kommandoraden:

```bash
uv run flask --app damp import-points fil.tsv --lp "LP1 26/27" --date 2026-09-22
uv run flask --app damp import-points fil.tsv --lp "LP4 25/26" --spread --seed 2526   # fiktiv kurva över LP:ets tisdagar
```

Ställningarna från innan sajten fanns (`data/*.tsv`) är redan importerade till `data/manual-points.json`.

## Slå ihop medlemmar

Visar det sig att ett smeknamn är någon i medlemslistan, flyttar `merge-members` alla bord och poäng dit, tar bort den gamla posten och behåller smeknamnet som visningsnamn. Två som suttit vid samma bord går inte att slå ihop. Ändringen loggas i historiken.

```bash
uv run flask --app damp merge-members Slalle "Nils Salomonsson"   # blir Nils "Slalle" Salomonsson
```

## Regler (kontrolleras i bygget och i admin)

- Varje bord poängsätts för sig. Spelarna står i placeringsordning, och ett bord har minst 2 spelare.
- Ett datum kan ha flera bord (`tables/2026-09-22-1.json`, `-2`, …). En medlem kan bara vara med en gång per bord, men kan spela flera bord samma dag (editorn visar det).
- Bord och manuella poäng hör till det LP vars datum de ligger inom. LP får inte överlappa.
- En medlem har förnamn, efternamn, LTU-id, medlem sedan och ett valfritt visningsnamn. Namn, LTU-id och visningsnamn är unika.
- Topplistan visar visningsnamnet, annars förnamnet (med efternamnets initial om två har samma förnamn, t.ex. "Nils S."). Klickar man på en spelare visas hela namnet: förnamn "visningsnamn" efternamn. LTU-id visas aldrig publikt.

## Struktur

```
data/                    all data (JSON), det enda admin skriver till
damp/store.py            läser och validerar data/ (dataformatet beskrivs här)
damp/scoring.py          poängfunktionen
damp/stats.py            ställning, kurvor, spelarstatistik
damp/public.py           publika sidor
damp/admin.py            admin-sidornas skal + poängtabellen
damp/devapi.py           lokalt admin-API (skriver till data/)
damp/build.py            bygger dist/
damp/history.py          ändringsloggen i data/history/ (varje sparning blir en händelse)
damp/manual.py, cli.py   import av totaler, recalc-points
damp/static/admin/       admin-JS (core.js = API, validering, hjälpfunktioner)
functions/admin/api/     Cloudflare Pages Function: admin-API:t i produktion
```

## Tester

```bash
uv run pytest
```
