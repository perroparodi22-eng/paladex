# Parodi Group — Honey Intelligence (Paladex)

A private, local intelligence platform for the global honey market: prices, international trade, production, news, and official reports and regulations, collected automatically from official sources and kept with their full history.

> **Italiano più sotto.** The application interface is in Italian by default, with English available.

---

## Italiano — Guida rapida

### Cosa fa

* Raccoglie automaticamente dati ufficiali e notizie sul miele: USDA (USA), Commissione Europea / Eurostat, Osservatorio Nazionale Miele e listini delle Camere di Commercio, UN Comtrade, FAO, cambi BCE e notizie di settore.
* Salva tutto sul computer, senza mai cancellare lo storico. Funziona anche senza internet, con i dati già salvati.
* Ogni numero mostra la fonte, la data di pubblicazione, il periodo e il tipo (all'ingrosso, al produttore, valore doganale…). Nessun dato viene inventato. Quando un dato manca, l'applicazione lo dice.

### Installazione (una sola volta)

1. Installare **Python 3.11 o superiore** (l'interfaccia è già inclusa: Node.js non serve) da <https://www.python.org/downloads/>. Su Windows, durante l'installazione spuntare **"Add Python to PATH"**.
2. Copiare la cartella `paladex` sul computer, per esempio in `Documenti`.
3. *(Facoltativo)* Aprire il file `.env` con il Blocco note e inserire le chiavi gratuite delle fonti dati e, se si desidera, la chiave dell'intelligenza artificiale (vedere più sotto). Al primo avvio il file `.env` viene creato automaticamente da `.env.example`.

### Avvio di tutti i giorni

* **Windows:** doppio clic su **`Avvia Paladex.bat`**.
* **Mac:** doppio clic su **`Avvia Paladex.command`**.

Il primo avvio richiede qualche minuto. Poi il browser si apre da solo su <http://127.0.0.1:8765>. Per chiudere l'applicazione basta chiudere la finestra nera.

I dati si aggiornano da soli mentre l'applicazione è aperta, e all'avvio se l'ultimo aggiornamento risale a più di 6 ore prima. Il pulsante **"Aggiorna dati"** in alto aggiorna tutto subito. La pagina **Fonti e qualità dati** mostra, per ogni fonte, quando è stata controllata e se ci sono problemi.

### Chiavi gratuite (consigliate)

| Chiave nel file `.env` | A cosa serve | Dove ottenerla (gratis) |
|---|---|---|
| `PALADEX_COMTRADE_API_KEY` | Commercio mondiale del miele (HS 0409), dati mensili | <https://comtradedeveloper.un.org> → iscriversi al prodotto "comtrade - v1" |
| `PALADEX_DATA_GOV_API_KEY` | Importazioni USA di miele per origine (USDA FAS / Census) | <https://api.data.gov/signup/> |
| `PALADEX_USDA_NASS_API_KEY` | Produzione e prezzi del miele negli USA (USDA NASS) | <https://quickstats.nass.usda.gov/api> |
| `PALADEX_CENSUS_API_KEY` *(facoltativa)* | Importazioni USA dal Census Bureau (funziona anche senza chiave, con limite giornaliero) | <https://api.census.gov/data/key_signup.html> |
| `PALADEX_FAOSTAT_USERNAME` / `PASSWORD` *(facoltativi)* | FAOSTAT via API e flussi bilaterali (senza account si usano i file pubblici) | <https://www.fao.org/faostat/en/#developer> |
| `PALADEX_LLM_PROVIDER` + `PALADEX_ANTHROPIC_API_KEY` (oppure `PALADEX_OPENAI_API_KEY`) | Riassunti e traduzioni delle notizie (in seguito: assistente e sintesi giornaliera) | console.anthropic.com oppure platform.openai.com (a pagamento, in base all'uso) |

Senza chiavi l'applicazione funziona comunque: le fonti che le richiedono vengono saltate (o usate in versione ridotta) e la pagina Fonti lo segnala.

### Dati dimostrativi

Per provare l'interfaccia prima che arrivino i dati reali, nella pagina **Fonti e qualità dati** si possono caricare **dati dimostrativi**. Sono contrassegnati ovunque con un'etichetta rossa **DEMO** e da una fascia rossa in alto, e si possono eliminare con un clic. **Non sono dati reali.**

### Backup

Tutti i dati si trovano nella cartella `data/`. Per fare una copia di sicurezza, copiare quella cartella.

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

The browser opens at <http://127.0.0.1:8765>. Collection runs automatically on a schedule, on start-up when the last run is older than 6 hours, and on demand with the **"Aggiorna dati"** button.

### Command line (advanced)

```bash
cd backend && source .venv/bin/activate     # Windows: .venv\Scripts\activate
python -m paladex collect                   # run every collector now
python -m paladex collect usda_honey_report eurostat_comext --force
python -m paladex sources                   # status of every source
python -m paladex seed-demo | purge-demo    # clearly-labelled demo data on/off
python -m paladex serve --no-browser
```

### Developers

* `docs/ARCHITECTURE.md` covers the design, data model and milestones.
* `docs/DATA_SOURCES.md` describes each source: access, formats, update frequency, limits and licensing.
* `docs/DEVELOPING.md` gives the conventions and the non-negotiable data rules.
* Backend tests: `cd backend && python -m pytest`.
* Frontend dev server: `cd frontend && npm install && npm run dev` (proxies `/api` to port 8765).
