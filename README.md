# Parodi Group — Honey Intelligence (Paladex)

A private, local intelligence platform for the global honey market: prices, international trade, production, news, and official reports and regulations, collected automatically from official sources and kept with their full history.

> **Italiano più sotto.** The application interface is in Italian by default, with English available.

---

## Italiano — Guida rapida

### Cosa fa

* Raccoglie automaticamente dati ufficiali e notizie sul miele: USDA e US Census (USA), Commissione Europea / Eurostat, Osservatorio Nazionale Miele e listini delle Camere di Commercio, Regno Unito (HMRC), UN Comtrade, FAO, fonti ufficiali dei paesi d'origine (Brasile, Argentina, Uruguay, Cile, Messico, Ucraina, Turchia, Canada, India), dazi UE e USA, meteo NASA delle zone di produzione, cambi BCE e notizie di settore.
* Salva tutto sul computer, senza mai cancellare lo storico. Funziona anche senza internet, con i dati già salvati.
* Ogni numero mostra la fonte, la data di pubblicazione, il periodo e il tipo (all'ingrosso, al produttore, valore doganale…). Nessun dato viene inventato. Quando un dato manca, l'applicazione lo dice.

### Installazione (una sola volta)

1. Installare **Python 3.11 o superiore** (l'interfaccia è già inclusa: Node.js non serve) da <https://www.python.org/downloads/>. Su Windows, durante l'installazione spuntare **"Add Python to PATH"**.
2. Copiare la cartella `paladex` sul computer, per esempio in `Documenti`.
3. *(Facoltativo)* Aprire il file `.env` con il Blocco note e inserire le chiavi gratuite delle fonti dati e, se si desidera, la chiave dell'intelligenza artificiale (vedere più sotto). Al primo avvio il file `.env` viene creato automaticamente da `.env.example`.

### Avvio di tutti i giorni

* **Windows:** doppio clic su **`Avvia Paladex.bat`**.
* **Mac:** doppio clic su **`Avvia Paladex.command`**.

Il primo avvio richiede qualche minuto (installazione). Poi il browser si apre da solo su <http://127.0.0.1:8765> e mostra **subito i dati reali** già raccolti dalle fonti ufficiali, inclusi nel programma (cartella `starter/`, con la data di raccolta indicata in alto). Intanto Paladex ricontrolla tutte le fonti da questo computer: la prima volta servono circa 30–40 minuti in background, e i dati più recenti compaiono man mano. Per chiudere l'applicazione basta chiudere la finestra che si è aperta all'avvio (su Windows è nera). Se Paladex è già aperto, un nuovo doppio clic su **Avvia Paladex** apre soltanto il browser.

I dati si aggiornano da soli mentre l'applicazione è aperta, e all'avvio se l'ultimo aggiornamento risale a più di 6 ore prima. Il pulsante **"Aggiorna dati"** in alto aggiorna tutto subito. La pagina **Fonti e qualità dati** mostra, per ogni fonte, quando è stata controllata e se ci sono problemi.

### Chiavi gratuite (consigliate)

| Chiave nel file `.env` | A cosa serve | Dove ottenerla (gratis) |
|---|---|---|
| `PALADEX_COMTRADE_API_KEY` | Commercio mondiale del miele (HS 0409), dati mensili | <https://comtradedeveloper.un.org> → iscriversi al prodotto "comtrade - v1" |
| `PALADEX_DATA_GOV_API_KEY` | Importazioni USA di miele per origine (USDA FAS / Census) | <https://api.data.gov/signup/> |
| `PALADEX_USDA_NASS_API_KEY` | Produzione e prezzi del miele negli USA (USDA NASS) | <https://quickstats.nass.usda.gov/api> |
| `PALADEX_CENSUS_API_KEY` *(facoltativa)* | Importazioni USA dal Census Bureau (funziona anche senza chiave, con limite giornaliero) | <https://api.census.gov/data/key_signup.html> |
| `PALADEX_FAOSTAT_USERNAME` / `PASSWORD` *(facoltativi)* | FAOSTAT via API e flussi bilaterali (senza account si usano i file pubblici) | <https://www.fao.org/faostat/en/#developer> |
| `PALADEX_LLM_PROVIDER` + `PALADEX_ANTHROPIC_API_KEY` (oppure `PALADEX_OPENAI_API_KEY`) | Riassunti e traduzioni delle notizie, assistente IA e sintesi giornaliera | console.anthropic.com oppure platform.openai.com (a pagamento, in base all'uso) |

Facoltativo: per leggere il prezzo minimo all'export del miele indiano (avvisi DGFT scansionati) installare il programma gratuito **Tesseract OCR** (Windows: installer «UB Mannheim», nella cartella che propone; Mac: `brew install tesseract`).

**Titoli delle notizie in altre lingue.** Senza chiave IA, i titoli in serbo, ucraino, ungherese, polacco e nelle altre lingue vengono tradotti in italiano da un traduttore automatico gratuito (MyMemory) e mostrati con la scritta **«Traduzione automatica»**; il titolo originale resta visibile accanto o passando il mouse. Viene inviato solo il titolo della notizia (un testo pubblico), mai dati dell'azienda. Il servizio gratuito traduce circa 55 titoli al giorno per computer, a partire dai più importanti: per averne circa 550 al giorno basta scrivere un indirizzo e-mail di contatto in `PALADEX_TITLE_TRANSLATION_EMAIL` nel file `.env`; per spegnerlo, `PALADEX_TITLE_TRANSLATION=false`. Con una chiave IA la traduzione (e il riassunto) li fa l'IA.

Senza chiavi l'applicazione funziona comunque: le fonti che le richiedono vengono saltate (o usate in versione ridotta) e la pagina Fonti lo segnala.

**Il modo più semplice per inserire una chiave:** pagina **Fonti e qualità dati** → la fonte che chiede la chiave → incollarla nel riquadro «Hai già la chiave? Incollala qui» → **Salva la chiave**. Paladex la salva nel file `.env` di questo computer e scarica subito i dati di quella fonte.

**Chiave dell'intelligenza artificiale:** pagina **Assistente** (oppure **Fonti e qualità dati**) → riquadro **«Servizio IA e chiave»** → scegliere Anthropic o OpenAI, incollare la chiave → **Salva**. L'analisi IA si attiva subito, senza riavviare. La chiave resta solo nel file `.env` di questo computer e non viene mai mostrata di nuovo.

### Dati dimostrativi

Per provare l'interfaccia prima che arrivino i dati reali, nella pagina **Fonti e qualità dati** si possono caricare **dati dimostrativi**. Sono contrassegnati ovunque con un'etichetta rossa **DEMO** e da una fascia rossa in alto, e si possono eliminare con un clic. **Non sono dati reali.**

### Aggiornare Paladex

Paladex si aggiorna da solo: a ogni avvio con **Avvia Paladex** scarica l'ultima versione (servono il programma `git` e una cartella scaricata con `git`) e, se servono, le librerie nuove. Se non c'è connessione o qualcosa non va, parte semplicemente la versione attuale. I dati (`data/`) e le chiavi (`.env`) non vengono mai toccati; i nuovi dati iniziali inclusi in una versione si aggiungono solo dove mancano. Per disattivare l'aggiornamento automatico: creare nella cartella un file vuoto chiamato `.no-auto-update`. Aggiornamento manuale: `git pull` nella cartella `paladex`.

### Correzioni e secondo computer

**Aziende trovate sul web.** Nella pagina di ogni paese e nella pagina Aziende, il riquadro **«Aziende del miele trovate sul web»** elenca alcune aziende che trattano miele (nome, attività, sito), prese dai primi risultati di una ricerca sul web. Porta la scritta **«Non ufficiale»** e la data della ricerca: non è un elenco ufficiale, non è una classifica, non è completo e non si aggiorna da solo. C'è solo chi ha un proprio sito che Paladex è riuscito ad aprire e che parla di miele.

Quando un numero è sbagliato (per esempio un prezzo), **lo si tocca e si scrive quello giusto**: accanto ai numeri che si possono correggere c'è una piccola matita; si apre una finestrella con il numero, lo si cambia e si preme **Salva** (o Invio). Si scrive nella stessa unità che si vede sullo schermo (per esempio €/kg): alla conversione pensa Paladex. Se il numero nuovo è molto diverso da quello di prima, Paladex chiede conferma una volta. Con una chiave IA lo si può anche scrivere a parole nel riquadro **«Scrivi a Paladex»**: «il prezzo del miele argentino di settembre non è 3,20 ma 3,40»; l'intelligenza artificiale capisce di quale dato si tratta e propone «valore attuale → nuovo valore» scegliendo solo tra i dati veri presenti in Paladex, e nulla cambia finché non si preme **Conferma**. Da quel momento il valore corretto compare ovunque con la scritta «corretto da *nome* il *data*»; il valore ufficiale della fonte resta nello storico e torna con un tocco («Rimetti il numero della fonte», nella stessa finestrella). Chi non sa il numero giusto può segnalare il dato come dubbio (apre una segnalazione nella pagina Fonti e qualità dati) o lasciare una nota su un paese. I totali fatti di più mesi (per esempio «da gennaio a settembre») non si correggono con un tocco: sono somme di più dati della fonte. Le offerte dei fornitori non vanno qui: Paladex le riconosce e rimanda alla pagina riservata **Offerte**, senza inviarle all'IA. Se più tardi la fonte pubblica un valore diverso, vale quello della fonte e un avviso lo segnala; se ripubblica lo stesso valore di prima, la correzione resta.

**Il computer del papà (o un secondo computer)** si installa esattamente come quello del titolare: Python, poi la cartella `paladex` **scaricata con `git`** (`git clone` del repository GitHub di Paladex) usando un account GitHub autorizzato a **scrivere** nel repository (la prima volta Windows/Mac chiede di accedere a GitHub e ricorda l'accesso), poi **Avvia Paladex**. La chiave dell'IA si incolla sullo schermo (pagina **Assistente** → «Servizio IA e chiave»); il nome che appare sulle correzioni si sceglie nella stessa finestra delle correzioni (oppure `PALADEX_USER_NAME=Mario` nel file `.env`).

**Che cosa viaggia e che cosa no.** Ogni correzione, segnalazione o nota diventa un piccolo file nel ramo `paladex-corrections` dello stesso repository GitHub (nessun servizio nuovo, nessuna password nuova): Paladex lo invia subito dopo la conferma e legge quelli degli altri computer all'avvio e ogni 15 minuti, poi anche la copia per il telefono li applica ogni mattina. Viaggiano solo: chi ha corretto, quando, il dato corretto, il valore ufficiale e quello nuovo, il motivo e le parole scritte. **Non lasciano mai il computer:** le offerte dei fornitori, le chiavi (`.env`), il database (`data/`), gli avvisi e le domande all'assistente. Senza internet o senza accesso a GitHub le correzioni restano sul computer («da inviare») e partono da sole appena possibile. Se un altro computer ha già un valore ufficiale diverso, la correzione non viene applicata lì ma mostrata come «in conflitto», da verificare. **Lo scambio è spento finché non lo si accende**, una volta, su ogni computer che deve scambiare le correzioni (interruttore «Scambia le correzioni con gli altri computer», oppure `PALADEX_CORRECTIONS_SYNC=true` nel file `.env`): così una copia di prova o una seconda cartella non pubblica mai niente da sola. Da spento, le correzioni restano su questo computer.

### Backup

Tutti i dati si trovano nella cartella `data/` e le chiavi nel file `.env`. Per fare una copia di sicurezza, chiudere Paladex e copiare la cartella `data/` e il file `.env`.

---

## English — Quick guide

### Install (once)

1. Install **Python 3.11+** from <https://www.python.org/downloads/>. On Windows, tick **"Add Python to PATH"**.
2. Copy the `paladex` folder to the computer.
3. *(Optional)* Edit `.env` (created from `.env.example` on first start) to add free data-source keys and an optional AI key (see the table above).

### Start

* **Windows:** double-click `Avvia Paladex.bat`.
* **macOS:** double-click `Avvia Paladex.command`.
* **Linux:** run `./start.sh`.

The browser opens at <http://127.0.0.1:8765> and shows real data straight away: the app ships with data already collected from the official sources (`starter/`, merged once per version at start-up, never overwriting local data, collection date shown at the top). Collection then runs automatically on a schedule, on start-up when the last run is older than 6 hours, and on demand with the **"Aggiorna dati"** button. The app updates itself: at every start the launcher downloads the latest version with `git fetch` (gives up after 90 s) and moves forward only by fast-forward (`git merge --ff-only`: never merges, never asks for a password; on any problem the current version starts), reinstalls the Python libraries when `backend/requirements.txt` changed, then starts (`scripts/launch.py`). Starting it again while it runs only opens the browser. Opt out with an empty `.no-auto-update` file or `PALADEX_AUTO_UPDATE=false`. Free source keys can be pasted on the Sources page, and the AI service and key in the "AI service and key" panel on the Assistant or Sources page (saved to the local `.env`, applied at once, never sent back to the browser).

### Command line (advanced)

```bash
cd backend && source .venv/bin/activate     # Windows: .venv\Scripts\activate
python -m paladex collect                   # run every collector now
python -m paladex collect usda_honey_report eurostat_comext --force
python -m paladex sources                   # status of every source
python -m paladex seed-demo | purge-demo    # clearly-labelled demo data on/off
python -m paladex starter-import            # merge the shipped real starter data (serve does it)
python -m paladex starter-build --from /path/to/paladex.sqlite3   # (developers) rebuild starter/
python -m paladex corrections-sync          # exchange corrections with the other computers now (git branch paladex-corrections)
python -m paladex corrections-apply --from-git   # only read and apply them (the phone copy does this)
python -m paladex serve --no-browser
```

### Developers

* `docs/ARCHITECTURE.md` covers the design, data model and milestones.
* `docs/DATA_SOURCES.md` describes each source: access, formats, update frequency, limits and licensing.
* `docs/DEVELOPING.md` gives the conventions and the non-negotiable data rules.
* Backend tests: `cd backend && .venv/bin/pip install pytest respx && .venv/bin/python -m pytest` (Windows: `.venv\Scripts\...`).
* Frontend dev server: `cd frontend && npm install && npm run dev` (proxies `/api` to port 8765).
