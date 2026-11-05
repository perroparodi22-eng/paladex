// Choose the AI service and paste its key from the interface, instead of editing a file.
// The key is written to the .env file on this computer only (PUT /api/quality/keys/<setting>), is
// never shown again, and applies at once: /api/assistant/status reflects it without a restart.
// Shown on the Assistant page and on the Sources page; never in the read-only online copy.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Check, ExternalLink, KeyRound, ShieldCheck } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { Panel } from '@/components/ui'
import { useI18n } from '@/i18n'
import { api, ApiError } from '@/lib/api'
import { isMirror } from '@/lib/mirror'
import type { AssistantStatus } from './types'

export type AiProvider = 'anthropic' | 'openai' | 'none'
const PROVIDERS: AiProvider[] = ['anthropic', 'openai', 'none']
const SIGNUP: Record<Exclude<AiProvider, 'none'>, string> = {
  anthropic: 'https://console.anthropic.com',
  openai: 'https://platform.openai.com/api-keys',
}

/** Provider choice + key field + save. `status` comes from /api/assistant/status. */
export function AiKeyForm({ status }: { status: AssistantStatus }) {
  const { t } = useI18n()
  const qc = useQueryClient()
  const current: AiProvider = status.provider_setting ?? (status.provider_configured ? (status.provider as AiProvider) : 'none')
  const [provider, setProvider] = useState<AiProvider>(current)
  const [key, setKey] = useState('')
  useEffect(() => { setProvider(current) }, [current])
  const saved = provider !== 'none' && Boolean(status.keys_saved?.[provider])
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['assistant'] })
    qc.invalidateQueries({ queryKey: ['meta'] })
    qc.invalidateQueries({ queryKey: ['settings'] })
  }
  const save = useMutation({
    mutationFn: async () => {
      if (provider !== 'none' && key.trim()) await api.put(`/quality/keys/${provider}_api_key`, { value: key.trim() })
      await api.put('/quality/keys/llm_provider', { value: provider })
    },
    onSuccess: () => { setKey(''); refresh() },
  })
  const forget = useMutation({
    mutationFn: () => api.put(`/quality/keys/${provider}_api_key`, { value: '' }),
    onSuccess: refresh,
  })
  const canSave = provider === 'none' || saved || key.trim().length > 0
  const changed = provider !== current || key.trim().length > 0
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (canSave && changed) save.mutate()
  }
  return (
    <form onSubmit={submit} className="space-y-3 text-[0.9rem] text-charcoal-soft">
      <fieldset>
        <legend className="mb-1.5 font-medium text-charcoal">{t('assistant.key.provider')}</legend>
        <div className="flex flex-wrap gap-2" role="radiogroup">
          {PROVIDERS.map((p) => (
            <label key={p} className={clsx('flex cursor-pointer items-center gap-2 rounded-sm border px-3 py-1.5',
              provider === p ? 'border-forest-600 bg-forest-50 text-forest-900' : 'border-line bg-white hover:border-forest-600')}>
              <input type="radio" name="ai-provider" value={p} checked={provider === p} className="accent-forest-700"
                onChange={() => { setProvider(p); save.reset() }} />
              {t(`assistant.key.p.${p}`)}
            </label>
          ))}
        </div>
      </fieldset>
      {provider !== 'none' && (
        <div className="space-y-1.5">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {saved
              ? <span className="inline-flex items-center gap-1 text-forest-700"><Check size={15} /> {t('assistant.key.saved')}</span>
              : <span className="text-warn">{t('assistant.key.none')}</span>}
            <a href={SIGNUP[provider]} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-1 text-[0.85rem]">
              {t('assistant.key.get', { service: t(`assistant.key.p.${provider}`) })} <ExternalLink size={12} />
            </a>
            {saved && (
              <button type="button" className="text-[0.85rem] text-muted underline hover:text-down" onClick={() => forget.mutate()}
                disabled={forget.isPending}>{t('assistant.key.forget')}</button>
            )}
          </div>
          <input
            type="password" autoComplete="off" spellCheck={false} value={key}
            onChange={(e) => { setKey(e.target.value); save.reset() }}
            placeholder={t(saved ? 'assistant.key.replace' : 'assistant.key.paste', { prefix: provider === 'anthropic' ? 'sk-ant-' : 'sk-' })}
            aria-label={t('assistant.key.paste', { prefix: provider === 'anthropic' ? 'sk-ant-' : 'sk-' })}
            className="field w-full max-w-md !py-2 bg-white"
          />
        </div>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <button type="submit" className="btn-primary !py-1.5" disabled={!canSave || !changed || save.isPending}>
          {save.isPending ? t('assistant.key.saving') : t('assistant.key.save')}
        </button>
        {save.isSuccess && (
          <span className="inline-flex items-center gap-1 text-forest-700">
            <Check size={15} /> {provider === 'none' ? t('assistant.key.doneOff') : t('assistant.key.done')}
          </span>
        )}
        {(save.isError || forget.isError) && (
          <span className="text-down">
            {save.error instanceof ApiError && save.error.status === 422 ? t('assistant.key.invalid') : t('assistant.key.error')}
          </span>
        )}
      </div>
      <ul className="space-y-1 border-t border-line-soft pt-2.5 text-[0.82rem] text-muted">
        <li>{t('assistant.key.paid')}</li>
        <li>{t('assistant.key.offers')}</li>
        <li className="flex items-start gap-1.5"><ShieldCheck size={14} className="mt-[0.15rem] shrink-0" /> {t('assistant.key.private')}</li>
      </ul>
    </form>
  )
}

/** The same form in its own panel (Sources page). Nothing in the read-only online copy. */
export function AiKeyPanel() {
  const { t } = useI18n()
  const status = useQuery({
    queryKey: ['assistant', 'status'],
    queryFn: () => api.get<AssistantStatus>('/assistant/status'),
    enabled: !isMirror(),
  })
  if (isMirror() || !status.data) return null
  const s = status.data
  return (
    <Panel title={<span className="inline-flex items-center gap-2"><KeyRound size={17} className="text-gold-dark" />{t('assistant.key.title')}</span>}
      eyebrow={s.llm_enabled ? t('assistant.key.stateOn', { provider: s.provider ?? '', model: s.model ?? '' }) : t('assistant.key.stateOff')}>
      <AiKeyForm status={s} />
    </Panel>
  )
}
