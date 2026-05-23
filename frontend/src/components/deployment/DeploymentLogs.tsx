"use client"

import { useEffect, useRef, useState, useCallback } from "react"
import { Terminal } from "lucide-react"

interface Props {
  deploymentId?: string | null
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

/**
 * Auto-scrolling deployment log viewer.
 * Polls every 2.5s while deployment is active, stops after 120s of inactivity
 * (no new log lines for 3 consecutive polls).
 */
export function DeploymentLogs({ deploymentId }: Props) {
  const [logs, setLogs] = useState<string[]>([])
  const [isStale, setIsStale] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const staleCountRef = useRef(0)
  const lastCountRef = useRef(0)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchLogs = useCallback(async () => {
    if (!deploymentId) return

    try {
      const response = await fetch(
        `${API_BASE}/api/deployments/${deploymentId}/logs`
      )
      if (!response.ok) return

      const data = await response.json()
      const newLogs: string[] = data.logs || []

      setLogs(newLogs)

      // Track staleness — stop polling if no new lines for 3 cycles
      if (newLogs.length === lastCountRef.current) {
        staleCountRef.current += 1
        if (staleCountRef.current >= 3) {
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

    // Reset state on new deploymentId
    setLogs([])
    setIsStale(false)
    staleCountRef.current = 0
    lastCountRef.current = 0

    // Initial fetch
    fetchLogs()

    // Poll every 2.5s
    intervalRef.current = setInterval(fetchLogs, 2500)

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
  }, [deploymentId, fetchLogs])

  // Auto-scroll to bottom on new logs
  useEffect(() => {
    if (bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" })
    }
  }, [logs.length])

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
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-muted-foreground font-mono">
            {logs.length} lines
          </span>
          {isStale ? (
            <span className="text-[10px] text-muted-foreground">● idle</span>
          ) : (
            <span className="text-[10px] text-green-400 animate-pulse">● live</span>
          )}
        </div>
      </div>

      {/* Log body */}
      <div className="max-h-72 overflow-y-auto px-4 py-3 font-mono text-xs text-green-400 space-y-0.5">
        {logs.length === 0 ? (
          <div className="text-muted-foreground/50 italic">
            Waiting for logs...
          </div>
        ) : (
          logs.map((log, idx) => (
            <div key={idx} className="leading-relaxed break-all">
              <span className="text-muted-foreground/40 mr-2 select-none">
                {String(idx + 1).padStart(3, "0")}
              </span>
              {log}
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}