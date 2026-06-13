import type { HistoryResponse, JobResponse, JobStatusResponse, UserProfileResponse } from './types'

const BASE = import.meta.env.VITE_API_URL ?? '/api'

function userHeaders(email?: string) {
  return {
    'Content-Type': 'application/json',
    ...(email ? { 'X-User-Email': email } : {}),
  }
}

export async function submitJob(
  platforms: string[],
  payload: Record<string, unknown>,
): Promise<JobResponse> {
  const res = await fetch(`${BASE}/generate`, {
    method: 'POST',
    headers: userHeaders(String(payload.email ?? '')),
    body: JSON.stringify({ ...payload, platforms }),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`API ${res.status}: ${text}`)
  }
  return res.json()
}

export async function getJobStatus(jobId: string): Promise<JobStatusResponse> {
  const res = await fetch(`${BASE}/result/${jobId}`)
  if (!res.ok) throw new Error(`API ${res.status}`)
  return res.json()
}

export async function reviseJob(
  jobId: string,
  payload: Record<string, unknown>,
): Promise<JobResponse> {
  const res = await fetch(`${BASE}/revise/${jobId}`, {
    method: 'POST',
    headers: userHeaders(String(payload.email ?? '')),
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`API ${res.status}: ${text}`)
  }
  return res.json()
}

export async function getUserProfile(email: string): Promise<UserProfileResponse> {
  const res = await fetch(`${BASE}/users/${encodeURIComponent(email)}`)
  if (!res.ok) throw new Error(`API ${res.status}`)
  return res.json()
}

export async function getHistory(email: string): Promise<HistoryResponse> {
  const res = await fetch(`${BASE}/history/${encodeURIComponent(email)}`)
  if (!res.ok) throw new Error(`API ${res.status}`)
  return res.json()
}

export async function deleteHistoryItem(email: string, jobId: string): Promise<void> {
  const res = await fetch(`${BASE}/history/${encodeURIComponent(email)}/${jobId}`, {
    method: 'DELETE',
    headers: userHeaders(email),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`API ${res.status}: ${text}`)
  }
}

export async function deleteProject(email: string, projectId: string): Promise<void> {
  const res = await fetch(`${BASE}/projects/${encodeURIComponent(email)}/${projectId}`, {
    method: 'DELETE',
    headers: userHeaders(email),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`API ${res.status}: ${text}`)
  }
}

export async function checkHealth(): Promise<{ redis: boolean }> {
  const res = await fetch(`${BASE}/health`)
  return res.json()
}

export async function approveJob(email: string, jobId: string): Promise<void> {
  const res = await fetch(`${BASE}/approve/${jobId}`, {
    method: 'POST',
    headers: userHeaders(email),
    body: JSON.stringify({ email }),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`API ${res.status}: ${text}`)
  }
}
