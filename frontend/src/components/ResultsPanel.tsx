import { useState } from 'react'
import { Copy, Check, Plus, SquarePen, Loader2 } from 'lucide-react'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import type { Platform, CachedResult, ActiveJob } from '@/lib/types'
import { PLATFORM_META } from '@/lib/types'

interface ResultsPanelProps {
  result: CachedResult
  requestedPlatforms: Platform[]
  activeJobs: ActiveJob[]
  onAddPlatform: (platform: Platform) => void
  onNewTab: () => void
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <button
      onClick={copy}
      className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
    >
      {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  )
}

function TweetCard({ tweet, index }: { tweet: string; index: number }) {
  const len = tweet.length
  const variant = len >= 200 ? 'success' : len >= 120 ? 'warning' : 'muted'
  return (
    <div className="rounded-lg border bg-background p-4 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-muted-foreground">Tweet {index}</span>
        <div className="flex items-center gap-2">
          <Badge variant={variant}>{len} chars</Badge>
          <CopyButton text={tweet} />
        </div>
      </div>
      <p className="text-sm leading-relaxed whitespace-pre-wrap">{tweet}</p>
    </div>
  )
}

function PendingState({ platform }: { platform: Platform }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-3 text-muted-foreground">
      <Loader2 className="h-6 w-6 animate-spin" />
      <p className="text-sm">Generating {PLATFORM_META[platform].label}…</p>
      <p className="text-xs">You can switch tabs — results appear here when ready.</p>
    </div>
  )
}

function EmptyState({ platform }: { platform: Platform }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-2 text-muted-foreground">
      <p className="text-sm">No {PLATFORM_META[platform].label} generated yet.</p>
    </div>
  )
}

export function ResultsPanel({
  result,
  requestedPlatforms,
  activeJobs,
  onAddPlatform,
  onNewTab,
}: ResultsPanelProps) {
  const allPlatforms: Platform[] = ['x', 'linkedin', 'devto']
  const ungenerated = allPlatforms.filter((p) => !requestedPlatforms.includes(p))

  const isPending = (platform: Platform) =>
    activeJobs.some((j) => j.platforms.includes(platform))

  const defaultTab = requestedPlatforms[0] ?? 'x'

  return (
    <div className="space-y-4">
      <Tabs defaultValue={defaultTab}>
        <div className="flex items-center justify-between mb-4">
          <TabsList>
            {requestedPlatforms.map((p) => (
              <TabsTrigger key={p} value={p} className="gap-1.5">
                {PLATFORM_META[p].label}
                {isPending(p) && <Loader2 className="h-3 w-3 animate-spin" />}
              </TabsTrigger>
            ))}
          </TabsList>
          <Button variant="ghost" size="sm" onClick={onNewTab} className="gap-1.5 text-muted-foreground">
            <SquarePen className="h-3.5 w-3.5" />
            New Tab
          </Button>
        </div>

        <TabsContent value="x">
          {isPending('x') ? (
            <PendingState platform="x" />
          ) : result.xThread?.length ? (
            <div className="space-y-3">
              {result.xThread.map((tweet, i) => (
                <TweetCard key={i} tweet={tweet} index={i + 1} />
              ))}
            </div>
          ) : (
            <EmptyState platform="x" />
          )}
        </TabsContent>

        <TabsContent value="linkedin">
          {isPending('linkedin') ? (
            <PendingState platform="linkedin" />
          ) : result.linkedinPost ? (
            <Card className="p-5">
              <div className="flex justify-end mb-3">
                <CopyButton text={result.linkedinPost} />
              </div>
              <p className="text-sm leading-relaxed whitespace-pre-wrap">{result.linkedinPost}</p>
            </Card>
          ) : (
            <EmptyState platform="linkedin" />
          )}
        </TabsContent>

        <TabsContent value="devto">
          {isPending('devto') ? (
            <PendingState platform="devto" />
          ) : result.devtoArticle ? (
            <Card className="p-5">
              <div className="flex justify-end mb-3">
                <CopyButton text={result.devtoArticle} />
              </div>
              <div className="prose prose-sm max-w-none text-sm leading-relaxed whitespace-pre-wrap">
                {result.devtoArticle}
              </div>
            </Card>
          ) : (
            <EmptyState platform="devto" />
          )}
        </TabsContent>
      </Tabs>

      {ungenerated.length > 0 && (
        <div className="flex items-center gap-2 pt-2 border-t">
          <span className="text-xs text-muted-foreground">Also generate:</span>
          {ungenerated.map((p) => (
            <Button
              key={p}
              variant="outline"
              size="sm"
              onClick={() => onAddPlatform(p)}
              disabled={isPending(p)}
              className="gap-1.5"
            >
              <Plus className="h-3 w-3" />
              {PLATFORM_META[p].label}
            </Button>
          ))}
        </div>
      )}
    </div>
  )
}
