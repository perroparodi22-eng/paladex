// /notizie, simple view: one article per row — headline, source, date and one line of summary
// (AI text labelled as such), with the link to the original. Filters stay one click away.
import { ExternalLink } from 'lucide-react'
import { AiBadge, DemoBadge } from '@/components/ui'
import { fmtNewsDate, utc } from '@/components/news/bits'
import type { NewsItem } from '@/components/news/types'
import { useI18n } from '@/i18n'
import { fmtAgo } from '@/lib/format'
import { pageUrl } from '@/lib/links'
import { shortSource } from '@/lib/plain'

export function SimpleNewsItem({ item }: { item: NewsItem }) {
  const { t, lang } = useI18n()
  const d = item.display[lang]
  const summary = d.summary ?? d.excerpt
  const fullOutlet = item.publisher || item.source?.publisher || item.source?.name || '—'
  const outlet = shortSource({ key: '', name: fullOutlet, publisher: fullOutlet }, lang)
  const when = item.published_at
    ? fmtNewsDate(item.published_at, lang)
    : t('news.card.collected', { ago: fmtAgo(utc(item.collected_at), lang) })
  const href = pageUrl(item.url) ?? undefined
  return (
    <article className="px-4 py-4 sm:px-6" aria-labelledby={`snews-${item.id}`} data-simple-news={item.id}>
      <h3 id={`snews-${item.id}`} className="font-serif text-[1.2rem] font-semibold leading-snug text-charcoal sm:text-[1.25rem]">
        <a href={href} target="_blank" rel="noreferrer" className="decoration-gold/60 underline-offset-[3px] hover:text-forest-800 hover:underline"
          lang={d.title_is_ai ? lang : item.language ?? undefined}>
          {d.title}
        </a>
      </h3>
      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.92rem] text-muted">
        {item.is_demo && <DemoBadge />}
        <span className="font-medium text-charcoal-soft" title={fullOutlet}>{outlet}</span>
        <span aria-hidden>·</span>
        <time dateTime={utc(item.published_at ?? item.collected_at) ?? undefined}>{when}</time>
        {(d.title_is_ai || (d.summary && d.summary_is_ai)) && <AiBadge />}
      </div>
      {summary && (
        <p className="mt-1.5 line-clamp-2 text-[1rem] sm:line-clamp-1 leading-snug text-charcoal-soft" lang={d.summary ? lang : item.language ?? undefined}>{summary}</p>
      )}
      <a href={href} target="_blank" rel="noreferrer" className="link mt-1.5 inline-flex items-center gap-1 text-[0.95rem]">
        {t('simple.news.read')} <ExternalLink size={14} />
      </a>
    </article>
  )
}
