// Sources page · "Correzioni e note": who signs, the synchronisation with the other computers, and
// every correction, flag and note with what happened to it (notices first). Anchor #correzioni.
import { Panel } from '@/components/ui'
import { useI18n } from '@/i18n'
import { CorrectionsList } from './CorrectionsPanel'
import { AuthorLine, SyncStatus, SyncSwitch } from './parts'

export function CorrectionsSection() {
  const { t } = useI18n()
  return (
    <div id="correzioni" className="scroll-mt-24">
      <Panel title={t('corrections.list.title')} eyebrow={t('corrections.form.eyebrow')}>
        <p className="-mt-1 mb-3 text-[0.95rem] text-muted">{t('corrections.list.sub')}</p>
        <div className="mb-4 space-y-1.5 rounded-sm border border-line-soft bg-paper px-3 py-2.5">
          <AuthorLine />
          <SyncStatus />
          <SyncSwitch className="pt-1" />
        </div>
        <CorrectionsList limit={50} />
      </Panel>
    </div>
  )
}
