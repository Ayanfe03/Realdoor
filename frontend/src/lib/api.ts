const API_BASE_URL = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000'

export type ApiEnvelope<T> = {
  ok: boolean
  data: T
  error: { code: string; message: string } | null
}

export type EvidenceField = {
  field: string
  value: string | number
  page: number
  bbox: number[]
  bbox_units: string
  confidence: number
  confirmed: boolean
  evidence_text?: string
  source: {
    document_id: string | null
    page: number
    bbox: number[]
    bbox_units: string
  }
}

export type EvidenceDocument = {
  document_id: string
  household_id: string
  document_type: string
  file_name: string
  contains_adversarial_text: boolean
  model_generated: boolean
  fields: EvidenceField[]
}

export type Assessment = {
  household_id: string
  household_size: number
  annualized_income: number
  income_sources: Array<{ kind: string; amount: number; frequency: string; annualized: number }>
  threshold: {
    household_size: number
    threshold: number
    effective_date: string
    hud_area: string
    fiscal_year: number
    source_pdf_page: number
    source_url: string
  }
  comparison: 'below_or_equal' | 'above' | 'no_frozen_threshold'
  readiness_status: 'READY_TO_REVIEW' | 'NEEDS_REVIEW'
  review_reasons: string[]
  missing_document_types: string[]
  citations: Array<{ rule_id: string; effective_date: string; source_url: string; source_locator: string }>
}

export type Packet = {
  session_id: string
  household_id: string
  documents: EvidenceDocument[]
  confirmations: Array<{
    document_id: string
    field: string
    original_value: string | number
    value: string | number
    corrected: boolean
    source: EvidenceField['source']
  }>
  action_log: Array<{
    action: string
    timestamp: string
    rule_version: string
    details: Record<string, unknown>
  }>
  assessment: Assessment
  decision_boundary: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: init?.body instanceof FormData ? init.headers : { 'Content-Type': 'application/json', ...init?.headers },
  })
  const payload = (await response.json()) as ApiEnvelope<T>
  if (!response.ok || !payload.ok) {
    throw new Error(payload.error?.message ?? `Request failed: ${response.status}`)
  }
  return payload.data
}

export const api = {
  health: () => request<{ openai_configured: boolean; model: string }>('/api/health'),
  createSession: () => request<{ session_id: string }>('/api/sessions', { method: 'POST' }),
  consent: (sessionId: string, granted = true) =>
    request<{ event: unknown }>('/api/sessions/consent', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, consent_type: 'process_synthetic_document', granted }),
    }),
  upload: (sessionId: string, file: File, householdId?: string) => {
    const form = new FormData()
    form.append('file', file)
    form.append('session_id', sessionId)
    if (householdId) form.append('household_id', householdId)
    form.append('use_model', 'true')
    return request<{
      mode: string
      file_name: string
      document?: EvidenceDocument
      attached_document?: EvidenceDocument
      validated?: { status: string; document: EvidenceDocument; abstentions: string[]; validation_errors: unknown[] }
      note: string
    }>('/api/extraction/upload', { method: 'POST', body: form })
  },
  confirmField: (sessionId: string, documentId: string, field: string, value: string | number) =>
    request<{ confirmation: unknown; assessment: Assessment }>('/api/sessions/confirm-field', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, document_id: documentId, field, value }),
    }),
  packet: (sessionId: string) =>
    request<Packet>('/api/sessions/packet', { method: 'POST', body: JSON.stringify({ session_id: sessionId }) }),
  rulesAnswer: (question: string, householdId?: string) =>
    request<{
      status: string
      answer: string
      qa_matches: Array<{ qa_id: string; question: string; answer: string; rule_ids: string[] }>
      abstentions: string[]
      citations: Array<{ rule_id: string; effective_date: string; source_url: string; source_locator: string }>
    }>('/api/rules/answer', { method: 'POST', body: JSON.stringify({ question, household_id: householdId }) }),
  copilot: (message: string, sessionId?: string) =>
    request<{ safety: { allowed: boolean; categories: string[]; message: string | null }; grounding?: unknown; answer: unknown }>(
      '/api/copilot',
      { method: 'POST', body: JSON.stringify({ message, session_id: sessionId }) },
    ),
  deleteSession: (sessionId: string) =>
    request<{ deleted: boolean }>('/api/sessions/delete', { method: 'POST', body: JSON.stringify({ session_id: sessionId }) }),
  exportUrl: () => `${API_BASE_URL}/api/sessions/export-file`,
}

export async function downloadPacket(sessionId: string, format: 'json' | 'html' | 'pdf') {
  const response = await fetch(api.exportUrl(), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, format }),
  })
  if (!response.ok) throw new Error(`Export failed: ${response.status}`)
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `realdoor-packet.${format}`
  anchor.click()
  URL.revokeObjectURL(url)
}
