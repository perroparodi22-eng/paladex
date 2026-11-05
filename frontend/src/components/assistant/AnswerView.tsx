// One answer of the assistant: what was understood, the sections (facts with citation chips, or the
// AI's text with its badges), data notes and warnings, the automatic check and the cited sources.
import clsx from 'clsx'
import { Database, ExternalLink, Lock, ShieldCheck, Sparkles } from 'lucide-react'
import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { AiBadge, Badge, DemoBadge, Note } from '@/components/ui'
import { useI18n } from '@/i18n'
import { fmtDate, fmtPeriod } from '@/lib/format'
import { Citations } from './Citation'
import type { Answer, AnswerSection, AssistantFact, FactStatus, HowToEnable } from './types'
import { pageUrl } from '@/lib/links'

type Tone = 'forest' | 'neutral' | 'warn' | 'outline' | 'gold'
const SECTION_TONE: Record<string, Tone> = { verified: 'forest', historical: 'neutral', estimates: 'warn', news: 'outline', quotes: 'gold' }
const ITEM_TAG: Partial<Record<FactStatus, { key: string; tone: Tone }>> = {
  provisional: { key: 'assistant.badge.provisional', tone: 'warn' },
  verified_industry: { key: 'assistant.badge.industry', tone: 'gold' },
}

export function SectionBadge({ section }: { section: AnswerSection }) {
  const { t } = useI18n()
  if (section.key === 'analysis' || section.key === 'forecast') return <AiBadge label={t(`assistant.badge.${section.key}`)} />
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <Badge tone={SECTION_TONE[section.key] ?? 'neutral'}>{t(`assistant.badge.${section.key}`)}</Badge>
      {section.ai && <AiBadge label={t('assistant.badge.aiText')} />}
    </span>
  )
}

function Section({ section, facts, plain }: { section: AnswerSection; facts: Map<number, AssistantFact>; plain: boolean }) {
  const { t } = useI18n()
  const analysis = section.key === 'analysis' || section.key === 'forecast'
  return (
    <section className={clsx('min-w-0', analysis && 'border-l-2 border-[#D7D0EA] bg-[#F7F5FB] py-3 pl-3 pr-2 sm:pl-4')}>
      <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1">
        <h3 className="font-serif text-[1.08rem] font-semibold">{section.title}</h3>
        <SectionBadge section={section} />
      </div>
      {analysis && <p className="mb-2 text-[0.8rem] text-[#4B3F7A]">{t(`assistant.badge.${section.key}Note`)}</p>}
      <ul className={clsx('space-y-2', plain && 'divide-y divide-line-soft [&>li]:pt-2 [&>li:first-child]:pt-0')}>
        {section.items.map((it, i) => {
          const tag = plain && it.status ? ITEM_TAG[it.status] : undefined
          return (
            <li key={i} className="break-words text-[0.98rem] leading-relaxed text-charcoal">
              {tag && <Badge tone={tag.tone} className="mr-1.5 align-[0.1em]">{t(tag.key)}</Badge>}
              {it.text}
              <Citations refs={it.refs} facts={facts} />
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function SourcesList({ facts }: { facts: AssistantFact[] }) {
  const { t, lang } = useI18n()
  return (
    <details className="group border-t border-line-soft pt-3">
      <summary className="cursor-pointer select-none text-sm font-medium text-forest-800 hover:text-forest-900">
        {t('assistant.answer.sources', { n: facts.length })}
      </summary>
      <ol className="mt-2 space-y-2">
        {facts.map((f) => (
          <li key={f.id} className="grid grid-cols-[2rem_minmax(0,1fr)] gap-x-2 text-[0.85rem]">
            <span className="num pt-[0.1rem] text-gold-dark">[{f.id}]</span>
            <div className="min-w-0 break-words">
              <div className="text-charcoal-soft">{f.title}</div>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.78rem] text-muted">
                {f.private ? (
                  <span className="inline-flex items-center gap-1"><Lock size={12} /> {t('assistant.cite.private')}</span>
                ) : (
                  <span className="font-medium text-charcoal-soft">{f.source_name || t('assistant.cite.noSource')}</span>
                )}
                {f.published_at && <span>· {t('assistant.cite.published', { date: fmtDate(f.published_at, lang) })}</span>}
                {f.period_label && f.kind !== 'news' && <span>· {t('assistant.cite.period', { p: fmtPeriod(f.period_label, lang) })}</span>}
                <span>· {f.status_label}</span>
                {f.is_demo && <DemoBadge />}
                {f.url && !f.private && (
                  <a href={pageUrl(f.url) ?? undefined} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-0.5">
                    {t('prov.original')} <ExternalLink size={11} />
                  </a>
                )}
                {f.link && <Link to={f.link} className="text-forest-700 hover:text-forest-900">{t('assistant.cite.openApp')} →</Link>}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </details>
  )
}

export function HowToEnableBox({ how, title }: { how: HowToEnable; title?: string }) {
  return (
    <div className="rounded-sm border border-line bg-paper px-3 py-2.5 text-[0.85rem] text-charcoal-soft">
      {title && <div className="mb-1 font-medium text-charcoal">{title}</div>}
      <p>{how.text}</p>
      <pre className="mt-2 overflow-x-auto rounded-sm border border-line-soft bg-white px-2.5 py-1.5 font-mono text-[0.78rem] text-charcoal">
        {how.lines.join('\n')}
      </pre>
    </div>
  )
}

function Understood({ a }: { a: Answer }) {
  const { t, lang } = useI18n()
  const u = a.understood
  const parts = [
    ...u.countries.map((c) => c.name),
    ...u.varieties.map((v) => v.name),
    ...u.price_types.map((p) => p.name),
    ...u.topics.filter((x) => x.key !== 'compare').map((x) => x.name),
    ...(u.period ? [lang === 'it' ? u.period.label_it : u.period.label_en] : []),
  ]
  if (!parts.length) return null
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1.5 text-[0.78rem] text-muted">
      <span>{t('assistant.answer.understood')}:</span>
      {[...new Set(parts)].map((p) => (
        <span key={p} className="rounded-sm border border-line-soft bg-paper px-1.5 py-[1px] text-charcoal-soft">{p}</span>
      ))}
    </div>
  )
}

export function AnswerView({ answer: a }: { answer: Answer }) {
  const { t } = useI18n()
  const facts = useMemo(() => new Map(a.facts.map((f) => [f.id, f])), [a.facts])
  const kept = a.sections.reduce((n, s) => n + s.items.length, 0)
  return (
    <div className="min-w-0 space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {a.ai_used
          ? <span title={t('assistant.answer.aiTitle', { model: a.ai.model ?? '' })}><AiBadge label={t('assistant.answer.ai')} /></span>
          : <Badge tone="forest" title={t('assistant.answer.noAiTitle')}><Database size={11} /> {t('assistant.answer.noAi')}</Badge>}
        {a.is_demo && <DemoBadge />}
        {a.insufficient && <Badge tone="warn">{t('assistant.answer.insufficient')}</Badge>}
        <Understood a={a} />
      </div>

      <p className="break-words font-serif text-[1.05rem] leading-snug text-charcoal">{a.intro}</p>

      {a.warnings.map((w, i) => <Note key={i} tone="warn">{w}</Note>)}
      {a.insufficient_note && <Note tone="warn">{a.insufficient_note}</Note>}
      {a.notes.length > 0 && (
        <Note>
          <div className="font-medium">{t('assistant.answer.notes')}</div>
          <ul className="mt-0.5 list-disc space-y-0.5 pl-4">
            {a.notes.map((n, i) => <li key={i} className="break-words">{n}</li>)}
          </ul>
        </Note>
      )}

      {a.sections.map((s) => <Section key={s.key} section={s} facts={facts} plain={!a.ai_used} />)}

      {(a.private_data_used || a.sent_private_to_ai) && (
        <p className="flex items-start gap-1.5 text-[0.8rem] text-muted">
          <Lock size={13} className="mt-0.5 shrink-0" />
          {a.sent_private_to_ai ? t('assistant.answer.privateSent') : t('assistant.answer.private')}
        </p>
      )}
      {a.checks && a.ai_used && (
        <p className="flex items-start gap-1.5 text-[0.8rem] text-muted">
          <ShieldCheck size={14} className="mt-0.5 shrink-0 text-forest-600" />
          {a.checks.dropped
            ? t('assistant.answer.checksDropped', { kept, dropped: a.checks.dropped })
            : t('assistant.answer.checks', { kept })}
        </p>
      )}
      {a.how_to_enable && a.facts.length > 0 && (
        <p className="flex items-start gap-1.5 text-[0.8rem] text-muted">
          <Sparkles size={13} className="mt-0.5 shrink-0" />
          <span className="min-w-0 break-words">{t('assistant.answer.howToEnable')}. {a.how_to_enable.text}</span>
        </p>
      )}
      {a.facts.length > 0 && <SourcesList facts={a.facts} />}
    </div>
  )
}
