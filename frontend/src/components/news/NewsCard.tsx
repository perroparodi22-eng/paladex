// One article in the /notizie list: headline (AI translation labelled), provenance, AI summary or the
// publisher's excerpt, country/topic tags, relevance with its explanation, syndicated copies, link out.
import clsx from 'clsx'
import { ChevronDown, ExternalLink, Languages, Loader2 } from 'lucide-react'
import { useState } from 'react'
import { AiBadge, DemoBadge, ReliabilityBadge } from '@/components/ui'
import { useI18n } from '@/i18n'
import { ApiError } from '@/lib/api'
import { fmtAgo } from '@/lib/format'
import { useLabels } from '@/lib/meta'
import { fmtNewsDate, fmtNewsDateTime, RelevanceMeter, TagButton, useLangName, utc } from './bits'
import type { DuplicateOutlet, NewsItem } from './types'

const EXCERPT_CLAMP_CHARS = 280

export interface CardActions {
  llmEnabled: boolean
  topicLabel: (key: string) => string
  activeCountries: string[]
  activeTopics: string[]
  onCountry: (iso3: string) => void
  onTopic: (key: string) => void
  onTranslate: (item: NewsItem) => void
  translating: boolean
  translateError: unknown
}

function translateErrorText(err: unknown, t: (k: string, v?: Record<string, string | number>) => string): string {
  if (err instanceof ApiError) {
    if (err.status === 409) return t('news.card.err.noAi')
    if (err.status === 502 || err.status === 503 || err.status === 504) return t('news.card.err.aiDown')
    if (err.status === 404) return t('news.card.err.gone')
  }
  const msg = err instanceof Error ? err.message : String(err)
  return t('news.card.err.generic', { msg })
}

function Thumb({ src }: { src: string }) {
  const [broken, setBroken] = useState(false)
  if (broken) return null
  return (
    <img
      src={src}
      alt=""
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setBroken(true)}
      className="hidden sm:block h-[126px] w-[188px] shrink-0 rounded-sm border border-line-soft bg-paper object-cover"
    />
  )
}

function Outlets({ outlets }: { outlets: DuplicateOutlet[] }) {
  const { t, lang } = useI18n()
  const langName = useLangName()
  return (
    <ul className="mt-3 divide-y divide-line-soft border-y border-line-soft bg-paper/60">
      {outlets.map((o) => (
        <li key={o.id} className="flex flex-wrap items-center gap-x-3 gap-y-0.5 px-3 py-2 text-[0.9rem]">
          <span className="font-medium text-charcoal">{o.publisher || o.source_name || '—'}</span>
          <span className="text-muted" title={t('news.card.publishedTip', { d: fmtNewsDateTime(o.published_at, lang), c: fmtNewsDateTime(o.collected_at, lang) })}>
            {o.published_at ? fmtNewsDate(o.published_at, lang) : t('news.card.collected', { ago: fmtAgo(utc(o.collected_at), lang) })}
          </span>
          {o.language && o.language.slice(0, 2) !== lang && (
            <span className="text-[0.8rem] text-muted">· {langName(o.language)}</span>
          )}
          {o.source_name && <span className="hidden md:inline text-[0.8rem] text-muted truncate max-w-[22rem]">· {t('news.card.via')} {o.source_name}</span>}
          <a href={o.url} target="_blank" rel="noreferrer" className="link ml-auto inline-flex items-center gap-1 text-[0.86rem]" title={t('news.card.opensNewTab')}>
            {t('news.card.outletOpen')} <ExternalLink size={13} />
          </a>
        </li>
      ))}
    </ul>
  )
}

export function NewsCard({ item, actions }: { item: NewsItem; actions: CardActions }) {
  const { t, lang } = useI18n()
  const { country } = useLabels()
  const langName = useLangName()
  const [showOutlets, setShowOutlets] = useState(false)
  const [showExcerpt, setShowExcerpt] = useState(false)
  const [excerptOpen, setExcerptOpen] = useState(false)

  const d = item.display[lang]
  const foreign = Boolean(item.language) && item.language!.slice(0, 2) !== lang
  const aiModel = item.ai_model?.split(':').slice(1).join(':') || item.ai_model || 'IA'
  const outlet = item.publisher || item.source?.publisher || item.source?.name || '—'
  // Syndicated copies from other outlets (the same outlet seen through two feeds is not "another source").
  const outlets = item.duplicate_outlets.filter((o) => (o.publisher ?? '').trim().toLowerCase() !== outlet.trim().toLowerCase())
  const nOutlets = outlets.length
  const canTranslate = actions.llmEnabled && d.needs_translation
  const excerpt = d.excerpt
  const longExcerpt = (excerpt?.length ?? 0) > EXCERPT_CLAMP_CHARS

  const when = item.published_at
    ? fmtNewsDate(item.published_at, lang)
    : t('news.card.collected', { ago: fmtAgo(utc(item.collected_at), lang) })
  const whenTip = item.published_at
    ? t('news.card.publishedTip', { d: fmtNewsDateTime(item.published_at, lang), c: fmtNewsDateTime(item.collected_at, lang) })
    : t('news.card.noDate')

  const excerptBlock = excerpt ? (
    <div className="mt-3 border-l-2 border-gold-light/70 pl-3.5">
      <div className="eyebrow !text-[0.68rem] text-gold-dark" title={t('news.card.excerptTip')}>{t('news.card.excerpt')}</div>
      <p className={clsx('mt-1 text-[0.98rem] leading-relaxed text-charcoal-soft', !excerptOpen && longExcerpt && 'line-clamp-3')}
        lang={item.language ?? undefined}>
        {excerpt}
      </p>
      {longExcerpt && (
        <button type="button" className="mt-0.5 text-[0.85rem] text-forest-700 hover:underline" onClick={() => setExcerptOpen((v) => !v)}>
          {excerptOpen ? t('news.card.readLess') : t('news.card.readMore')}
        </button>
      )}
    </div>
  ) : null

  return (
    <article className="px-6 py-5" aria-labelledby={`news-${item.id}`}>
      <div className="flex gap-5">
        <div className="min-w-0 flex-1">
          {/* provenance line */}
          <div className="flex items-start justify-between gap-4">
            <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[0.85rem] text-muted">
              {item.is_demo && <span title={t('news.card.demo')}><DemoBadge /></span>}
              <span className="font-semibold uppercase tracking-[0.06em] text-[0.78rem] text-charcoal-soft">{outlet}</span>
              <span aria-hidden>·</span>
              <time dateTime={utc(item.published_at ?? item.collected_at) ?? undefined} title={whenTip}>{when}</time>
              {foreign && (
                <span
                  className="inline-flex items-center gap-1 rounded-sm border border-line-soft px-1.5 py-[1px] text-[0.72rem] uppercase tracking-wide text-muted"
                  title={actions.llmEnabled || !d.needs_translation
                    ? t('news.card.langTag', { lang: langName(item.language) })
                    : t('news.card.langTagNoAi', { lang: langName(item.language) })}
                >
                  {item.language!.slice(0, 2)}
                </span>
              )}
            </div>
            <RelevanceMeter item={item} />
          </div>

          {/* headline */}
          <h3 id={`news-${item.id}`} className="mt-1.5 font-serif text-[1.32rem] font-semibold leading-snug text-charcoal">
            <a href={item.url} target="_blank" rel="noreferrer" className="decoration-gold/60 underline-offset-[3px] hover:text-forest-800 hover:underline"
              lang={d.title_is_ai ? lang : item.language ?? undefined}>
              {d.title}
            </a>
          </h3>
          {d.title_is_ai && (
            <div className="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[0.86rem] text-muted" title={t('news.card.aiTitleTip', { model: aiModel })}>
              <AiBadge label={t('news.card.aiTitle')} />
              <span>
                {t('news.card.original', { lang: langName(item.language) })}:{' '}
                <span className="italic text-charcoal-soft" lang={item.language ?? undefined}>{item.title}</span>
              </span>
            </div>
          )}

          {/* summary: AI summary (labelled) or the publisher's own excerpt */}
          {d.summary ? (
            <>
              <div className="mt-3 text-[1rem] leading-relaxed text-charcoal-soft" title={t('news.card.aiSummaryTip', { model: aiModel })}>
                <span className="mr-1.5 align-[2px]"><AiBadge label={t('news.card.aiSummary')} /></span>
                {d.summary}
              </div>
              {excerpt && (
                <button type="button" className="mt-1.5 inline-flex items-center gap-1 text-[0.85rem] text-forest-700 hover:underline"
                  onClick={() => setShowExcerpt((v) => !v)} aria-expanded={showExcerpt}>
                  {showExcerpt ? t('news.card.hideExcerpt') : t('news.card.showExcerpt')}
                  <ChevronDown size={14} className={clsx('transition-transform', showExcerpt && 'rotate-180')} />
                </button>
              )}
              {showExcerpt && excerptBlock}
            </>
          ) : excerptBlock}

          {/* tags */}
          {(item.countries.length > 0 || item.topics.length > 0) && (
            <div className="mt-3.5 flex flex-wrap items-center gap-1.5">
              {item.countries.map((c) => (
                <TagButton key={c} tone="country" active={actions.activeCountries.includes(c)}
                  title={t('news.card.filterCountry', { x: country(c) })} onClick={() => actions.onCountry(c)}>
                  {country(c)}
                </TagButton>
              ))}
              {item.countries.length > 0 && item.topics.length > 0 && <span className="mx-1 h-4 w-px bg-line" aria-hidden />}
              {item.topics.map((k) => (
                <TagButton key={k} tone="topic" active={actions.activeTopics.includes(k)}
                  title={t('news.card.filterTopic', { x: actions.topicLabel(k) })} onClick={() => actions.onTopic(k)}>
                  {actions.topicLabel(k)}
                </TagButton>
              ))}
            </div>
          )}

          {/* actions + feed provenance */}
          <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-[0.92rem]">
            <a href={item.url} target="_blank" rel="noreferrer" title={t('news.card.opensNewTab')}
              className="inline-flex items-center gap-1.5 font-medium text-forest-800 underline decoration-gold/50 underline-offset-[3px] hover:decoration-gold">
              {t('news.card.readOriginal')} <ExternalLink size={14} />
            </a>
            {canTranslate && (
              <button type="button" className="inline-flex items-center gap-1.5 text-forest-800 hover:underline disabled:opacity-60"
                onClick={() => actions.onTranslate(item)} disabled={actions.translating} title={t('news.card.translateTip')}>
                {actions.translating ? <Loader2 size={15} className="animate-spin" /> : <Languages size={15} />}
                {actions.translating ? t('news.card.translating') : t('news.card.translate')}
              </button>
            )}
            {nOutlets > 0 && (
              <button type="button" onClick={() => setShowOutlets((v) => !v)} aria-expanded={showOutlets}
                title={t('news.card.alsoByTip')}
                className="inline-flex items-center gap-1 text-charcoal-soft hover:text-forest-800">
                {nOutlets === 1 ? t('news.card.alsoBy1') : t('news.card.alsoBy', { n: nOutlets })}
                <ChevronDown size={15} className={clsx('transition-transform', showOutlets && 'rotate-180')} />
              </button>
            )}
            {item.source && (
              <span className="ml-auto flex min-w-0 items-center gap-2 text-[0.8rem] text-muted">
                <span className="truncate max-w-[20rem]" title={`${t('prov.source')}: ${item.source.name}${item.source.publisher ? ` (${item.source.publisher})` : ''}`}>
                  {t('news.card.via')} {item.source.name}
                </span>
                {item.reliability && <ReliabilityBadge reliability={item.reliability} />}
              </span>
            )}
          </div>
          {actions.translateError != null && (
            <div className="mt-2 text-[0.88rem] text-down">{translateErrorText(actions.translateError, t)}</div>
          )}
          {showOutlets && <Outlets outlets={outlets} />}
        </div>
        {item.image_url && <Thumb src={item.image_url} />}
      </div>
    </article>
  )
}
