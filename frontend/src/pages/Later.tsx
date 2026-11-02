import { ComingSoon } from '@/components/ui'
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
  if (!s) return <ComingSoon title="404" milestone={0} description={t('later.notfound')} />
  return <ComingSoon title={t(s.nav)} milestone={s.milestone} description={t(`later.${section}`)} />
}
