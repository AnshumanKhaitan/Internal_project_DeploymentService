"use client"

import { useEffect, useState } from "react"

interface Props {
  deploymentId: string
}

export function DeploymentLogs({
  deploymentId,
}: Props) {

  const [logs, setLogs] =
    useState<string[]>([])

  useEffect(() => {

  if (!deploymentId) {
    return
  }

  const fetchLogs = async () => {

    try {

      const response =
        await fetch(
          `http://localhost:8000/api/deployments/${deploymentId}/logs`
        )

      if (!response.ok) {
        return
      }

      const data =
        await response.json()

      setLogs(data.logs || [])

    } catch (error) {

      console.error(
        "Failed to fetch logs:",
        error
      )
    }
  }

  fetchLogs()

}, [deploymentId])

  return (
    <div className="rounded-xl border border-border bg-black p-4 mt-6">
      <div className="mb-3 text-xs uppercase tracking-widest text-green-400">
        Deployment Logs
      </div>

      <div className="space-y-1 font-mono text-xs text-green-400 max-h-80 overflow-auto">
        {logs.map((log, idx) => (
          <div key={idx}>
            {log}
          </div>
        ))}
      </div>
    </div>
  )
}