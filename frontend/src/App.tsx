import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import { Shell } from '@/components/layout/Shell'
import { Loading } from '@/components/ui'

const Overview = lazy(() => import('@/pages/Overview'))
const Prices = lazy(() => import('@/pages/Prices'))
const News = lazy(() => import('@/pages/News'))
const Countries = lazy(() => import('@/pages/Countries'))
const CountryDetail = lazy(() => import('@/pages/CountryDetail'))
const Trade = lazy(() => import('@/pages/Trade'))
const Companies = lazy(() => import('@/pages/Companies'))
const Sources = lazy(() => import('@/pages/Sources'))
const SearchPage = lazy(() => import('@/pages/Search'))
const Regulations = lazy(() => import('@/pages/Regulations'))
const Harvest = lazy(() => import('@/pages/Harvest'))
const Quotes = lazy(() => import('@/pages/Quotes'))
const Alerts = lazy(() => import('@/pages/Alerts'))
const Archive = lazy(() => import('@/pages/Archive'))
const Assistant = lazy(() => import('@/pages/Assistant'))
const Later = lazy(() => import('@/pages/Later'))

export default function App() {
  return (
    <Shell>
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/prezzi" element={<Prices />} />
          <Route path="/notizie" element={<News />} />
          <Route path="/paesi" element={<Countries />} />
          <Route path="/paesi/:iso3" element={<CountryDetail />} />
          <Route path="/commercio" element={<Trade />} />
          <Route path="/aziende" element={<Companies />} />
          <Route path="/fonti" element={<Sources />} />
          <Route path="/cerca" element={<SearchPage />} />
          <Route path="/raccolti" element={<Harvest />} />
          <Route path="/normative" element={<Regulations />} />
          <Route path="/offerte" element={<Quotes />} />
          <Route path="/avvisi" element={<Alerts />} />
          <Route path="/archivio" element={<Archive />} />
          <Route path="/assistente" element={<Assistant />} />
          <Route path="*" element={<Later section="notfound" />} />
        </Routes>
      </Suspense>
    </Shell>
  )
}
