"use client"

import { useEffect, useRef, useState, useCallback } from "react"
import { ExternalLink, RefreshCw, Globe, Server } from "lucide-react"
import { listDeployments, type DeploymentRecord } from "@/lib/api"

/**
 * Deployment history panel.
 *
 * Polls every 15s instead of 5s, pauses when the tab is hidden,
 * and resumes when the tab becomes visible again.
 */
export function DeploymentHistory() {
  const [deployments, setDeployments] = useState<DeploymentRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchDeployments = useCallback(async () => {
    try {
      const data = await listDeployments()
      setDeployments(data)
      setLastUpdated(new Date())
    } catch {
      // Silent — history is non-critical
    }
  }, [])

  const manualRefresh = useCallback(async () => {
    setLoading(true)
    await fetchDeployments()
    setLoading(false)
  }, [fetchDeployments])

  useEffect(() => {
    // Initial fetch
    fetchDeployments()

    // Poll every 15s (reduced from 5s)
    const startPolling = () => {
      intervalRef.current = setInterval(fetchDeployments, 15_000)
    }

    const stopPolling = () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }

    startPolling()

    // Pause when tab is hidden, resume when visible
    const handleVisibility = () => {
      if (document.hidden) {
        stopPolling()
      } else {
        fetchDeployments() // refresh immediately on focus
        startPolling()
      }
    }

    document.addEventListener("visibilitychange", handleVisibility)

    return () => {
      stopPolling()
      document.removeEventListener("visibilitychange", handleVisibility)
    }
  }, [fetchDeployments])

  const statusColor = (status?: string) => {
    switch (status) {
      case "running":
        return "bg-green-400"
      case "degraded":
        return "bg-yellow-400"
      case "failed":
        return "bg-red-400"
      case "stopped":
        return "bg-gray-400"
      default:
        return "bg-blue-400"
    }
  }

  const formatTime = (iso?: string) => {
    if (!iso) return ""
    try {
      return new Date(iso).toLocaleString()
    } catch {
      return iso
    }
  }

  return (
    <div className="rounded-2xl border border-border bg-card/40 backdrop-blur-xl p-5">
      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Deployments</h2>
          <p className="text-xs text-muted-foreground mt-1">
            Persistent deployment history
            {lastUpdated && (
              <span className="ml-2 opacity-50">
                · updated {lastUpdated.toLocaleTimeString()}
              </span>
            )}
          </p>
        </div>
        <button
          onClick={manualRefresh}
          disabled={loading}
          className="rounded-lg border border-border bg-background px-3 py-1.5 text-xs hover:bg-accent transition flex items-center gap-1.5"
          title="Refresh deployment history"
        >
          <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* Deployment list */}
      <div className="space-y-3">
        {deployments.length === 0 && (
          <div className="rounded-xl border border-border bg-background/40 p-4 text-sm text-muted-foreground">
            No deployments yet. Upload a ZIP to deploy your first project.
          </div>
        )}

        {deployments.map((dep, index) => (
          <div
            key={`${dep.deployment_id}-${index}`}
            className="rounded-xl border border-border bg-background/40 p-4 space-y-3"
          >
            {/* Top row: name + status */}
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <div
                    className={`h-2 w-2 rounded-full shrink-0 ${statusColor(dep.status)}`}
                  />
                  <p className="font-medium text-sm truncate">
                    {dep.project_name || dep.deployment_id}
                  </p>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span className="capitalize">{dep.status || "unknown"}</span>
                  {dep.created_at && (
                    <>
                      <span>•</span>
                      <span>{formatTime(dep.created_at)}</span>
                    </>
                  )}
                  <span className="font-mono opacity-50">
                    #{dep.deployment_id.slice(0, 8)}
                  </span>
                </div>
              </div>

              {/* Open frontend button */}
              {dep.frontend_url && (
                <button
                  onClick={() => window.open(dep.frontend_url!, "_blank")}
                  className="shrink-0 rounded-lg border border-border bg-background px-3 py-2 text-xs hover:bg-accent transition flex items-center gap-1.5"
                >
                  <ExternalLink className="h-3 w-3" />
                  Open
                </button>
              )}
            </div>

            {/* URL rows */}
            {(dep.frontend_url || dep.backend_url) && (
              <div className="space-y-1.5">
                {dep.frontend_url && (
                  <div className="flex items-center gap-2 text-xs">
                    <Globe className="h-3 w-3 text-green-400 shrink-0" />
                    <span className="text-muted-foreground mr-1">Frontend:</span>
                    <a
                      href={dep.frontend_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-mono text-green-400 hover:underline truncate"
                    >
                      {dep.frontend_url}
                    </a>
                  </div>
                )}
                {dep.backend_url && (
                  <div className="flex items-center gap-2 text-xs">
                    <Server className="h-3 w-3 text-blue-400 shrink-0" />
                    <span className="text-muted-foreground mr-1">Backend:</span>
                    <a
                      href={dep.backend_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-mono text-blue-400 hover:underline truncate"
                    >
                      {dep.backend_url}
                    </a>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}