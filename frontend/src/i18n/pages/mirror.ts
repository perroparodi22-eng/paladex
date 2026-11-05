// Read-only online copy (lib/mirror.ts): the strip on every page, the "not in the copy" note,
// and the phone menu button (shown in the normal application too, on narrow screens).
const it = {
  strip: 'Copia online di sola lettura',
  collected: 'dati raccolti fino al {when}',
  collectedUnknown: 'data di raccolta non disponibile',
  daily: 'aggiornata ogni giorno',
  stale: 'copia non aggiornata da {n} giorni: i dati possono essere vecchi',
  stale1: 'copia non aggiornata da ieri: i dati possono essere vecchi',
  dataStale: 'le fonti non rispondono da {n} giorni: i dati possono essere vecchi',
  produced: 'Copia prodotta il {when}',
  missing: 'Questa vista non è inclusa nella copia online: è disponibile sul computer.',
  missingTitle: 'Non inclusa nella copia online',
  readOnly: 'Copia online di sola lettura: le modifiche si fanno sul computer.',
  footer: 'Copia online privata e di sola lettura per Parodi Group: si apre solo con l’account Netlify del titolare. Offerte, avvisi e strumenti di lavoro restano sul computer.',
  menu: 'Menu',
  closeMenu: 'Chiudi il menu',
}

const en: typeof it = {
  strip: 'Read-only online copy',
  collected: 'data collected up to {when}',
  collectedUnknown: 'collection date not available',
  daily: 'refreshed every day',
  stale: 'copy not refreshed for {n} days: the data may be old',
  stale1: 'copy not refreshed since yesterday: the data may be old',
  dataStale: 'the sources have not answered for {n} days: the data may be old',
  produced: 'Copy produced on {when}',
  missing: 'This view is not included in the online copy: it is available on the computer.',
  missingTitle: 'Not in the online copy',
  readOnly: 'Read-only online copy: changes are made on the computer.',
  footer: 'Private, read-only online copy for Parodi Group: it opens only with the owner’s Netlify account. Quotes, alerts and working tools stay on the computer.',
  menu: 'Menu',
  closeMenu: 'Close the menu',
}

export default { it, en }
