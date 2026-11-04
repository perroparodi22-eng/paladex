// Notice shown in the top bar during the first minutes after installation.
const it = {
  starterUpdating:
    'Stai vedendo i dati reali già raccolti dalle fonti ufficiali fino al {date}. Paladex li sta aggiornando ora da questo computer: i dati più recenti compaiono man mano (la prima volta servono circa 30–40 minuti).',
  starterWaiting:
    'Stai vedendo i dati reali già raccolti dalle fonti ufficiali fino al {date}. Verranno aggiornati automaticamente da questo computer.',
  starterOffline:
    'Stai vedendo i dati reali già raccolti dalle fonti ufficiali fino al {date}. Nessuna connessione a internet: verranno aggiornati appena il computer è online.',
  collecting:
    'Primo avvio: Paladex sta scaricando i dati dalle fonti ufficiali (la prima volta servono circa 30–40 minuti). Le pagine si riempiono man mano: puoi lasciare aperta la finestra.',
  offline:
    'Nessun dato ancora: il computer non risulta collegato a internet. Controlla la connessione e premi «Aggiorna dati».',
  empty: 'Nessun dato ancora raccolto. Premi «Aggiorna dati» per scaricarli dalle fonti ufficiali.',
}

const en: typeof it = {
  starterUpdating:
    'You are looking at real data already collected from the official sources up to {date}. Paladex is now updating it from this computer: newer figures appear as they arrive (about 30–40 minutes the first time).',
  starterWaiting:
    'You are looking at real data already collected from the official sources up to {date}. It will be updated automatically from this computer.',
  starterOffline:
    'You are looking at real data already collected from the official sources up to {date}. No internet connection: it will be updated as soon as this computer is online.',
  collecting:
    'First start: Paladex is downloading the data from the official sources (about 30–40 minutes the first time). Pages fill in as data arrives: you can leave the window open.',
  offline: 'No data yet: this computer does not seem to be connected to the internet. Check the connection and press "Refresh data".',
  empty: 'No data collected yet. Press "Refresh data" to download it from the official sources.',
}

export default { it, en }
