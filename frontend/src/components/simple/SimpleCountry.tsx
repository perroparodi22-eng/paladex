// Country page, simple view: "2026 finora" for both flows in one panel, ahead of production and the
// unofficial sources; the long tables live under "Mostra dettagli" (pages/CountryDetail.tsx).
import { Panel } from '@/components/ui'
import { ProfileYtd } from '@/components/countries/ProfileYtd'
import type { CountryProfile } from '@/components/countries/types'
import { useI18n } from '@/i18n'

export function CountryYtdPanel({ p, name }: { p: CountryProfile; name: string }) {
  const { t } = useI18n()
  const exp = p.trade.export.ytd
  const imp = p.trade.import.ytd
  // the year the figures belong to (in January the newest monthly data are still last year's)
  const year = exp?.own?.year ?? imp?.own?.year ?? (Number(p.today?.slice(0, 4)) || new Date().getFullYear())
  if (!exp && !imp) return null
  return (
    <Panel title={t('simple.country.ytdTitle', { y: year })} eyebrow={t('simple.country.ytdEyebrow')} className="mb-5">
      <div className="grid gap-5 xl:grid-cols-2" data-simple-ytd>
        {exp && (
          <div className="min-w-0">
            <h3 className="mb-2 font-sans text-[1.05rem] font-semibold text-forest-800">{t('simple.country.exports')}</h3>
            <ProfileYtd s={exp} flow="export" name={name} today={p.today} />
          </div>
        )}
        {imp && (
          <div className="min-w-0">
            <h3 className="mb-2 font-sans text-[1.05rem] font-semibold text-forest-800">{t('simple.country.imports')}</h3>
            <ProfileYtd s={imp} flow="import" name={name} today={p.today} />
          </div>
        )}
      </div>
    </Panel>
  )
}
