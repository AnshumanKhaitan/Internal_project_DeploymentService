"use client"

import React, { useState, useEffect, useRef } from "react"
import { Terminal, Circle, Copy, Check, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"
import { useDeployment } from "@/lib/deployment-context"
import { getRuntimeLabel, getFrameworkLabel } from "@/lib/api"

interface LogEntry {
  timestamp: string
  level: "info" | "warn" | "error" | "success" | "system"
  message: string
}

const levelColors: Record<string, string> = {
  info: "text-foreground/70",
  warn: "text-chart-3",
  error: "text-destructive",
  success: "text-chart-2",
  system: "text-primary/80",
}

const levelDotColors: Record<string, string> = {
  info: "text-foreground/30",
  warn: "text-chart-3",
  error: "text-destructive",
  success: "text-chart-2",
  system: "text-primary/60",
}

function getTimestamp(): string {
  const now = new Date()
  return now.toLocaleTimeString("en-GB", { hour12: false }).slice(0, 8)
}

export function DeploymentLogs() {
  const { stage, analysis, error, file, deploymentId } = useDeployment()
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [copied, setCopied] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Generate real-time logs based on pipeline stage changes
  useEffect(() => {
    if (stage === "idle") {
      setLogs([
        { timestamp: getTimestamp(), level: "system", message: "⬡ Anti Gravity Deployment Engine v2.1.0" },
        { timestamp: getTimestamp(), level: "system", message: "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" },
        { timestamp: getTimestamp(), level: "info", message: "Waiting for project upload..." },
      ])
    }
  }, [])

  useEffect(() => {
    if (stage === "uploading" && file) {
      setLogs((prev) => [
        ...prev,
        { timestamp: getTimestamp(), level: "info", message: `Uploading: ${file.name} (${(file.size / 1024 / 1024).toFixed(2)} MB)` },
      ])
    }
  }, [stage, file])

  useEffect(() => {
    if (stage === "analyzing") {
      const timer = setTimeout(() => {
        setLogs((prev) => [
          ...prev,
          { timestamp: getTimestamp(), level: "info", message: "Upload complete — analyzing project..." },
          { timestamp: getTimestamp(), level: "info", message: "Extracting ZIP archive..." },
          { timestamp: getTimestamp(), level: "info", message: "Scanning project structure recursively..." },
        ])
      }, 300)
      return () => clearTimeout(timer)
    }
  }, [stage])

  useEffect(() => {
    if (stage === "ready" && analysis) {
      const newLogs: LogEntry[] = [
        {
          timestamp: getTimestamp(),
          level: "success",
          message: `Detected runtime: ${getRuntimeLabel(analysis.runtime)}${analysis.runtime_version ? ` ${analysis.runtime_version}` : ""}`,
        },
        {
          timestamp: getTimestamp(),
          level: "success",
          message: `Detected framework: ${getFrameworkLabel(analysis.framework)}${analysis.framework_version ? ` ${analysis.framework_version}` : ""}`,
        },
        {
          timestamp: getTimestamp(),
          level: "info",
          message: `Found ${analysis.dependencies_count} dependencies`,
        },
        {
          timestamp: getTimestamp(),
          level: "info",
          message: `Scanned ${analysis.file_count} files`,
        },
      ]

      if (analysis.startup_command) {
        newLogs.push({
          timestamp: getTimestamp(),
          level: "info",
          message: `Startup command: ${analysis.startup_command}`,
        })
      }

      if (analysis.detected_port) {
        newLogs.push({
          timestamp: getTimestamp(),
          level: "info",
          message: `Detected port: ${analysis.detected_port}`,
        })
      }

      if (analysis.has_dockerfile) {
        newLogs.push({
          timestamp: getTimestamp(),
          level: "success",
          message: "Found existing Dockerfile",
        })
      }

      if (analysis.env_template_keys.length > 0) {
        newLogs.push({
          timestamp: getTimestamp(),
          level: "info",
          message: `Detected ${analysis.env_template_keys.length} env variables from ${analysis.env_template_file}`,
        })
      }

      newLogs.push(
        { timestamp: getTimestamp(), level: "system", message: "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" },
        { timestamp: getTimestamp(), level: "success", message: `✔ Analysis complete — deployment ${deploymentId} ready` },
      )

      // Animate logs in one by one
      let idx = 0
      const interval = setInterval(() => {
        if (idx < newLogs.length) {
          setLogs((prev) => [...prev, newLogs[idx]])
          idx++
        } else {
          clearInterval(interval)
        }
      }, 150)

      return () => clearInterval(interval)
    }
  }, [stage, analysis, deploymentId])

  useEffect(() => {
    if (stage === "error" && error) {
      setLogs((prev) => [
        ...prev,
        { timestamp: getTimestamp(), level: "error", message: `Error: ${error}` },
        { timestamp: getTimestamp(), level: "system", message: "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" },
        { timestamp: getTimestamp(), level: "error", message: "✘ Upload/analysis failed" },
      ])
    }
  }, [stage, error])

  // Auto-scroll
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [logs])

  const copyLogs = () => {
    const text = logs
      .map((log) => `[${log.timestamp}] ${log.message}`)
      .join("\n")
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="terminal-bg rounded-lg overflow-hidden">
      {/* Terminal header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border/30 bg-background/30">
        <div className="flex items-center gap-2">
          <div className="flex gap-1.5">
            <div className="w-2.5 h-2.5 rounded-full bg-destructive/70" />
            <div className="w-2.5 h-2.5 rounded-full bg-chart-3/70" />
            <div className="w-2.5 h-2.5 rounded-full bg-chart-2/70" />
          </div>
          <div className="flex items-center gap-1.5 ml-2">
            <Terminal className="h-3 w-3 text-muted-foreground" />
            <span className="text-[10px] font-mono text-muted-foreground uppercase tracking-wider">
              deployment logs
            </span>
            {(stage === "uploading" || stage === "analyzing") && (
              <Loader2 className="h-2.5 w-2.5 text-primary animate-spin ml-1" />
            )}
          </div>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6 text-muted-foreground hover:text-foreground"
          onClick={copyLogs}
          id="copy-logs-button"
        >
          {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
        </Button>
      </div>

      {/* Log output */}
      <ScrollArea
        ref={scrollRef}
        className="h-[220px] p-3 font-mono text-xs leading-relaxed"
        id="deployment-logs-scroll"
      >
        {logs.filter(Boolean).map((log, i) => (
          <div
            key={`${log.timestamp}-${i}`}
            className={cn(
  "flex items-start gap-2 log-line",
 levelColors[log?.level || "info"]
)}
          >
            <Circle
              className={cn("h-1.5 w-1.5 mt-[5px] shrink-0 fill-current", levelDotColors[log?.level || "info"])}
            />
            <span className="text-muted-foreground/40 select-none shrink-0">
              {log.timestamp}
            </span>
            <span className="break-all">{log.message}</span>
          </div>
        ))}
        {(stage === "uploading" || stage === "analyzing") && (
          <div className="flex items-center gap-1.5 mt-1 text-muted-foreground/40">
            <span className="inline-block w-1.5 h-3 bg-primary/60 animate-pulse" />
          </div>
        )}
      </ScrollArea>
    </div>
  )
}
