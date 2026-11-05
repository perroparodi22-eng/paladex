// Question composer: a textarea (Enter asks, Shift+Enter new line) and, for questions about supplier
// offers, the choice of the offers to compare.
import { useQuery } from '@tanstack/react-query'
import { Loader2, Send } from 'lucide-react'
import { type FormEvent, type KeyboardEvent } from 'react'
import { Link } from 'react-router-dom'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtDate, fmtNumber } from '@/lib/format'
import type { QuoteOption } from './types'

const ABOUT_OFFERS = /offert|offer|fornitor|supplier|preventiv|quotes?\b/i
export const MAX_CHARS = 1000

export function isAboutOffers(text: string): boolean {
  return ABOUT_OFFERS.test(text)
}

export function AskBox({ value, onChange, onSubmit, pending, aiEnabled, quoteIds, onQuoteIds }: {
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  pending: boolean
  aiEnabled: boolean
  quoteIds: number[]
  onQuoteIds: (ids: number[]) => void
}) {
  const { t, lang } = useI18n()
  const offers = isAboutOffers(value)
  const quotes = useQuery({
    queryKey: ['assistant', 'quotes', lang],
    queryFn: () => api.get<{ items: QuoteOption[] }>('/assistant/quotes', { lang }),
    enabled: offers,
  })
  const submit = (e?: FormEvent) => {
    e?.preventDefault()
    if (!pending && value.trim()) onSubmit()
  }
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submit()
    }
  }
  const toggle = (id: number) => onQuoteIds(quoteIds.includes(id) ? quoteIds.filter((x) => x !== id) : [...quoteIds, id])
  return (
    <form onSubmit={submit} className="panel p-3 sm:p-4">
      <label htmlFor="assistant-question" className="label">{t('assistant.ask.label')}</label>
      <textarea
        id="assistant-question"
        className="field min-h-[4.5rem] resize-y leading-snug"
        rows={2}
        maxLength={MAX_CHARS}
        value={value}
        placeholder={t('assistant.ask.placeholder')}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKey}
        disabled={pending}
      />
      {offers && (
        <fieldset className="mt-3 rounded-sm border border-line-soft bg-paper px-3 py-2">
          <legend className="px-1 text-sm font-medium text-charcoal-soft">{t('assistant.quotes.title')}</legend>
          {quotes.data && quotes.data.items.length > 0 ? (
            <>
              <p className="mb-1.5 text-[0.8rem] text-muted">{t('assistant.quotes.hint')}</p>
              <ul className="space-y-1">
                {quotes.data.items.slice(0, 8).map((q) => (
                  <li key={q.id}>
                    <label className="flex cursor-pointer items-start gap-2 text-[0.88rem]">
                      <input type="checkbox" className="mt-1 accent-forest-700" checked={quoteIds.includes(q.id)}
                        onChange={() => toggle(q.id)} disabled={pending} />
                      <span className="min-w-0 break-words">
                        <span className="font-medium text-charcoal">{q.supplier_name}</span>
                        {' · '}{q.origin_name} · {q.variety_name} · <span className="num">{fmtNumber(q.price_per_kg, lang, 2)} {q.currency}/kg</span>
                        {q.incoterm ? ` ${q.incoterm}` : ''}
                        <span className="text-muted"> · {t('assistant.quotes.received', { date: fmtDate(q.date_received, lang) })}</span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            </>
          ) : quotes.data ? (
            <p className="text-[0.85rem] text-muted">
              {t('assistant.quotes.none')} <Link to="/offerte" className="link">{t('assistant.quotes.add')}</Link>
            </p>
          ) : null}
        </fieldset>
      )}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1 text-[0.78rem] leading-snug text-muted">
          <div className="hidden sm:block">{t('assistant.ask.hint')}</div>
          <div>{t('assistant.ask.privacy')} {aiEnabled && t('assistant.ask.privacyAi')}</div>
        </div>
        <div className="flex items-center gap-3">
          <span className="num text-[0.75rem] text-muted">{t('assistant.ask.chars', { n: value.length, max: MAX_CHARS })}</span>
          <button type="submit" className="btn-primary" disabled={pending || !value.trim()}>
            {pending ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
            {t('assistant.ask.submit')}
          </button>
        </div>
      </div>
    </form>
  )
}
