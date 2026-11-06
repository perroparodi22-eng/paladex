// Requests of the corrections API, shared by the badge, the figure dialog, the "Scrivi a Paladex" box,
// the country notes and the sync status. Every write refreshes the views that show figures.
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { api, ApiError } from '@/lib/api'
import { isMirror } from '@/lib/mirror'
import type { Lang } from '@/lib/types'
import type { CorrErrorDetail, CorrectionEvent, CorrectionsList, CorrSettings, CorrSettingsSaved, CreateBody, Interpretation, SyncState } from './types'

/** The {code, message_it, message_en} of an error answer (lib/api.ts keeps `detail` as JSON text). */
export function errorDetail(e: unknown): CorrErrorDetail | null {
  if (!(e instanceof ApiError)) return null
  try {
    const d = JSON.parse(e.message)
    return d && typeof d === 'object' && typeof d.code === 'string' ? (d as CorrErrorDetail) : null
  } catch {
    return null
  }
}

/** The error in the interface language, else the raw message. */
export function errorText(e: unknown, lang: Lang): string {
  const d = errorDetail(e)
  if (d) return (lang === 'en' ? d.message_en : d.message_it) ?? d.message_it ?? d.code
  return e instanceof Error ? e.message : String(e)
}

/** After a correction, a revert or a note: every view that shows figures reads them again. */
export function refreshFigures(qc: QueryClient): Promise<void> {
  return qc.invalidateQueries({
    predicate: (q) => ['overview', 'prices', 'countries', 'trade', 'corrections', 'quality', 'archive', 'harvest', 'assistant']
      .includes(String(q.queryKey[0])),
  })
}

export function useCorrSettings() {
  return useQuery({
    queryKey: ['corrections', 'settings'],
    queryFn: () => api.get<CorrSettings>('/corrections/settings'),
    enabled: !isMirror(),
    staleTime: 5 * 60_000,
  })
}

export function useSaveAuthor() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (author: string) => api.put<{ author: string }>('/corrections/settings', { author }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['corrections'] }),
  })
}

/** "Scambia le correzioni con gli altri computer": on or off on THIS computer (written to its .env). */
export function useSaveSync() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (sync: boolean) => api.put<CorrSettingsSaved>('/corrections/settings', { sync }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['corrections'] }),
  })
}

export function useSyncState() {
  return useQuery({
    queryKey: ['corrections', 'sync'],
    queryFn: () => api.get<SyncState>('/corrections/sync'),
    enabled: !isMirror(),
    refetchInterval: (q) => (q.state.data?.running ? 3000 : 60_000),
  })
}

export function useSyncNow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<SyncState>('/corrections/sync', {}),
    onSuccess: (data) => {
      qc.setQueryData(['corrections', 'sync'], data)
      return refreshFigures(qc)
    },
  })
}

export function useCorrections(params: Record<string, string | number | undefined>, enabled = true) {
  return useQuery({
    queryKey: ['corrections', 'list', params],
    queryFn: () => api.get<CorrectionsList>('/corrections', params),
    enabled: enabled && !isMirror(),
  })
}

export function useCreateCorrection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateBody) => api.post<{ event: CorrectionEvent; figure: unknown }>('/corrections', body),
    onSuccess: () => refreshFigures(qc),
  })
}

export function useRevert() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ eventId, reason }: { eventId: string; reason?: string }) =>
      api.post<{ event: CorrectionEvent; reverted: CorrectionEvent | null }>(`/corrections/${encodeURIComponent(eventId)}/revert`, { reason }),
    onSuccess: () => refreshFigures(qc),
  })
}

export function useInterpret() {
  return useMutation({
    mutationFn: (body: { text: string; lang: Lang; context?: { table: string; row_id: number } }) =>
      api.post<Interpretation>('/corrections/interpret', body),
  })
}
