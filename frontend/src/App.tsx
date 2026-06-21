import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, ChevronDown, ChevronRight, FileText, Loader2, RefreshCw, Trash2, Upload, X, Zap } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ResultsPanel } from '@/components/ResultsPanel'
import { approveJob, deleteHistoryItem, deleteProject, getHistory, getJobStatus, reviseJob, submitJob } from '@/lib/api'
import { cn, makeFingerprint, parseBulletList } from '@/lib/utils'
import type { ActiveJob, CachedResult, HistoryItem, Platform } from '@/lib/types'
import { PLATFORM_META } from '@/lib/types'

const TONES = ['honest and practical', 'technical', 'casual', 'professional', 'storytelling']
const AUDIENCES = [
  'intermediate developers', 'junior developers', 'senior engineers',
  'CTOs / Tech leads', 'DevOps engineers', 'full-stack developers', 'general tech community',
]
const ALL_PLATFORMS: Platform[] = ['x', 'linkedin', 'devto']

const STEP_LABELS: Record<string, string> = {
  queued: 'Waiting in queue…',
  running: 'Starting up…',
  extracting: 'Extracting insights from README…',
  writing: 'Writing content…',
  reviewing: 'Reviewing drafts…',
  awaiting_approval: 'Awaiting approval…',
  completed: 'Done!',
}

type InputMethod = 'paste' | 'upload'

interface WorkspaceTab {
  id: string
  title: string
  inputMethod: InputMethod
  email: string
  readme: string
  learnings: string
  hardParts: string
  tone: string
  audience: string
  selected: Platform[]
  resultCache: Record<string, CachedResult>
  fingerprint: string | null
  projectId: string | null
  platformJobIds: Partial<Record<Platform, string>>
  requestedPlatforms: Platform[]
  latestJobId: string | null
  latestJobStatus: string | null
  revisionInstruction: string
  history: HistoryItem[]
  error: string | null
}

function makeTabId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `tab-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

function createTab(index: number): WorkspaceTab {
  return {
    id: makeTabId(),
    title: `Draft ${index}`,
    inputMethod: 'paste',
    email: '',
    readme: '',
    learnings: '',
    hardParts: '',
    tone: TONES[0],
    audience: AUDIENCES[0],
    selected: ['x'],
    resultCache: {},
    fingerprint: null,
    projectId: null,
    platformJobIds: {},
    requestedPlatforms: [],
    latestJobId: null,
    latestJobStatus: null,
    revisionInstruction: '',
    history: [],
    error: null,
  }
}

const INITIAL_TAB = createTab(1)

export default function App() {
  const [tabs, setTabs] = useState<WorkspaceTab[]>(() => [INITIAL_TAB])
  const [activeTabId, setActiveTabId] = useState<string>(() => INITIAL_TAB.id)
  const [activeJobs, setActiveJobs] = useState<ActiveJob[]>([])
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(new Set())

  const activeJobsRef = useRef(activeJobs)
  useEffect(() => { activeJobsRef.current = activeJobs }, [activeJobs])

  const activeTab = useMemo(
    () => tabs.find((tab) => tab.id === activeTabId) ?? tabs[0],
    [tabs, activeTabId],
  )

  const updateTab = useCallback((tabId: string, updater: (tab: WorkspaceTab) => WorkspaceTab) => {
    setTabs((prev) => prev.map((tab) => (tab.id === tabId ? updater(tab) : tab)))
  }, [])

  const refreshHistory = useCallback(async (tabId: string, email: string) => {
    if (!email.includes('@')) return
    try {
      const resp = await getHistory(email)
      updateTab(tabId, (tab) => ({ ...tab, history: resp.items }))
    } catch {
      updateTab(tabId, (tab) => ({ ...tab, history: [] }))
    }
  }, [updateTab])

  useEffect(() => {
    if (activeJobs.length === 0) return
    const id = setInterval(async () => {
      const remaining: ActiveJob[] = []

      await Promise.all(
        activeJobsRef.current.map(async (job) => {
          try {
            const data = await getJobStatus(job.jobId)
            if (data.status === 'completed' || data.status === 'awaiting_approval') {
              updateTab(job.tabId, (tab) => {
                const next = { ...tab.resultCache }
                const existing = next[job.fingerprint] ?? {}
                if (data.x_thread) existing.xThread = data.x_thread
                if (data.linkedin_post) existing.linkedinPost = data.linkedin_post
                if (data.devto_article) existing.devtoArticle = data.devto_article
                next[job.fingerprint] = existing
                return {
                  ...tab,
                  resultCache: next,
                  latestJobId: job.jobId,
                  latestJobStatus: data.status,
                  error: null,
                }
              })
            } else if (data.status === 'failed') {
              updateTab(job.tabId, (tab) => ({ ...tab, error: data.error ?? 'Job failed' }))
            } else {
              remaining.push({
                ...job,
                status: data.status,
                currentStep: data.current_step ?? '',
                threadId: data.thread_id,
                parentJobId: data.parent_job_id,
              })
            }
          } catch {
            remaining.push(job)
          }
        }),
      )

      setActiveJobs(remaining)
    }, 2000)
    return () => clearInterval(id)
  }, [activeJobs.length, updateTab])

  useEffect(() => {
    if (!activeTab?.email.includes('@')) return
    let cancelled = false
    getHistory(activeTab.email)
      .then((resp) => {
        if (!cancelled) {
          updateTab(activeTab.id, (tab) => ({ ...tab, history: resp.items }))
        }
      })
      .catch(() => {
        if (!cancelled) {
          updateTab(activeTab.id, (tab) => ({ ...tab, history: [] }))
        }
      })
    return () => { cancelled = true }
  }, [activeTab?.email, activeTab?.id, updateTab])

  const buildPayload = useCallback((tab: WorkspaceTab) => ({
    email: tab.email,
    readme: tab.readme,
    learnings: parseBulletList(tab.learnings),
    hard_parts: parseBulletList(tab.hardParts),
    tone: tab.tone,
    audience: tab.audience,
  }), [])

  const platformCached = (tab: WorkspaceTab, fp: string, p: Platform): boolean => {
    const c = tab.resultCache[fp]
    if (!c) return false
    if (p === 'x') return !!c.xThread?.length
    if (p === 'linkedin') return !!c.linkedinPost
    if (p === 'devto') return !!c.devtoArticle
    return false
  }

  const renameTab = (tab: WorkspaceTab) => {
    const line = tab.readme.split('\n').find((x) => x.trim())
    if (!line) return tab.title
    const cleaned = line.replace(/^#\s*/, '').trim()
    return cleaned ? cleaned.slice(0, 24) : tab.title
  }

  const handleGenerate = async () => {
    if (!activeTab || !activeTab.readme.trim()) return
    updateTab(activeTab.id, (tab) => ({ ...tab, error: null }))
    const payload = buildPayload(activeTab)
    const fp = makeFingerprint(payload)
    const toGenerate = activeTab.selected.filter((p) => !platformCached(activeTab, fp, p))

    updateTab(activeTab.id, (tab) => ({
      ...tab,
      fingerprint: fp,
      title: renameTab(tab),
      requestedPlatforms: [...new Set([...tab.requestedPlatforms, ...tab.selected])] as Platform[],
    }))

    if (toGenerate.length === 0) return

    try {
      const { job_id, thread_id, parent_job_id } = await submitJob(toGenerate, payload)
      setActiveJobs((prev) => [
        ...prev,
        {
          jobId: job_id,
          tabId: activeTab.id,
          platforms: toGenerate,
          fingerprint: fp,
          status: 'queued',
          currentStep: 'queued',
          threadId: thread_id,
          parentJobId: parent_job_id,
        },
      ])
      updateTab(activeTab.id, (tab) => ({ ...tab, latestJobId: job_id, latestJobStatus: 'queued' }))
      await refreshHistory(activeTab.id, activeTab.email)
    } catch (e) {
      updateTab(activeTab.id, (tab) => ({
        ...tab,
        error: e instanceof Error ? e.message : 'Failed to submit job',
      }))
    }
  }

  const handleAddPlatform = async (platform: Platform) => {
    if (!activeTab || !activeTab.fingerprint) return
    updateTab(activeTab.id, (tab) => ({
      ...tab,
      error: null,
      requestedPlatforms: tab.requestedPlatforms.includes(platform)
        ? tab.requestedPlatforms
        : [...tab.requestedPlatforms, platform],
    }))
    try {
      const { job_id, thread_id, parent_job_id } = await submitJob([platform], buildPayload(activeTab))
      setActiveJobs((prev) => [
        ...prev,
        {
          jobId: job_id,
          tabId: activeTab.id,
          platforms: [platform],
          fingerprint: activeTab.fingerprint!,
          status: 'queued',
          currentStep: 'queued',
          threadId: thread_id,
          parentJobId: parent_job_id,
        },
      ])
      updateTab(activeTab.id, (tab) => ({ ...tab, latestJobId: job_id, latestJobStatus: 'queued' }))
    } catch (e) {
      updateTab(activeTab.id, (tab) => ({
        ...tab,
        error: e instanceof Error ? e.message : 'Failed to submit job',
      }))
    }
  }

  const handleRevise = async () => {
    if (!activeTab || !activeTab.latestJobId || !activeTab.email.trim() || !activeTab.revisionInstruction.trim()) return
    const fp = activeTab.fingerprint ?? makeFingerprint(buildPayload(activeTab))
    updateTab(activeTab.id, (tab) => ({ ...tab, error: null }))
    try {
      const { job_id, thread_id, parent_job_id } = await reviseJob(activeTab.latestJobId, {
        email: activeTab.email,
        instruction: activeTab.revisionInstruction,
        tone: activeTab.tone,
        platforms: activeTab.requestedPlatforms,
      })
      setActiveJobs((prev) => [
        ...prev,
        {
          jobId: job_id,
          tabId: activeTab.id,
          platforms: activeTab.requestedPlatforms,
          fingerprint: fp,
          status: 'queued',
          currentStep: 'queued',
          threadId: thread_id,
          parentJobId: parent_job_id,
        },
      ])
      updateTab(activeTab.id, (tab) => ({
        ...tab,
        latestJobId: job_id,
        latestJobStatus: 'queued',
        revisionInstruction: '',
        fingerprint: fp,
      }))
      await refreshHistory(activeTab.id, activeTab.email)
    } catch (e) {
      updateTab(activeTab.id, (tab) => ({
        ...tab,
        error: e instanceof Error ? e.message : 'Failed to submit revision',
      }))
    }
  }

  const handleNewTab = () => {
    const next = createTab(tabs.length + 1)
    setTabs((prev) => [...prev, next])
    setActiveTabId(next.id)
  }

  const handleOpenHistoryItem = (item: HistoryItem) => {
    const next = createTab(tabs.length + 1)
    const payload = {
      email: activeTab.email || '',
      readme: item.readme,
      learnings: item.learnings,
      hard_parts: item.hard_parts,
      tone: item.tone ?? TONES[0],
      audience: item.audience ?? AUDIENCES[0],
    }
    const fp = makeFingerprint(payload)
    next.title = item.readme
      .split('\n')
      .find((line) => line.trim())
      ?.replace(/^#\s*/, '')
      .trim()
      .slice(0, 24) || `Draft ${tabs.length + 1}`
    next.email = activeTab.email || ''
    next.readme = item.readme
    next.learnings = item.learnings.map((x) => `- ${x}`).join('\n')
    next.hardParts = item.hard_parts.map((x) => `- ${x}`).join('\n')
    next.tone = item.tone ?? TONES[0]
    next.audience = item.audience ?? AUDIENCES[0]

    // Step 1: aggregate — oldest first so newest wins per platform
    const projectRuns = activeTab.history
      .filter((h) => h.project_id === item.project_id)
      .sort((a, b) => new Date(a.updated_at).getTime() - new Date(b.updated_at).getTime())
    const merged: CachedResult = {}
    const allPlatforms = new Set<Platform>()
    const platformJobIds: Partial<Record<Platform, string>> = {}
    for (const run of projectRuns) {
      if (run.x_thread?.length) { merged.xThread = run.x_thread; platformJobIds.x = run.job_id }
      if (run.linkedin_post) { merged.linkedinPost = run.linkedin_post; platformJobIds.linkedin = run.job_id }
      if (run.devto_article) { merged.devtoArticle = run.devto_article; platformJobIds.devto = run.job_id }
      for (const p of run.platforms) allPlatforms.add(p as Platform)
    }

    // Step 2: override with this specific item's content for its own platforms
    if (item.x_thread?.length) { merged.xThread = item.x_thread; platformJobIds.x = item.job_id }
    if (item.linkedin_post) { merged.linkedinPost = item.linkedin_post; platformJobIds.linkedin = item.job_id }
    if (item.devto_article) { merged.devtoArticle = item.devto_article; platformJobIds.devto = item.job_id }

    next.selected = item.platforms.length > 0 ? item.platforms : ['x']
    next.requestedPlatforms = allPlatforms.size > 0 ? Array.from(allPlatforms) : ['x']
    next.latestJobId = item.job_id
    next.latestJobStatus = item.status
    next.fingerprint = fp
    next.projectId = item.project_id
    next.platformJobIds = platformJobIds
    next.resultCache = { [fp]: merged }
    next.history = activeTab.history
    setTabs((prev) => [...prev, next])
    setActiveTabId(next.id)
  }

  // In-place version swap: only updates the clicked run's platforms, keeps everything else
  const handleLoadHistoryRun = (run: HistoryItem) => {
    if (activeTab.projectId !== run.project_id || !activeTab.fingerprint) {
      // Different project — fall back to opening a new tab
      handleOpenHistoryItem(run)
      return
    }
    updateTab(activeTab.id, (tab) => {
      const fp = tab.fingerprint!
      const existing = tab.resultCache[fp] ?? {}
      const updated = { ...existing }
      const jobIds = { ...tab.platformJobIds }
      if (run.x_thread?.length) { updated.xThread = run.x_thread; jobIds.x = run.job_id }
      if (run.linkedin_post) { updated.linkedinPost = run.linkedin_post; jobIds.linkedin = run.job_id }
      if (run.devto_article) { updated.devtoArticle = run.devto_article; jobIds.devto = run.job_id }
      return {
        ...tab,
        resultCache: { ...tab.resultCache, [fp]: updated },
        platformJobIds: jobIds,
        latestJobId: run.job_id,
        latestJobStatus: run.status,
      }
    })
  }

  const handleCloseTab = (tabId: string) => {
    if (tabs.length === 1) return
    const remaining = tabs.filter((tab) => tab.id !== tabId)
    setTabs(remaining)
    setActiveJobs((prev) => prev.filter((job) => job.tabId !== tabId))
    if (activeTabId === tabId) {
      setActiveTabId(remaining[0].id)
    }
  }

  const handleDeleteHistoryItem = async (item: HistoryItem) => {
    if (!activeTab.email) return
    try {
      await deleteHistoryItem(activeTab.email, item.job_id)
      setActiveJobs((prev) => prev.filter((job) => job.jobId !== item.job_id))
      await refreshHistory(activeTab.id, activeTab.email)
    } catch (e) {
      updateTab(activeTab.id, (tab) => ({
        ...tab,
        error: e instanceof Error ? e.message : 'Failed to delete history item',
      }))
    }
  }

  const handleDeleteProject = async (projectId: string) => {
    if (!activeTab.email) return
    try {
      await deleteProject(activeTab.email, projectId)
      setActiveJobs((prev) => prev.filter((job) => {
        const item = activeTab.history.find((entry) => entry.job_id === job.jobId)
        return item?.project_id !== projectId
      }))
      await refreshHistory(activeTab.id, activeTab.email)
    } catch (e) {
      updateTab(activeTab.id, (tab) => ({
        ...tab,
        error: e instanceof Error ? e.message : 'Failed to delete project',
      }))
    }
  }

  const handleApprove = async () => {
    if (!activeTab.email || !activeTab.latestJobId) return
    try {
      await approveJob(activeTab.email, activeTab.latestJobId)
      updateTab(activeTab.id, (tab) => ({ ...tab, latestJobStatus: 'completed' }))
      await refreshHistory(activeTab.id, activeTab.email)
    } catch (e) {
      updateTab(activeTab.id, (tab) => ({
        ...tab,
        error: e instanceof Error ? e.message : 'Failed to approve output',
      }))
    }
  }

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !activeTab) return
    const reader = new FileReader()
    reader.onload = (ev) => {
      updateTab(activeTab.id, (tab) => ({
        ...tab,
        readme: ev.target?.result as string ?? '',
      }))
    }
    reader.readAsText(file)
  }

  const hasResults = !!(activeTab?.fingerprint && activeTab.requestedPlatforms.length > 0 && (
    activeTab.resultCache[activeTab.fingerprint] ||
    activeJobs.some((job) => job.tabId === activeTab.id && job.fingerprint === activeTab.fingerprint)
  ))
  const currentCache = activeTab?.fingerprint ? (activeTab.resultCache[activeTab.fingerprint] ?? {}) : {}
  const currentActiveJobs = activeTab ? activeJobs.filter((job) => job.tabId === activeTab.id) : []
  const projectGroups = useMemo(() => {
    const grouped = new Map<string, { latest: HistoryItem; count: number; items: HistoryItem[] }>()
    for (const item of activeTab.history) {
      const existing = grouped.get(item.project_id)
      if (!existing) {
        grouped.set(item.project_id, { latest: item, count: 1, items: [item] })
        continue
      }
      grouped.set(item.project_id, {
        latest: new Date(item.updated_at) > new Date(existing.latest.updated_at) ? item : existing.latest,
        count: existing.count + 1,
        items: [...existing.items, item],
      })
    }
    return Array.from(grouped.values())
      .map((g) => ({ ...g, items: g.items.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()) }))
      .sort((a, b) => new Date(b.latest.updated_at).getTime() - new Date(a.latest.updated_at).getTime())
  }, [activeTab.history])
  const platformVersionLabels = useMemo((): Partial<Record<Platform, string>> => {
    if (!activeTab.projectId) return {}
    const labels: Partial<Record<Platform, string>> = {}
    const projectRuns = activeTab.history.filter((h) => h.project_id === activeTab.projectId)
    for (const p of ALL_PLATFORMS) {
      const currentJobId = activeTab.platformJobIds[p]
      if (!currentJobId) continue
      const runsForPlatform = projectRuns
        .filter((h) => h.platforms.includes(p))
        .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
      const idx = runsForPlatform.findIndex((h) => h.job_id === currentJobId)
      if (idx >= 0 && runsForPlatform.length > 1) {
        labels[p] = `v${idx + 1}/${runsForPlatform.length}`
      }
    }
    return labels
  }, [activeTab.platformJobIds, activeTab.history, activeTab.projectId])

  const isGenerating = currentActiveJobs.length > 0

  if (!activeTab) return null

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b">
        <div className="max-w-5xl mx-auto px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Zap className="h-5 w-5 text-foreground" />
            <span className="font-semibold text-sm tracking-tight">DevVoice</span>
          </div>
          <span className="text-xs text-muted-foreground hidden sm:block">
            Turn a README into platform-native content
          </span>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8 space-y-8">
        <div className="flex flex-wrap items-center gap-2">
          {tabs.map((tab) => {
            const running = activeJobs.some((job) => job.tabId === tab.id)
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTabId(tab.id)}
                className={cn(
                  'inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-colors',
                  activeTabId === tab.id ? 'border-foreground bg-foreground text-background' : 'hover:border-foreground/40',
                )}
              >
                <span>{tab.title}</span>
                {running && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                {tabs.length > 1 && (
                  <span
                    onClick={(e) => {
                      e.stopPropagation()
                      handleCloseTab(tab.id)
                    }}
                    className="rounded-full p-0.5 hover:bg-black/10"
                  >
                    <X className="h-3 w-3" />
                  </span>
                )}
              </button>
            )
          })}
          <Button variant="outline" size="sm" onClick={handleNewTab}>New Tab</Button>
        </div>

        {currentActiveJobs.length > 0 && (
          <div className="rounded-lg border bg-muted/50 px-4 py-3 space-y-1">
            {currentActiveJobs.map((job) => (
              <div key={job.jobId} className="flex items-center gap-2 text-sm">
                <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground shrink-0" />
                <span className="text-muted-foreground">
                  {job.platforms.map((p) => PLATFORM_META[p].label).join(' + ')}
                </span>
                <span className="text-xs text-muted-foreground">—</span>
                <span className="text-xs text-muted-foreground">{STEP_LABELS[job.status] ?? job.status}</span>
              </div>
            ))}
          </div>
        )}

        {activeTab.error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 flex gap-2 text-sm text-red-700">
            <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
            <span>{activeTab.error}</span>
          </div>
        )}

        {hasResults && (
          <ResultsPanel
            result={currentCache}
            requestedPlatforms={activeTab.requestedPlatforms}
            activeJobs={currentActiveJobs}
            platformVersionLabels={platformVersionLabels}
            onAddPlatform={handleAddPlatform}
            onNewTab={handleNewTab}
          />
        )}

        {hasResults && (
          <Card id="revise-section" className="mt-6">
            <CardHeader>
              <CardTitle className="text-sm">Revise Current Result</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {activeTab.latestJobStatus === 'awaiting_approval' && (
                <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                  Output is waiting for your approval before it is finalized.
                </div>
              )}
              <textarea
                value={activeTab.revisionInstruction}
                onChange={(e) => updateTab(activeTab.id, (tab) => ({ ...tab, revisionInstruction: e.target.value }))}
                rows={3}
                placeholder="Example: make it more technical and less promotional."
                className="w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring scrollbar-thin"
              />
              <Button
                variant="outline"
                className="w-full"
                disabled={!activeTab.latestJobId || !activeTab.revisionInstruction.trim() || isGenerating}
                onClick={handleRevise}
              >
                Revise With Current Tone Settings
              </Button>
              {activeTab.latestJobStatus === 'awaiting_approval' && (
                <Button
                  className="w-full"
                  disabled={!activeTab.latestJobId || isGenerating}
                  onClick={handleApprove}
                >
                  Approve Output
                </Button>
              )}
            </CardContent>
          </Card>
        )}

        <div className={cn('grid gap-6', hasResults && 'pt-6 border-t')}>
          {/* USER CARD */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">User</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="email" className="text-xs text-muted-foreground">Email</Label>
                <input
                  id="email"
                  type="email"
                  value={activeTab.email}
                  onChange={(e) => updateTab(activeTab.id, (tab) => ({ ...tab, email: e.target.value }))}
                  placeholder="you@example.com"
                  className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                />
              </div>
            </CardContent>
          </Card>

          {/* README & GENERATE SIDE BY SIDE */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* LEFT: README */}
            <Card className="flex flex-col">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm">README</CardTitle>
                  <div className="flex rounded-md border overflow-hidden text-xs">
                    {(['paste', 'upload'] as const).map((m) => (
                      <button
                        key={m}
                        onClick={() => updateTab(activeTab.id, (tab) => ({ ...tab, inputMethod: m }))}
                        className={cn(
                          'px-3 py-1 transition-colors',
                          activeTab.inputMethod === m
                            ? 'bg-foreground text-background'
                            : 'hover:bg-muted text-muted-foreground',
                        )}
                      >
                        {m === 'paste' ? 'Paste' : 'Upload'}
                      </button>
                    ))}
                  </div>
                </div>
              </CardHeader>
              <CardContent className="flex flex-col flex-1">
                {activeTab.inputMethod === 'paste' ? (
                  <div className="space-y-1.5 flex flex-col flex-1">
                    <textarea
                      value={activeTab.readme}
                      onChange={(e) => updateTab(activeTab.id, (tab) => ({ ...tab, readme: e.target.value }))}
                      rows={10}
                      placeholder="# Your Project&#10;&#10;Paste your full README.md here…"
                      className="w-full flex-1 resize-none rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring font-mono scrollbar-thin"
                    />
                    {activeTab.readme && (
                      <p className="text-xs text-muted-foreground text-right">{activeTab.readme.length.toLocaleString()} chars</p>
                    )}
                  </div>
                ) : (
                  <label className="flex flex-col items-center justify-center flex-1 rounded-md border-2 border-dashed border-input cursor-pointer hover:border-foreground/30 transition-colors gap-2">
                    <Upload className="h-5 w-5 text-muted-foreground" />
                    <span className="text-sm text-muted-foreground">
                      {activeTab.readme ? (
                        <span className="flex items-center gap-1.5">
                          <FileText className="h-4 w-4" />
                          File loaded · {activeTab.readme.length.toLocaleString()} chars
                        </span>
                      ) : (
                        'Drop .md or .txt file, or click to browse'
                      )}
                    </span>
                    <input type="file" accept=".md,.txt" className="sr-only" onChange={handleFileUpload} />
                  </label>
                )}
              </CardContent>
            </Card>

            {/* RIGHT: GENERATE */}
            <Card className="flex flex-col">
              <CardHeader>
                <CardTitle className="text-sm">Generate</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-4 flex-1">
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                  {ALL_PLATFORMS.map((p) => {
                    const cached = activeTab.fingerprint ? platformCached(activeTab, activeTab.fingerprint, p) : false
                    const pending = currentActiveJobs.some((j) => j.platforms.includes(p))
                    const selected = activeTab.selected.includes(p)
                    return (
                      <label
                        key={p}
                        className={cn(
                          'flex flex-col gap-0.5 rounded-lg border p-2 cursor-pointer transition-colors',
                          selected ? 'border-foreground bg-muted/30' : 'border-input hover:border-foreground/40',
                        )}
                      >
                        <div className="flex items-center gap-2">
                          <Checkbox
                            checked={selected}
                            onCheckedChange={() => updateTab(activeTab.id, (tab) => ({
                              ...tab,
                              selected: tab.selected.includes(p)
                                ? tab.selected.filter((value) => value !== p)
                                : [...tab.selected, p],
                            }))}
                            id={`plat-${activeTab.id}-${p}`}
                          />
                          <span className="text-xs font-medium">{PLATFORM_META[p].label}</span>
                          {cached && <Badge variant="success" className="text-[9px] px-1 py-0">cached</Badge>}
                          {pending && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
                        </div>
                        <p className="text-[11px] text-muted-foreground pl-6 leading-tight">{PLATFORM_META[p].description}</p>
                      </label>
                    )
                  })}
                </div>
                <Button
                  className="w-full mt-auto"
                  disabled={!activeTab.email.trim() || !activeTab.readme.trim() || activeTab.selected.length === 0 || isGenerating}
                  onClick={handleGenerate}
                >
                  {isGenerating ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Generating…
                    </>
                  ) : (
                    `Generate ${activeTab.selected.map((p) => PLATFORM_META[p].label).join(' + ')}`
                  )}
                </Button>
              </CardContent>
            </Card>
          </div>

          {/* BOTTOM ROW */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* BOTTOM LEFT: CONTEXT */}
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Context <span className="font-normal text-muted-foreground">(optional)</span></CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <Label htmlFor="learnings" className="text-xs text-muted-foreground">Key Learnings</Label>
                    <textarea
                      id="learnings"
                      value={activeTab.learnings}
                      onChange={(e) => updateTab(activeTab.id, (tab) => ({ ...tab, learnings: e.target.value }))}
                      rows={4}
                      placeholder="One per line:&#10;- Redis pub/sub is faster than polling&#10;- Celery needs state tracking"
                      className="w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring scrollbar-thin"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="hardparts" className="text-xs text-muted-foreground">Hard Parts / Challenges</Label>
                    <textarea
                      id="hardparts"
                      value={activeTab.hardParts}
                      onChange={(e) => updateTab(activeTab.id, (tab) => ({ ...tab, hardParts: e.target.value }))}
                      rows={4}
                      placeholder="One per line:&#10;- Managing distributed task state&#10;- Debugging connection timeouts"
                      className="w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring scrollbar-thin"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <Label htmlFor="tone" className="text-xs text-muted-foreground">Tone</Label>
                    <select
                      id="tone"
                      value={activeTab.tone}
                      onChange={(e) => updateTab(activeTab.id, (tab) => ({ ...tab, tone: e.target.value }))}
                      className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                    >
                      {TONES.map((t) => <option key={t}>{t}</option>)}
                    </select>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="audience" className="text-xs text-muted-foreground">Audience</Label>
                    <select
                      id="audience"
                      value={activeTab.audience}
                      onChange={(e) => updateTab(activeTab.id, (tab) => ({ ...tab, audience: e.target.value }))}
                      className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                    >
                      {AUDIENCES.map((a) => <option key={a}>{a}</option>)}
                    </select>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* BOTTOM RIGHT: HISTORY */}
            <div className="space-y-6">
              <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-tight">History</h3>
            {activeTab.email.includes('@') && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm">Projects</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  {projectGroups.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-8 gap-4 text-center">
                      <div className="space-y-1">
                        <p className="text-sm text-muted-foreground">No projects yet for this email</p>
                        <p className="text-xs text-muted-foreground">Start creating content by filling in the form and generating</p>
                      </div>
                      <Button
                        variant="outline"
                        onClick={() => {
                          const readmeField = document.querySelector('textarea[placeholder*="Paste your full README"]') as HTMLTextAreaElement
                          if (readmeField) readmeField.focus()
                        }}
                      >
                        Get Started
                      </Button>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {projectGroups.slice(0, 8).map(({ latest, count, items }) => {
                    const projectTitle = latest.readme
                      .split('\n')
                      .find((line) => line.trim())
                      ?.replace(/^#\s*/, '')
                      .trim() || latest.project_id
                    const isExpanded = expandedProjects.has(latest.project_id)
                    const toggleExpand = (e: React.MouseEvent) => {
                      e.stopPropagation()
                      setExpandedProjects((prev) => {
                        const next = new Set(prev)
                        if (next.has(latest.project_id)) next.delete(latest.project_id)
                        else next.add(latest.project_id)
                        return next
                      })
                    }
                    return (
                      <div key={latest.project_id} className="rounded-md border overflow-hidden">
                        {/* Project header row */}
                        <div className="flex items-center gap-2 p-3 hover:bg-muted/30 transition-colors">
                          <button
                            type="button"
                            onClick={toggleExpand}
                            className="text-muted-foreground hover:text-foreground"
                          >
                            {isExpanded
                              ? <ChevronDown className="h-3.5 w-3.5" />
                              : <ChevronRight className="h-3.5 w-3.5" />}
                          </button>
                          <button
                            type="button"
                            onClick={() => handleOpenHistoryItem(latest)}
                            className="flex-1 text-left min-w-0"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="text-sm font-medium truncate">{projectTitle.slice(0, 38)}</span>
                              <Badge variant="muted" className="shrink-0">{count} run{count === 1 ? '' : 's'}</Badge>
                            </div>
                            <div className="text-xs text-muted-foreground mt-0.5">
                              {new Date(latest.updated_at).toLocaleString()}
                            </div>
                          </button>
                          <span
                            onClick={(e) => { e.stopPropagation(); void handleDeleteProject(latest.project_id) }}
                            className="shrink-0 rounded-md p-1 text-muted-foreground hover:text-foreground hover:bg-muted cursor-pointer"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </span>
                        </div>

                        {/* Per-run history rows (expanded) */}
                        {isExpanded && (
                          <div className="border-t divide-y">
                            {items.map((run) => (
                              <div key={run.job_id} className="px-3 py-2.5 flex items-start justify-between gap-2 bg-muted/10">
                                <div className="min-w-0 space-y-0.5">
                                  <div className="flex items-center gap-1.5 flex-wrap">
                                    {run.platforms.map((p) => (
                                      <Badge key={p} variant="muted" className="text-[10px] px-1.5 py-0">{PLATFORM_META[p as Platform].label}</Badge>
                                    ))}
                                    {run.parent_job_id && (
                                      <Badge variant="warning" className="text-[10px] px-1.5 py-0">revision</Badge>
                                    )}
                                  </div>
                                  <div className="text-[11px] text-muted-foreground">
                                    {run.status} · {new Date(run.created_at).toLocaleString()}
                                  </div>
                                </div>
                                <div className="flex items-center gap-1 shrink-0">
                                  <button
                                    type="button"
                                    onClick={() => handleLoadHistoryRun(run)}
                                    title="Load this version"
                                    className="rounded-md p-1 text-muted-foreground hover:text-foreground hover:bg-muted"
                                  >
                                    <FileText className="h-3.5 w-3.5" />
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => {
                                      handleLoadHistoryRun(run)
                                      setTimeout(() => {
                                        document.getElementById('revise-section')?.scrollIntoView({ behavior: 'smooth' })
                                      }, 100)
                                    }}
                                    title="Load and revise"
                                    className="rounded-md p-1 text-muted-foreground hover:text-foreground hover:bg-muted"
                                  >
                                    <RefreshCw className="h-3.5 w-3.5" />
                                  </button>
                                  <span
                                    onClick={(e) => { e.stopPropagation(); void handleDeleteHistoryItem(run) }}
                                    title="Delete this run"
                                    className="rounded-md p-1 text-muted-foreground hover:text-foreground hover:bg-muted cursor-pointer"
                                  >
                                    <Trash2 className="h-3.5 w-3.5" />
                                  </span>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )
                  })}
                    </div>
                  )}
                </CardContent>
              </Card>
            )}
          </div>
          </div>
        </div>
      </main>
    </div>
  )
}
