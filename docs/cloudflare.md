# Publicera sidan på Cloudflare

Sidan körs gratis på **Cloudflare Pages**. Adminen skyddas av **Cloudflare Access** (inloggning med Google-konto eller e-postkod), och det enda som kostar är domänen. Görs en gång och tar ungefär 30 minuter.

Du behöver först:

- **DAMP-organisationen på GitHub med repon** (steg 0 i [github-app.md](github-app.md)).
- **Ett Cloudflare-konto** (gratis, på dash.cloudflare.com).

## 1. Pages-projektet

Cloudflare → **Workers & Pages** → **Create** → fliken **Pages** → **Connect to Git**.

1. Koppla GitHub och ge Cloudflare tillgång till organisationen, helst **bara `damp`-repon**.
2. Välj repon och fyll i:

| Fält | Värde |
|---|---|
| Project name | `damp` (sidan hamnar på `damp.pages.dev`, eller ett annat namn om det är upptaget) |
| Production branch | `master` |
| Framework preset | None |
| Build command | `pip install uv && uv run --frozen python -m damp.build` |
| Build output directory | `dist` |

3. Tryck **Save and Deploy**. Bygget tar någon minut. Mappen `functions/` (admin-API:t) upptäcks automatiskt.
4. Öppna `https://damp.pages.dev`. Topplistan ska synas. `/admin` fungerar först efter steg 2–4.

Om bygget klagar på Python eller pip: lägg till miljövariabeln `PYTHON_VERSION` = `3.12` under Settings → Variables and Secrets och bygg om.

## 2. Inloggning (Cloudflare Access)

Cloudflare → **Zero Trust**. Första gången väljer du ett **team-namn**, till exempel `damp`. Då blir team-domänen `damp.cloudflareaccess.com`. Välj planen **Free** (upp till 50 användare). Cloudflare kan be om kortuppgifter även för gratisplanen.

### Inloggningssätt

Under **Settings → Authentication → Login methods**:

- **One-time PIN** är på från början. Man skriver in sin e-post och får en kod. Det fungerar direkt för alla adresser, även `@datasektionen.com`, utan mer inställningar.
- **Google** (valfritt, "Logga in med Google"-knapp): **Add new → Google**. Du behöver en OAuth-klient från Google Cloud Console (APIs & Services → Credentials → Create OAuth client ID → Web application) med
  - Authorized JavaScript origins: `https://damp.cloudflareaccess.com`
  - Authorized redirect URIs: `https://damp.cloudflareaccess.com/cdn-cgi/access/callback`

  Klistra in Client ID och Client secret i Cloudflare och tryck **Test**.

### Access-applikationen

**Access → Applications → Add an application → Self-hosted**:

| Fält | Värde |
|---|---|
| Application name | `DAMP admin` |
| Session duration | t.ex. `1 week` (hur ofta man måste logga in igen) |
| Domain | `damp.pages.dev`, path `admin` |

Lägg till en policy: **Action: Allow**, **Include → Emails**:

```
nilsalomonsson@gmail.com
damp-info@datasektionen.com
```

Spara. Öppna sedan applikationen igen och kopiera **Application Audience (AUD) Tag** från översikten. Den behövs i steg 3.

## 3. Inställningar i Pages-projektet

Pages-projektet → **Settings → Variables and Secrets → Production → Add**:

| Namn | Värde | Typ |
|---|---|---|
| `ACCESS_TEAM_DOMAIN` | `damp.cloudflareaccess.com` | Text |
| `ACCESS_AUD` | AUD-taggen från steg 2 | Text |
| `ADMIN_EMAILS` | `nilsalomonsson@gmail.com,damp-info@datasektionen.com` | Text |

Lägg också till GitHub-värdena från [github-app.md](github-app.md), steg 5 (`GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_REPO`, `GITHUB_BRANCH`).

**Variablerna börjar gälla vid nästa deploy.** Gå till Deployments → senaste → **Retry deployment**.

## 4. Testa

1. Öppna `https://damp.pages.dev/admin/`. Du ska hamna på Cloudflares inloggning, sedan i admin med "Inloggad som …" uppe till höger.
2. Skapa en testnyhet under Nyheter. På GitHub ska en commit dyka upp, och efter ungefär en minut syns nyheten på sidan.
3. Radera testnyheten.

## 5. Domän

Välj ett av alternativen. Lägg sedan till samma domän med path `admin` i Access-applikationen (steg 2), annars är adminen oskyddad där. API:t vägrar ändå utan giltig inloggning.

- **damp.se (egen domän, ca 100–250 kr/år):** köp den hos en registrar. Pages-projektet → **Custom domains → Set up a custom domain → `damp.se`**. För en toppdomän vill Cloudflare att domänens nameservers pekar på Cloudflare. Följ instruktionerna och byt nameservers hos registraren. HTTPS ordnas automatiskt.
- **damp.datasektionen.com (gratis):** be den som sköter datasektionen.com (DNS ligger hos LUDD) lägga till en CNAME-post `damp` → `damp.pages.dev`. Lägg sedan till `damp.datasektionen.com` under Custom domains i Pages. (En sökväg som datasektionen.com/damp fungerar inte utan en proxy hos LUDD.)

## Underhåll

- **Lägga till eller ta bort en admin:** ändra **både** Access-policyn (steg 2) **och** `ADMIN_EMAILS` (steg 3, sedan redeploy). Access stoppar obehöriga vid dörren, och funktionen kontrollerar listan en gång till innan något sparas.
- **Få veta när ett bygge misslyckas:** Cloudflare → **Notifications → Add** → Pages → deployment-aviseringar till din e-post. Ett misslyckat bygge betyder oftast ogiltig data, och byggloggen (Pages → Deployments → bygget) listar exakt vad som är fel. Den gamla sidan ligger kvar tills det är rättat.
- **Felmeddelanden i admin:**
  - "Admin är inte färdigkonfigurerad. Saknar: X": variabeln X saknas i steg 3 (glöm inte redeploy).
  - "… har inte behörighet": adressen finns inte i `ADMIN_EMAILS`.
  - "Du är utloggad": sessionen har gått ut, så ladda om sidan.
