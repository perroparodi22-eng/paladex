// Minimal i18n. Italian is the default; English is a toggle (stored in the browser and
// on the backend). Each page keeps its own dictionary in ./pages/<page>.ts exporting
// `{ it: {...}, en: {...} }`; they are merged automatically, so pages never edit a shared file.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { isMirror } from '@/lib/mirror'
import type { Lang } from '@/lib/types'
import { common } from './common'

type Dict = Record<string, string>
type PageDict = { it: Dict; en: Dict }

const modules = import.meta.glob<{ default: PageDict }>('./pages/*.ts', { eager: true })

const DICTS: Record<Lang, Dict> = { it: { ...common.it }, en: { ...common.en } }
for (const [path, mod] of Object.entries(modules)) {
  const ns = path.replace('./pages/', '').replace('.ts', '')
  for (const lang of ['it', 'en'] as Lang[]) {
    for (const [k, v] of Object.entries(mod.default[lang] ?? {})) DICTS[lang][`${ns}.${k}`] = v
  }
}

interface I18nCtx {
  lang: Lang
  setLang: (l: Lang) => void
  t: (key: string, vars?: Record<string, string | number>) => string
}

const Ctx = createContext<I18nCtx | null>(null)
const STORAGE_KEY = 'paladex.lang'

function readStoredLang(): Lang {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    return v === 'en' ? 'en' : 'it'
  } catch {
    return 'it'
  }
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(readStoredLang)

  const setLang = useCallback((l: Lang) => {
    setLangState(l)
    try {
      localStorage.setItem(STORAGE_KEY, l)
    } catch {
      /* ignore */
    }
    // (The read-only online copy has no settings to save: the browser keeps the choice.)
    if (!isMirror()) fetch('/api/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ language: l }) }).catch(() => {})
  }, [])

  useEffect(() => {
    document.documentElement.lang = lang
  }, [lang])

  const t = useCallback(
    (key: string, vars?: Record<string, string | number>) => {
      let s = DICTS[lang][key] ?? DICTS.it[key] ?? key
      if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, String(v))
      return s
    },
    [lang],
  )

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useI18n(): I18nCtx {
  const c = useContext(Ctx)
  if (!c) throw new Error('useI18n outside provider')
  return c
}

/** A source's publication rhythm in the UI language (`expected_update` is Italian, `expected_update_en` English). */
export function expectedUpdate(s: { expected_update?: string | null; expected_update_en?: string | null }, lang: Lang): string | null {
  return (lang === 'en' ? s.expected_update_en || s.expected_update : s.expected_update || s.expected_update_en) || null
}

/** Pick the right language field from a backend object: pick(row, 'title') -> row.title_it / row.title_en / row.title */
export function pickLang<T extends Record<string, unknown>>(row: T, field: string, lang: Lang): string | null {
  const v = (row[`${field}_${lang}`] ?? row[field] ?? row[`${field}_${lang === 'it' ? 'en' : 'it'}`]) as string | null | undefined
  return v ?? null
}
