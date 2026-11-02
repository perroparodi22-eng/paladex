// Friendly, step-by-step instructions to add a free API key to the .env file.
import { ExternalLink, KeyRound, ShieldCheck } from 'lucide-react'
import { pickLang, useI18n } from '@/i18n'
import type { ApiKeyInfo } from './types'

export function KeyHelp({ info, settingAttr, optional }: { info: ApiKeyInfo | undefined; settingAttr: string; optional: boolean }) {
  const { t, lang } = useI18n()
  const envVar = info?.env_var ?? `PALADEX_${settingAttr.toUpperCase()}`
  const help = info ? pickLang(info as unknown as Record<string, unknown>, 'help', lang) : null
  const code = (s: string) => <code className="num bg-white border border-line rounded-sm px-1.5 py-0.5 text-[0.85rem] text-charcoal">{s}</code>
  const step3 = t('sources.key.step3', { file: '\u0000', example: '\u0001' }).split(/(\u0000|\u0001)/)
  return (
    <div className="rounded-sm border border-gold-light/60 bg-[#FBF6E9] px-5 py-4">
      <div className="flex items-center gap-2 font-medium text-gold-dark">
        <KeyRound size={18} /> {t('sources.key.title')}
      </div>
      <p className="mt-1 text-[0.92rem] text-charcoal-soft">{optional ? t('sources.key.optional') : t('sources.key.required')}{help ? ` ${help}` : ''}</p>
      <ol className="mt-3 space-y-2 text-[0.95rem] text-charcoal-soft list-decimal pl-5 marker:text-gold-dark marker:font-medium">
        <li>
          {t('sources.key.step1')}{' '}
          {info?.signup_url ? (
            <a href={info.signup_url} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-1">
              {info.service ?? info.signup_url} <ExternalLink size={13} />
            </a>
          ) : (info?.service ?? '—')}
        </li>
        <li>{t('sources.key.step2')}</li>
        <li>{step3.map((part, i) => (part === '\u0000' ? <span key={i}>{code('.env')}</span> : part === '\u0001' ? <span key={i}>{code('.env.example')}</span> : part))}</li>
        <li>
          {t('sources.key.step4')}
          <div className="mt-1.5 num text-[0.92rem] bg-white border border-line rounded-sm px-3 py-2 overflow-x-auto whitespace-nowrap">
            <span className="text-charcoal">{envVar}=</span><span className="text-gold-dark">{t('sources.key.placeholder')}</span>
          </div>
        </li>
        <li>{t('sources.key.step5')}</li>
      </ol>
      <p className="mt-3 flex items-center gap-1.5 text-[0.82rem] text-muted"><ShieldCheck size={14} /> {t('sources.key.privacy')}</p>
    </div>
  )
}
