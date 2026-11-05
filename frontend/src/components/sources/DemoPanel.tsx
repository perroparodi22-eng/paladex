// "Dati dimostrativi": explains demo data, shows whether it is present/visible, load / remove / show / hide.
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Eye, EyeOff, FlaskConical, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Badge, DemoBadge } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api } from '@/lib/api'
import { fmtNumber } from '@/lib/format'
import type { QualitySummary } from './types'
import { ConfirmDialog } from './widgets'

export function DemoPanel({ demo, onNotice }: {
  demo: QualitySummary['demo']; onNotice: (n: { tone: 'ok' | 'warn'; text: string }) => void
}) {
  const { t, lang } = useI18n()
  const qc = useQueryClient()
  const [confirm, setConfirm] = useState<'load' | 'remove' | null>(null)
  const fail = (e: unknown) => onNotice({ tone: 'warn', text: e instanceof Error ? e.message : String(e) })

  const load = useMutation({
    mutationFn: () => api.post<{ inserted: number }>('/demo/seed'),
    onSuccess: (r) => { setConfirm(null); onNotice({ tone: 'ok', text: t('sources.demo.loaded', { n: fmtNumber(r.inserted, lang) }) }); qc.invalidateQueries() },
    onError: fail,
  })
  const remove = useMutation({
    mutationFn: () => api.del<{ deleted: number }>('/demo'),
    onSuccess: (r) => { setConfirm(null); onNotice({ tone: 'ok', text: t('sources.demo.removed', { n: fmtNumber(r.deleted, lang) }) }); qc.invalidateQueries() },
    onError: fail,
  })
  const visibility = useMutation({
    mutationFn: (show: boolean) => api.put('/settings', { show_demo: show }),
    onSuccess: () => qc.invalidateQueries(),
    onError: fail,
  })

  const present = demo.total > 0
  const status = !present ? t('sources.demo.statusNone') : demo.visible ? t('sources.demo.statusVisible') : t('sources.demo.statusHidden')

  return (
    <section className="panel" aria-labelledby="demo-title">
      <div className="panel-head">
        <h2 id="demo-title" className="panel-title flex items-center gap-2"><FlaskConical size={19} className="text-[#9A2A17]" />{t('sources.demo.title')}</h2>
        <DemoBadge />
      </div>
      <div className="p-6 grid gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] items-start">
        <p className="text-[0.98rem] leading-relaxed text-charcoal-soft">{t('sources.demo.what')}</p>
        <div className="rounded-sm border border-line-soft bg-paper px-4 py-3.5">
          <div className="flex items-center gap-2">
            <Badge tone={present && demo.visible ? 'demo' : 'outline'}>{status}</Badge>
          </div>
          {present && <div className="mt-1.5 text-sm text-muted num">{t('sources.demo.rows', { n: fmtNumber(demo.total, lang) })}</div>}
          <div className="mt-3 flex flex-wrap gap-2">
            {!present ? (
              <button className="btn-secondary" onClick={() => setConfirm('load')}><Plus size={16} /> {t('sources.demo.load')}</button>
            ) : (
              <>
                <button className="btn-secondary" onClick={() => visibility.mutate(!demo.visible)} disabled={visibility.isPending}>
                  {demo.visible ? <EyeOff size={16} /> : <Eye size={16} />} {demo.visible ? t('sources.demo.hide') : t('sources.demo.show')}
                </button>
                <button className="btn-secondary !text-down hover:!border-down" onClick={() => setConfirm('remove')}>
                  <Trash2 size={16} /> {t('sources.demo.remove')}
                </button>
              </>
            )}
          </div>
        </div>
      </div>
      <ConfirmDialog
        open={confirm === 'load'}
        title={t('sources.demo.confirmLoadTitle')}
        body={t('sources.demo.confirmLoadBody')}
        confirmLabel={t('sources.demo.load')}
        busy={load.isPending}
        onConfirm={() => load.mutate()}
        onCancel={() => setConfirm(null)}
      />
      <ConfirmDialog
        open={confirm === 'remove'}
        title={t('sources.demo.confirmRemoveTitle')}
        body={t('sources.demo.confirmRemoveBody', { n: fmtNumber(demo.total, lang) })}
        confirmLabel={t('sources.demo.remove')}
        danger
        busy={remove.isPending}
        onConfirm={() => remove.mutate()}
        onCancel={() => setConfirm(null)}
      />
    </section>
  )
}
