import { Link } from 'react-router-dom'
import { ComingSoon, EmptyState, PageHeader, Panel } from '@/components/ui'
import { useI18n } from '@/i18n'

const SECTIONS: Record<string, { nav: string; milestone: number }> = {
  harvest: { nav: 'nav.harvest', milestone: 5 },
  regulations: { nav: 'nav.regulations', milestone: 5 },
  quotes: { nav: 'nav.quotes', milestone: 7 },
  alerts: { nav: 'nav.alerts', milestone: 7 },
  archive: { nav: 'nav.archive', milestone: 7 },
  assistant: { nav: 'nav.assistant', milestone: 6 },
}

/** Sections scheduled for later milestones: an honest placeholder, never fake content. */
export default function Later({ section }: { section: string }) {
  const { t } = useI18n()
  const s = SECTIONS[section]
  // An unknown address is a broken link, not a section "in development".
  if (!s) {
    return (
      <div>
        <PageHeader title={t('later.notfoundTitle')} />
        <Panel>
          <EmptyState title={t('later.notfoundTitle')} hint={t('later.notfoundHint')}
            action={<Link to="/" className="btn-secondary">{t('later.notfoundHome')}</Link>} />
        </Panel>
      </div>
    )
  }
  return <ComingSoon title={t(s.nav)} milestone={s.milestone} description={t(`later.${section}`)} />
}
