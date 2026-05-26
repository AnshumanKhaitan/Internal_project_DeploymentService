"use client"

import { useEffect, useRef, useState, useCallback } from "react"
import { Terminal, ChevronDown } from "lucide-react"
import { useDeployment } from "@/lib/deployment-context"
import { getApiBase } from "@/lib/api"

interface Props {
  deploymentId?: string | null
}

/**
 * Auto-scrolling deployment log viewer with color-coded output.
 *
 * - Reads deploymentId from prop (explicit) or from DeploymentContext (fallback)
 * - Polls every 2.5s while deployment is active
 * - Stops after 5 consecutive cycles with no new lines (stale detection)
 * - Color-codes [Build], [Error], [Health], [Deploy], [Runtime] prefixes
 * - Shows line numbers in gutter
 * - Auto-scrolls to bottom; user can scroll up freely
 */
export function DeploymentLogs({ deploymentId: propId }: Props) {
  // Fallback to shared context when no explicit prop is passed.
  // This allows <DeploymentLogs /> at page level to work without a prop,
  // while <DeploymentLogs deploymentId={id} /> inside UploadZone still works.
  const { deploymentId: contextId } = useDeployment()
  const deploymentId = propId ?? contextId

  const [logs, setLogs] = useState<string[]>([])
  const [isStale, setIsStale] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const staleCountRef = useRef(0)
  const lastCountRef = useRef(0)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const userScrolledRef = useRef(false)

  const fetchLogs = useCallback(async () => {
    if (!deploymentId) return

    try {
      const response = await fetch(
        `${getApiBase()}/api/deployments/${deploymentId}/logs`,
        { cache: "no-store" }
      )
      if (!response.ok) return

      const data = await response.json()
      const newLogs: string[] = data.logs || []

      setLogs(newLogs)

      // Staleness detection — stop after 5 cycles with no new lines
      if (newLogs.length === lastCountRef.current) {
        staleCountRef.current += 1
        if (staleCountRef.current >= 5) {
          setIsStale(true)
          if (intervalRef.current) {
            clearInterval(intervalRef.current)
            intervalRef.current = null
          }
        }
      } else {
        staleCountRef.current = 0
        lastCountRef.current = newLogs.length
        setIsStale(false)
      }
    } catch {
      // Silent — logs are non-critical
    }
  }, [deploymentId])

  useEffect(() => {
    if (!deploymentId) return

    // Reset on new deployment
    setLogs([])
    setIsStale(false)
    staleCountRef.current = 0
    lastCountRef.current = 0
    userScrolledRef.current = false

    fetchLogs()
    intervalRef.current = setInterval(fetchLogs, 2500)

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
  }, [deploymentId, fetchLogs])

  // Auto-scroll to bottom when new logs arrive (unless user has scrolled up)
  useEffect(() => {
    if (!userScrolledRef.current && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" })
    }
  }, [logs.length])

  // Track if user has scrolled up
  const handleScroll = () => {
    const el = containerRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    userScrolledRef.current = !atBottom
  }

  const scrollToBottom = () => {
    userScrolledRef.current = false
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }

  if (!deploymentId) return null

  return (
    <div className="rounded-xl border border-border bg-black/95 overflow-hidden mt-4">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border/30 bg-black/60">
        <div className="flex items-center gap-2">
          <Terminal className="h-3.5 w-3.5 text-green-400" />
          <span className="text-xs font-mono uppercase tracking-widest text-green-400">
            Deployment Logs
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[10px] text-muted-foreground font-mono">
            {logs.length} lines
          </span>
          {isStale ? (
            <span className="text-[10px] text-muted-foreground font-mono">● idle</span>
          ) : (
            <span className="text-[10px] text-green-400 animate-pulse font-mono">● live</span>
          )}
          <button
            onClick={scrollToBottom}
            className="text-muted-foreground hover:text-foreground transition-colors"
            title="Scroll to bottom"
          >
            <ChevronDown className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Log body */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="max-h-80 overflow-y-auto px-4 py-3 font-mono text-xs space-y-0.5"
      >
        {logs.length === 0 ? (
          <div className="text-muted-foreground/50 italic py-2">
            Waiting for deployment logs...
          </div>
        ) : (
          logs.map((log, idx) => (
            <LogLine key={idx} index={idx} line={log} />
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}

// ── Log line coloring ──────────────────────────────────────────────────────────

function logColor(line: string): string {
  const lower = line.toLowerCase()
  if (lower.includes("[error]") || lower.includes("error:") || lower.includes("failed"))
    return "text-red-400"
  if (lower.includes("[build]"))
    return "text-yellow-300"
  if (lower.includes("[health]"))
    return "text-blue-400"
  if (lower.includes("[deploy]"))
    return "text-cyan-400"
  if (lower.includes("[runtime]") || lower.includes("listening") || lower.includes("started"))
    return "text-green-400"
  if (lower.includes("warn") || lower.includes("warning"))
    return "text-orange-400"
  return "text-green-400/80"
}

function LogLine({ index, line }: { index: number; line: string }) {
  const color = logColor(line)

  return (
    <div className={`leading-relaxed break-all flex gap-2 ${color}`}>
      <span className="text-muted-foreground/30 select-none shrink-0 w-8 text-right">
        {String(index + 1).padStart(3, "0")}
      </span>
      <span>{line}</span>
    </div>
  )
}