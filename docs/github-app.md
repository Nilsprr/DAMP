# Sätta upp GitHub-appen (nyckeln som låter admin spara)

Admin-sidan sparar ändringar (bord, medlemmar, LP, nyheter) genom att en Cloudflare-funktion committar till GitHub-repon. Funktionen loggar in som en **GitHub App**: en robotanvändare som tillhör DAMP-organisationen, inte en person. Den får bara läsa och skriva filer i DAMP-repon, och ingen nyckel går ut.

Görs en gång och tar ungefär 10 minuter. Exemplen använder organisationen `damp-ltu` och repon `damp`. Byt ut dem mot era riktiga namn.

## 0. Förutsättningar

- **En GitHub-organisation** med repon i. Saknas den: github.com → **+** (uppe till höger) → **New organization** → **Free**.
  - Lägg till minst en person till som **Owner** (Settings → People), så att inget hänger på en enda person.
  - Rekommenderat: Settings → **Authentication security** → **Require two-factor authentication**.
- **Repon ligger i organisationen och är privat.** Skapa `damp-ltu/damp` som **Private** (utan README), och pusha sedan från datorn:
  ```bash
  git remote add origin git@github.com:damp-ltu/damp.git
  git push -u origin master
  ```
- **Du måste vara Owner i organisationen** för att kunna skapa appen.

## 1. Skapa appen

Gå till `https://github.com/organizations/damp-ltu/settings/apps/new`, eller: organisationen → **Settings** → längst ner i vänstermenyn **Developer settings** → **GitHub Apps** → **New GitHub App**.

Fyll i:

| Fält | Värde |
|---|---|
| GitHub App name | `damp-ltu-admin` (namnet måste vara unikt på hela GitHub, så lägg till något om det är upptaget) |
| Homepage URL | `https://github.com/damp-ltu/damp` (krävs men används inte) |
| Callback URL | lämna tomt |
| Request user authorization (OAuth) during installation | **av** |
| Webhook → Active | **bocka ur** |

Under **Permissions → Repository permissions**:

| Behörighet | Nivå |
|---|---|
| **Contents** | **Read and write** |
| Metadata | Read-only (sätts automatiskt) |
| allt annat | No access |

Under **Where can this GitHub App be installed?**: **Only on this account**.

Tryck **Create GitHub App**.

## 2. Anteckna App ID

Du hamnar på appens sida. Överst under **About** står **App ID**, ett tal som `1234567`. Skriv upp det. (Client ID behövs inte.)

## 3. Skapa den privata nyckeln

Längre ner på samma sida, under **Private keys** → **Generate a private key**. En fil laddas ner, till exempel `damp-ltu-admin.2026-09-23.private-key.pem`.

**Behandla filen som ett lösenord.** Den som har den kan skriva i repon. Lägg den inte i repon, och skicka den inte i chatt eller mejl.

Filen kan användas precis som den är. Du behöver inte konvertera den.

## 4. Installera appen på repon

I vänstermenyn på appens sida: **Install App** → **Install** bredvid `damp-ltu` → välj **Only select repositories** → välj `damp` → **Install**.

Efter installationen ser adressen ut ungefär så här:

```
https://github.com/organizations/damp-ltu/settings/installations/87654321
```

**Talet på slutet är Installation ID.** Skriv upp det.

## 5. Lägg in värdena i Cloudflare

Det här steget görs när Cloudflare Pages-projektet finns (se [cloudflare.md](cloudflare.md)). Pages-projektet → **Settings** → **Variables and Secrets** → **Production** → **Add**:

| Namn | Värde | Typ |
|---|---|---|
| `GITHUB_APP_ID` | App ID från steg 2 | Text |
| `GITHUB_APP_INSTALLATION_ID` | Installation ID från steg 4 | Text |
| `GITHUB_APP_PRIVATE_KEY` | **hela innehållet** i `.pem`-filen, inklusive raderna `-----BEGIN …-----` och `-----END …-----` | **Secret** |
| `GITHUB_REPO` | `damp-ltu/damp` | Text |
| `GITHUB_BRANCH` | `master` | Text |

Spara. **Variablerna börjar gälla vid nästa deploy.** Gå till **Deployments**, välj senaste och kör **Retry deployment**, eller pusha en commit.

Lägg sedan `.pem`-filen i en lösenordshanterare eller radera den. Behövs den igen kan du alltid skapa en ny (se nedan).

## 6. Testa

Öppna `/admin`, logga in och gör en liten ändring, till exempel en nyhet. På GitHub under **Commits** ska en ny commit synas från `damp-ltu-admin[bot]`, med din e-post som författare. Någon minut senare har Cloudflare byggt om sidan.

## Underhåll

- **Byta nyckel** (en gång om året, eller om den kan ha läckt): appens sida → **Generate a private key** → byt värdet på `GITHUB_APP_PRIVATE_KEY` i Cloudflare → redeploy → **Delete** på den gamla nyckeln. **En raderad nyckel slutar gälla direkt.**
- **Överlämning till nästa styrelse:** gör dem till **Owner** i organisationen. Appen tillhör organisationen, så inget annat behöver ändras. Admins för sidan styrs separat, i Cloudflare Access.
- **Skydda inte `master` med "Require a pull request before merging".** Då kan appen inte spara. Vill ni ha branch protection, lägg appen i listan över dem som får kringgå reglerna ("bypass list").
- **Vad nyckeln kan göra:** läsa och skriva filer i `damp-ltu/damp`, och inget annat. Den kan inte ändra inställningar, radera repon eller se andra repon. Funktionen skriver bara i `data/`, men nyckeln i sig kan skriva i hela repon, så håll den hemlig.
