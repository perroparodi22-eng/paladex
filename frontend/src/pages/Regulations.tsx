// /normative — import duties on honey by origin (EU TARIC via the UK XI mirror, US HTS, US anti-dumping
// cases linked to the Federal Register) and the official documents collected from government sources.
import { useQuery } from '@tanstack/react-query'
import { DocumentsPanel } from '@/components/regulations/DocumentsPanel'
import { DutyMatrix } from '@/components/regulations/DutyMatrix'
import type { DutiesResponse } from '@/components/regulations/types'
import { ErrorBlock, Loading, PageHeader, Panel } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'

export default function Regulations() {
  const { t } = useI18n()
  const duties = useQuery({ queryKey: ['regulations', 'duties'], queryFn: () => api.get<DutiesResponse>('/regulations/duties') })
  return (
    <div className="space-y-6">
      <PageHeader eyebrow={t('regulations.eyebrow')} title={t('regulations.title')} subtitle={t('regulations.subtitle')} />
      {duties.isLoading ? (
        <Panel title={t('regulations.duties.title')}><Loading /></Panel>
      ) : duties.error ? (
        <Panel title={t('regulations.duties.title')}><ErrorBlock error={duties.error} onRetry={() => duties.refetch()} /></Panel>
      ) : duties.data ? (
        <DutyMatrix d={duties.data} />
      ) : null}
      <DocumentsPanel />
    </div>
  )
}
