# Paladex sul telefono / Paladex on the phone

## Italiano

### Che cos'è

Una **copia online di sola lettura** delle pagine di mercato di Paladex, da aprire sul telefono quando si è fuori ufficio, anche con il computer spento.

* Indirizzo: <https://paladex-pg-mobile.netlify.app> (progetto Netlify «paladex-pg-mobile»).
* È **privata**: si apre solo dopo l'accesso con l'account Netlify del titolare. Nessun altro può vederla.
* Si aggiorna **da sola ogni mattina** (la copia nuova è pronta verso le 6:30 ora italiana, le 7:30 con l'ora legale): GitHub raccoglie i dati dalle stesse fonti ufficiali del computer, prepara la copia e la pubblica. Il computer non serve.
* In cima a ogni pagina una fascia dice **fino a quando sono stati raccolti i dati** («Copia online di sola lettura · dati raccolti fino al …»). Se la copia non viene aggiornata da più di un giorno e mezzo, o se le fonti non rispondono da tre giorni, la fascia diventa gialla con un avviso.

Consiglio: sul telefono, aprire l'indirizzo e scegliere «Aggiungi a schermata Home» per averla come un'app.

### Cosa contiene e cosa no

Contiene, con gli stessi numeri e le stesse fonti del computer (fonte, data di pubblicazione, periodo per ogni dato):

* **Panoramica**, **Prezzi** (ogni tipo di prezzo; filtri per una origine, varietà, mercato, fonte o colore; dollari ed euro, periodi e frequenze per la vista principale di ogni tipo), **Notizie** (con i filtri per paese, argomento, fonte, lingua e periodo), **Paesi** e la scheda di ogni paese con dati, **Commercio internazionale** (ogni mercato; anni recenti e valore per i mercati principali), **Raccolti e produzione**, **Normative e dazi** (con lo storico dei dazi), **Fonti e qualità dati**.

Non contiene (restano solo sul computer):

* **offerte dei fornitori, avvisi, assistente IA, archivio storico**, impostazioni, chiavi di accesso, file originali scaricati: niente di privato viene mai copiato online (la preparazione della copia li toglie e controlla che nessuna chiave compaia);
* la **ricerca**, il pulsante **«Aggiorna dati»**, l'esportazione CSV, la traduzione IA su richiesta: la copia non può modificare nulla.

Una combinazione di filtri non preparata (per esempio due origini insieme, o una ricerca scritta a mano) mostra il messaggio «Questa vista non è inclusa nella copia online: è disponibile sul computer.»

### Da fare una volta sola

1. **Creare la chiave di Netlify.** Su <https://app.netlify.com>: in basso a sinistra l'icona del profilo → **User settings** → **Applications** → **Personal access tokens** → **New access token**. Nome: `Paladex GitHub`; scadenza: la più lunga disponibile (annotarla). Copiare la chiave mostrata (si vede una volta sola).
2. **Darla a GitHub.** Nel repository di Paladex su GitHub: **Settings** → **Secrets and variables** → **Actions** → **New repository secret**. Nome: `NETLIFY_AUTH_TOKEN`; valore: la chiave copiata → **Add secret**.

L'identificativo del progetto Netlify (`NETLIFY_SITE_ID`) è già scritto nel file `.github/workflows/mirror.yml`. Serve cambiarlo solo per pubblicare su un altro progetto: in quel caso aggiungere, nella stessa pagina, una **variabile** (scheda *Variables*) chiamata `NETLIFY_SITE_ID`.

Facoltativo: le chiavi gratuite delle fonti dati (le stesse del file `.env` del computer: `PALADEX_COMTRADE_API_KEY`, `PALADEX_DATA_GOV_API_KEY`, `PALADEX_USDA_NASS_API_KEY`, `PALADEX_CENSUS_API_KEY`) si possono aggiungere come altri *repository secret* con lo stesso nome: la raccolta online userà anche quelle fonti. La chiave dell'intelligenza artificiale (`PALADEX_LLM_PROVIDER` + `PALADEX_ANTHROPIC_API_KEY`) è facoltativa e a pagamento in base all'uso.

### Aggiornare subito la copia

Su GitHub: scheda **Actions** → a sinistra **Online copy (phone)** → **Run workflow** → **Run workflow**. Dopo circa un'ora (40–60 minuti) la copia è aggiornata. Nella stessa pagina si vede l'esito di ogni aggiornamento:

* segno verde, e nel riepilogo «Online copy» con la data dei dati = pubblicato (il riepilogo «Collection» dice anche quali fonti non hanno risposto);
* segno verde con l'avviso «Skipped: the repository secret NETLIFY_AUTH_TOKEN is missing…» = manca la chiave Netlify, non è stato pubblicato nulla;
* croce rossa = errore: sul telefono resta la copia precedente.

Se la chiave Netlify scade, crearne una nuova (punto 1) e sostituire il valore del secret `NETLIFY_AUTH_TOKEN` (punto 2).

### Costi

* GitHub: ogni aggiornamento usa circa 50 minuti di GitHub Actions, circa 1.550 minuti al mese (il piano gratuito di GitHub ne include 2.000 al mese per i repository privati).
* Netlify: una pubblicazione al giorno. Con i piani Netlify a crediti ogni pubblicazione costa 15 crediti, circa 450 al mese: il piano gratuito ne include 300, il piano Personal 1.000. Il piano si controlla su <https://app.netlify.com> → team → **Billing**.

---

## English

### What it is

A **read-only online copy** of Paladex's market pages, to open on the phone when away, even with the computer switched off.

* Address: <https://paladex-pg-mobile.netlify.app> (Netlify project "paladex-pg-mobile").
* It is **private**: it opens only after logging in with the owner's Netlify account. Nobody else can see it.
* It **refreshes itself every morning** (the new copy is ready around 6:30 am Italian time, 7:30 am in summer time): GitHub collects the data from the same official sources as the computer, prepares the copy and publishes it. The computer is not needed.
* A strip at the top of every page says **up to when the data was collected** ("Read-only online copy · data collected up to …"). If the copy has not been refreshed for more than a day and a half, or the sources have not answered for three days, the strip turns amber with a warning.

Tip: on the phone, open the address and choose "Add to Home Screen" to use it like an app.

### What it contains and what it does not

It contains, with the same figures and sources as the computer (source, publication date and period for every figure):

* **Overview**, **Prices** (every price type; filters by one origin, variety, market, source or colour; dollars and euros, periods and frequencies for each type's main view), **News** (with the country, topic, source, language and period filters), **Countries** and the profile of every country with data, **International trade** (every market; recent years and value for the main markets), **Harvest & production**, **Regulations & tariffs** (with duty history), **Sources & data quality**.

It does not contain (they stay on the computer only):

* **supplier quotes, alerts, AI assistant, historical archive**, settings, access keys, downloaded original files: nothing private is ever copied online (preparing the copy removes them and checks that no key appears);
* **search**, the **"Update data"** button, CSV export, on-demand AI translation: the copy cannot change anything.

A filter combination that was not prepared (for example two origins at once, or a typed search) shows "This view is not included in the online copy: it is available on the computer."

### One-time setup

1. **Create the Netlify key.** On <https://app.netlify.com>: profile icon (bottom left) → **User settings** → **Applications** → **Personal access tokens** → **New access token**. Name: `Paladex GitHub`; expiration: the longest available (note it down). Copy the key shown (it is shown only once).
2. **Give it to GitHub.** In the Paladex repository on GitHub: **Settings** → **Secrets and variables** → **Actions** → **New repository secret**. Name: `NETLIFY_AUTH_TOKEN`; value: the copied key → **Add secret**.

The Netlify project id (`NETLIFY_SITE_ID`) is already written in `.github/workflows/mirror.yml`. Change it only to publish to another project: then add, on the same page, a **variable** (*Variables* tab) named `NETLIFY_SITE_ID`.

Optional: the free data-source keys (the same as in the computer's `.env`: `PALADEX_COMTRADE_API_KEY`, `PALADEX_DATA_GOV_API_KEY`, `PALADEX_USDA_NASS_API_KEY`, `PALADEX_CENSUS_API_KEY`) can be added as further repository secrets with the same names: the online collection then uses those sources too. The AI key (`PALADEX_LLM_PROVIDER` + `PALADEX_ANTHROPIC_API_KEY`) is optional and billed by use.

### Refreshing the copy now

On GitHub: **Actions** tab → **Online copy (phone)** on the left → **Run workflow** → **Run workflow**. After about an hour (40–60 minutes) the copy is up to date. The same page shows the outcome of every refresh:

* green tick, and an "Online copy" summary with the data date = published (the "Collection" summary also lists the sources that did not answer);
* green tick with the warning "Skipped: the repository secret NETLIFY_AUTH_TOKEN is missing…" = the Netlify key is missing, nothing was published;
* red cross = error: the phone keeps the previous copy.

If the Netlify key expires, create a new one (step 1) and replace the value of the `NETLIFY_AUTH_TOKEN` secret (step 2).

### Costs

* GitHub: each refresh uses about 50 minutes of GitHub Actions, about 1,550 minutes a month (GitHub's free plan includes 2,000 a month for private repositories).
* Netlify: one deploy a day. On Netlify's credit-based plans each production deploy costs 15 credits, about 450 a month: the free plan includes 300, the Personal plan 1,000. Check the plan at <https://app.netlify.com> → team → **Billing**.

### For developers

* Build a copy from any database: `scripts/mirror/build.sh <database.sqlite3> <output-dir>` (Python with the backend requirements, Node, Playwright). Options are listed at the top of the script; `MIRROR_VERIFY=1` re-opens the finished copy and counts views it cannot answer.
* Look at it locally: `node scripts/mirror/serve.mjs <output-dir> 8790` (applies the copy's `_redirects` and `_headers` like Netlify).
* How it works: `frontend/src/lib/mirror.ts` (read-only mode, enabled only by `VITE_PALADEX_MIRROR=1`), `scripts/mirror/crawl.mjs` (records the answers of the real application), `scripts/mirror/prepare_db.py` (removes private data from the database copy), `scripts/mirror/scan_secrets.py` (refuses to publish a copy that contains a secret).
