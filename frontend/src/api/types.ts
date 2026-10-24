export type Uuid = string
export type IsoDateTime = string 

export type DocumentType = 'contract' | 'invoice' | 'payment_request' | 'unknown'


export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed'
export type JobStep = 'ai_analysis' | 'completed' | 'failed'

export type AlertSeverity = 'info' | 'warning' | 'error'
export type AlertStatus = 'open' | 'resolved' | 'ignored'
export type RuleCode =
  | 'MISSING_DOCUMENT_TYPE'
  | 'MISSING_REQUIRED_FIELD'
  | 'CONTRACT_NUMBER_MISMATCH'
  | 'INVOICE_NUMBER_MISMATCH'
  | 'TAX_ID_MISMATCH'
  | 'TOTAL_AMOUNT_MISMATCH'
  | 'PAYMENT_AMOUNT_MISMATCH'
  | 'CURRENCY_MISMATCH'
  | 'INVOICE_TOTAL_MISMATCH'
  | 'VAT_AMOUNT_MISMATCH'
  | 'AMOUNT_IN_WORDS_MISMATCH'
  | 'AMOUNT_IN_WORDS_UNVERIFIABLE'

export interface Dossier {
  id: Uuid
  name: string
  status: string
  created_at: IsoDateTime
  updated_at: IsoDateTime
}

export interface FileUploadResponse {
  dossier_id: Uuid
  source_file_id: Uuid
  job_id: Uuid
  original_name: string
  media_type: string
  size_bytes: number
  sha256: string
  job_status: JobStatus
}

export interface ProcessingJob {
  id: Uuid
  dossier_id: Uuid
  source_file_id: Uuid | null
  job_type: string
  status: JobStatus
  current_step: JobStep | null
  progress: number
  attempts: number
  error_message: string | null
  created_at: IsoDateTime
  updated_at: IsoDateTime
  started_at: IsoDateTime | null
  finished_at: IsoDateTime | null
}


export interface BoundingBox {
  x1: number
  y1: number
  x2: number
  y2: number
}


export interface ExtractedField {
  name: string 
  raw_value: string | null
  normalized_value: string | null
  confidence: number // 0..1
  page: number | null
  bbox: BoundingBox | null
  evidence_text: string | null
  source: string
  needs_review: boolean
}

export interface OcrBlock {
  page: number
  text: string
  confidence: number
  bbox: BoundingBox
}

export interface AnalyzedDocument {
  document_type: DocumentType
  classification_confidence: number
  pages: number[]
  fields: ExtractedField[]
  ocr_blocks: OcrBlock[]
}

export interface AnalysisResult {
  documents: AnalyzedDocument[]
  engine_version: string
  processing_time_ms: number
}

export interface Alert {
  id: Uuid
  dossier_id: Uuid
  rule_code: RuleCode
  severity: AlertSeverity
  status: AlertStatus
  message: string
  source_document_id: Uuid | null
  target_document_id: Uuid | null
  field_name: string | null
  expected_value: string | null
  actual_value: string | null
  details: Record<string, unknown>
  created_at: IsoDateTime
  resolved_at: IsoDateTime | null
}

export interface ReconcileResponse {
  dossier_id: Uuid
  alert_count: number
  severity_counts: Partial<Record<AlertSeverity, number>> 
  rule_counts: Partial<Record<RuleCode, number>>
  alerts: Alert[]
}

export interface AlertListResponse {
  dossier_id: Uuid
  count: number
  alerts: Alert[]
}


export interface SearchParams {
  q?: string
  document_type?: DocumentType
  field_name?: string
  min_confidence?: number
  limit?: number
  offset?: number
}

export interface SearchMatch {
  source: 'extracted_field' | 'ocr_block'
  field_name: string | null
  text: string
  page_number: number | null
  confidence: number
}

export interface SearchResult {
  document_id: Uuid
  source_file_id: Uuid
  original_name: string
  document_type: DocumentType
  classification_confidence: number
  page_numbers: number[]
  created_at: IsoDateTime
  matches: SearchMatch[]
}

export interface SearchResponse {
  query: string | null
  document_type: DocumentType | null
  field_name: string | null
  count: number
  limit: number
  offset: number
  results: SearchResult[]
}