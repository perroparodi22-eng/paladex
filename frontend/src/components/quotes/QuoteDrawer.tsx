// Detail of one quote: landed cost per kg / drum / container for each duty alternative, the
// line-by-line breakdown with sources and dates, editable assumptions, the official duty layers,
// the exchange rates used and the market reference prices.
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, ArchiveRestore, Copy, ExternalLink, Lock, Pencil } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { DemoBadge, ErrorBlock, Loading } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api, qs } from '@/lib/api'
import { fmtDate, fmtDateTime } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import { Assumptions } from './Assumptions'
import { Breakdown } from './Breakdown'
import { Drawer, Section } from './Drawer'
import { DutyDetails } from './DutyDetails'
import { FlagNote, LandedSummary } from './LandedSummary'
import { MarketReference } from './MarketReference'
import { StatusChip } from './QuoteTable'
import type { FxMode, Landed, Quote, QuoteBody, QuoteDetail, QuotesMeta } from './types'
import { bodyFromQuote, CONTAINER_KG, fmtPlain, fmtTons, sameBody } from './utils'
import { isMappedUrl, pageUrl } from '@/lib/links'

export function QuoteDrawer({ id, fx, onFx, onClose, onEdit, onOpenQuote }: {
  id: number
  fx: FxMode
  onFx: (v: FxMode) => void
  onClose: () => void
  onEdit: (id: number) => void
  onOpenQuote: (id: number) => void
}) {
  const { t, lang } = useI18n()
  const { country, variety } = useLabels()
  const qc = useQueryClient()
  const [containerKg, setContainerKg] = useState(CONTAINER_KG)
  const [draft, setDraft] = useState<QuoteBody | null>(null)
  const params = { fx, container_kg: containerKg === CONTAINER_KG ? undefined : containerKg }

  const detail = useQuery({
    queryKey: ['quotes', 'detail', id, fx, containerKg],
    queryFn: () => api.get<QuoteDetail>(`/quotes/${id}`, params),
    placeholderData: keepPreviousData,
  })
  const meta = useQuery({ queryKey: ['quotes', 'meta'], queryFn: () => api.get<QuotesMeta>('/quotes/meta'), staleTime: 10 * 60_000 })
  const quote = detail.data?.quote.id === id ? detail.data.quote : undefined
  const saved = useMemo(() => (quote ? bodyFromQuote(quote) : null), [quote])
  useEffect(() => setDraft(null), [id])
  const current = draft ?? saved
  const dirty = Boolean(draft && saved && !sameBody(draft, saved))

  const whatIf = useQuery({
    queryKey: ['quotes', 'calc', draft, fx, containerKg],
    queryFn: () => api.post<Landed>(`/quotes/calculate${qs(params)}`, draft),
    enabled: dirty,
    placeholderData: keepPreviousData,
  })
  const landed: Landed | undefined = dirty ? whatIf.data : detail.data?.landed

  const refresh = () => qc.invalidateQueries({ queryKey: ['quotes'] })
  const save = useMutation({
    mutationFn: (body: QuoteBody) => api.put<Quote>(`/quotes/${id}`, body),
    onSuccess: () => { setDraft(null); refresh() },
  })
  const archive = useMutation({
    mutationFn: (archived: boolean) => api.post<Quote>(`/quotes/${id}/${archived ? 'archive' : 'unarchive'}`),
    onSuccess: refresh,
  })
  const duplicate = useMutation({
    mutationFn: () => api.post<Quote>(`/quotes/${id}/duplicate`),
    onSuccess: (q) => { refresh(); onOpenQuote(q.id) },
  })

  const title = quote?.supplier_name ?? t('quotes.drawer.loading')
  const metaLine = quote && (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
      {quote.is_demo && <DemoBadge />}
      <StatusChip q={quote} />
      <span>{country(quote.origin_iso3)} · {variety(quote.variety)}{quote.variety_note ? ` (${quote.variety_note})` : ''}</span>
      <span>· {t('quotes.list.received', { date: fmtDate(quote.date_received, lang) })}</span>
      <span>· {quote.valid_until ? t('quotes.list.until', { date: fmtDate(quote.valid_until, lang) }) : t('quotes.list.noExpiry')}</span>
    </span>
  )
  const actions = quote && (
    <>
      <button type="button" className="btn-secondary !py-1.5" onClick={() => onEdit(id)}><Pencil size={16} /> {t('quotes.drawer.edit')}</button>
      <button type="button" className="btn-secondary !py-1.5" onClick={() => duplicate.mutate()} disabled={duplicate.isPending}
        title={t('quotes.drawer.duplicateHint')}><Copy size={16} /> {t('quotes.drawer.duplicate')}</button>
      {quote.archived ? (
        <button type="button" className="btn-secondary !py-1.5" onClick={() => archive.mutate(false)} disabled={archive.isPending}>
          <ArchiveRestore size={16} /> {t('quotes.drawer.unarchive')}
        </button>
      ) : (
        <button type="button" className="btn-secondary !py-1.5" onClick={() => archive.mutate(true)} disabled={archive.isPending}
          title={t('quotes.drawer.archiveHint')}>
          <Archive size={16} /> {t('quotes.drawer.archive')}
        </button>
      )}
    </>
  )

  return (
    <Drawer open onClose={onClose} labelId="quote-drawer-title" eyebrow={t('quotes.drawer.eyebrow')} title={title} meta={metaLine}
      actions={actions} size="lg">
      {detail.isLoading ? <Loading /> : detail.error ? <ErrorBlock error={detail.error} onRetry={() => detail.refetch()} /> : !quote || !current || !detail.data ? null : (
        <>
          {(archive.error || duplicate.error) && <div className="mb-4"><ErrorBlock error={archive.error ?? duplicate.error} /></div>}
          {quote.archived && <p className="mb-4 text-[0.9rem] text-muted">{t('quotes.drawer.archivedNote')}</p>}

          <Section title={t('quotes.drawer.landedTitle', { dest: t(`quotes.dest.${current.destination}`) })}
            aside={landed ? t('quotes.drawer.calcOn', { date: fmtDate(landed.calc_date, lang) }) : undefined}>
            {dirty && whatIf.isFetching && !whatIf.data ? <Loading /> : whatIf.error && dirty ? <ErrorBlock error={whatIf.error} /> : landed ? (
              <LandedSummary landed={landed} />
            ) : null}
          </Section>

          <Section title={t('quotes.drawer.assumptions')} aside={t('quotes.drawer.assumptionsHint')}>
            <Assumptions draft={current} onChange={(p) => setDraft({ ...current, ...p })} fx={fx} onFx={onFx}
              receivedOn={quote.date_received} containerKg={containerKg} onContainerKg={setContainerKg}
              currencies={meta.data?.currencies ?? ['EUR', 'USD']} dirty={dirty}
              onSave={() => draft && save.mutate(draft)} onReset={() => setDraft(null)} saving={save.isPending}
              saveError={save.error ? (save.error as Error).message : null} />
          </Section>

          {landed && (
            <>
              <Section title={t('quotes.drawer.breakdown')} aside={t('quotes.drawer.breakdownHint')}>
                <Breakdown landed={landed} />
                {landed.flags.some((f) => f.kind === 'info') && (
                  <div className="mt-3"><FlagNote flags={landed.flags.filter((f) => f.kind === 'info')} title={t('quotes.drawer.notes')} tone="info" /></div>
                )}
              </Section>

              <Section title={t('quotes.drawer.duty')}>
                <DutyDetails landed={landed} origin={current.origin_iso3} />
              </Section>

              <Section title={t('quotes.drawer.fx')}>
                {landed.fx.rates.length === 0 && landed.fx.missing.length === 0 ? (
                  <p className="text-[0.9rem] text-muted">{t('quotes.drawer.fxNone')}</p>
                ) : (
                  <ul className="space-y-1 text-[0.92rem]">
                    {landed.fx.rates.map((r) => (
                      <li key={r.currency} className="num">
                        1 EUR = {fmtPlain(r.per_eur, lang, 4)} {r.currency}
                        <span className="font-sans text-muted"> · {t('quotes.drawer.fxDate', { date: fmtDate(r.rate_date, lang) })}</span>
                      </li>
                    ))}
                    {landed.fx.missing.map((c) => (
                      <li key={c} className="text-warn">{t('quotes.drawer.fxMissing', { ccy: c, date: fmtDate(landed.fx.date, lang) })}</li>
                    ))}
                  </ul>
                )}
                <p className="mt-1 text-[0.82rem] text-muted">
                  {t(fx === 'today' ? 'quotes.drawer.fxModeToday' : 'quotes.drawer.fxModeReceived', { date: fmtDate(landed.fx.date, lang) })}
                  {landed.fx.source && <> · {t('prov.source')}: {landed.fx.source.publisher ?? landed.fx.source.name}</>}
                  {landed.fx.source_url && (
                    <> · <a href={pageUrl(landed.fx.source_url) ?? undefined} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-0.5"
                      title={isMappedUrl(landed.fx.source_url) ? t('prov.exactAddress', { url: landed.fx.source_url ?? '' }) : undefined}>{t(isMappedUrl(landed.fx.source_url) ? 'prov.officialPage' : 'prov.original')} <ExternalLink size={11} /></a></>
                  )}
                </p>
              </Section>
            </>
          )}

          <Section title={t('quotes.drawer.market')} aside={t('quotes.drawer.marketHint', { origin: country(quote.origin_iso3), variety: variety(quote.variety) })}>
            <MarketReference market={detail.data.market} />
          </Section>

          <Section title={t('quotes.drawer.record')}>
            <dl className="grid gap-x-6 gap-y-2 text-[0.92rem] sm:grid-cols-2">
              <Item k={t('quotes.form.quantity')} v={quote.quantity_kg ? fmtTons(quote.quantity_kg, lang) : t('quotes.notGivenF')} />
              <Item k={t('quotes.form.packaging')} v={quote.packaging ?? '—'} />
              <Item k={t('quotes.form.incoterm')} v={quote.incoterm ? `${quote.incoterm}${quote.incoterm_place ? ` ${quote.incoterm_place}` : ''}` : t('quotes.notGiven')} />
              <Item k={t('quotes.drawer.createdAt')} v={fmtDateTime(quote.created_at, lang)} />
              <Item k={t('quotes.drawer.updatedAt')} v={fmtDateTime(quote.updated_at, lang)} />
              <Item k={t('quotes.drawer.dataStatus')} v={quote.is_demo ? t('quotes.drawer.demoData') : t('quotes.drawer.userData')} />
              {quote.notes && <div className="sm:col-span-2"><dt className="text-muted">{t('quotes.form.notes')}</dt><dd className="whitespace-pre-line">{quote.notes}</dd></div>}
            </dl>
            <p className="mt-3 flex items-start gap-2 text-[0.84rem] text-muted"><Lock size={14} className="mt-0.5 shrink-0" />{t('quotes.privacy')}</p>
          </Section>
        </>
      )}
    </Drawer>
  )
}

function Item({ k, v }: { k: string; v: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-muted">{k}</dt>
      <dd className="break-words text-charcoal-soft">{v}</dd>
    </div>
  )
}
