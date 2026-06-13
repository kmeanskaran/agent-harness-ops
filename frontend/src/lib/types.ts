export type Platform = 'x' | 'linkedin' | 'devto'

export const PLATFORM_META: Record<Platform, { label: string; description: string }> = {
  x:        { label: 'X Thread',        description: '6–10 tweets, 200–280 chars each' },
  linkedin: { label: 'LinkedIn Post',   description: '150–300 word post' },
  devto:    { label: 'Article',         description: '1000–1500 word article' },
}

export interface CachedResult {
  xThread?: string[]
  linkedinPost?: string
  devtoArticle?: string
}

export interface ActiveJob {
  jobId: string
  tabId: string
  platforms: Platform[]
  fingerprint: string
  status: string
  currentStep: string
  threadId?: string
  parentJobId?: string | null
}

export interface JobStatusResponse {
  job_id: string
  status: string
  current_step?: string
  thread_id?: string
  parent_job_id?: string | null
  x_thread?: string[]
  linkedin_post?: string
  devto_article?: string
  error?: string
}

export interface JobResponse {
  job_id: string
  status: string
  thread_id?: string
  parent_job_id?: string | null
}

export interface FormValues {
  email: string
  readme: string
  learnings: string
  hardParts: string
  tone: string
  audience: string
}

export interface UserProfileResponse {
  email: string
}

export interface HistoryItem {
  job_id: string
  project_id: string
  thread_id: string
  parent_job_id?: string | null
  status: string
  current_step?: string
  tone?: string | null
  audience?: string | null
  platforms: Platform[]
  readme: string
  learnings: string[]
  hard_parts: string[]
  x_thread?: string[]
  linkedin_post?: string
  devto_article?: string
  created_at: string
  updated_at: string
  error?: string | null
}

export interface HistoryResponse {
  email: string
  items: HistoryItem[]
}
