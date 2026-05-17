"use client"

import React from "react"
import {
  ExternalLink,
  RefreshCw,
  Loader2,
  CheckCircle2,
  Globe,
  Signal,
  Upload,
  Rocket,
  Package,
  Code2,
  Layers,
  Radio,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { motion } from "framer-motion"
import { useDeployment } from "@/lib/deployment-context"
import { getRuntimeLabel, getFrameworkLabel, formatBytes } from "@/lib/api"

export function LivePreview() {
  const { stage, analysis, deploymentId, file } = useDeployment()

  const statusConfig = {
    idle: { label: "Waiting", color: "text-muted-foreground", dotColor: "bg-muted-foreground" },
    uploading: { label: "Uploading", color: "text-chart-3", dotColor: "bg-chart-3" },
    analyzing: { label: "Analyzing", color: "text-primary", dotColor: "bg-primary" },
    ready: { label: "Ready", color: "text-chart-2", dotColor: "bg-chart-2" },
    deploying: { label: "Deploying", color: "text-chart-3", dotColor: "bg-chart-3" },
    deployed: { label: "Live", color: "text-chart-2", dotColor: "bg-chart-2" },
    error: { label: "Error", color: "text-destructive", dotColor: "bg-destructive" },
  }

  const currentStatus = statusConfig[stage]

  return (
    <div className="h-full flex flex-col">
      {/* Preview header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border/30">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Globe className="h-4 w-4 text-primary/70" />
            <span className="text-sm font-semibold text-foreground/90">Live Preview</span>
          </div>
          <Badge
            variant="outline"
            className={cn(
              "text-[10px] gap-1.5 px-2 py-0.5 font-medium",
              currentStatus.color
            )}
          >
            <span className={cn("h-1.5 w-1.5 rounded-full status-pulse", currentStatus.dotColor)} />
            {currentStatus.label}
          </Badge>
        </div>
        <div className="flex items-center gap-1.5">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-muted-foreground"
            id="refresh-preview-button"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-muted-foreground"
            id="external-link-button"
          >
            <ExternalLink className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Preview content */}
      <div className="flex-1 relative overflow-hidden">
        {/* Grid pattern background */}
        <div className="absolute inset-0 grid-pattern opacity-30" />

        {/* Idle state */}
        {stage === "idle" && (
          <div className="absolute inset-0 flex flex-col items-center justify-center z-10">
            <motion.div
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              className="glass-card rounded-2xl p-8 flex flex-col items-center gap-5 max-w-xs mx-auto"
            >
              <div className="rounded-xl p-4 bg-muted/30">
                <Signal className="h-8 w-8 text-muted-foreground/50" />
              </div>
              <div className="text-center">
                <p className="text-sm font-semibold text-foreground/80">No Active Deployment</p>
                <p className="text-xs text-muted-foreground mt-1">
                  Upload a project ZIP to get started
                </p>
              </div>
            </motion.div>
          </div>
        )}

        {/* Uploading / Analyzing state */}
        {(stage === "uploading" || stage === "analyzing") && (
          <div className="absolute inset-0 flex flex-col items-center justify-center z-10">
            <motion.div
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              className="glass-card rounded-2xl p-8 flex flex-col items-center gap-5 max-w-xs mx-auto"
            >
              <div className="relative">
                <Loader2 className="h-10 w-10 text-primary animate-spin" />
                <div className="absolute inset-0 rounded-full bg-primary/10 animate-ping" />
              </div>
              <div className="text-center space-y-2">
                <p className="text-sm font-semibold text-foreground/80">
                  {stage === "uploading" ? "Uploading Project..." : "Analyzing Project..."}
                </p>
                <p className="text-xs text-muted-foreground">
                  {stage === "uploading"
                    ? `Sending ${file?.name || "file"} to the server`
                    : "Scanning files, detecting stack & dependencies"}
                </p>
              </div>
            </motion.div>
          </div>
        )}

        {/* Ready state — show analysis summary */}
        {stage === "ready" && analysis && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.5 }}
            className="absolute inset-0 z-10"
          >
            <div className="h-full w-full flex flex-col items-center justify-center bg-gradient-to-br from-background via-primary/[0.02] to-chart-2/[0.03]">
              <motion.div
                initial={{ y: 20, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ delay: 0.2 }}
                className="glass-card rounded-2xl p-8 max-w-md mx-auto text-center space-y-5"
              >
                {/* Header */}
                <div className="flex items-center justify-center gap-2 mb-2">
                  <CheckCircle2 className="h-6 w-6 text-chart-2" />
                  <span className="text-lg font-bold bg-gradient-to-r from-chart-2 to-primary bg-clip-text text-transparent">
                    Analysis Complete
                  </span>
                </div>

                {/* Stack info grid */}
                <div className="grid grid-cols-2 gap-3">
                  <div className="glass-card rounded-lg p-3 text-left">
                    <div className="flex items-center gap-2 mb-1">
                      <Code2 className="h-3.5 w-3.5 text-chart-2" />
                      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Runtime</span>
                    </div>
                    <p className="text-sm font-semibold text-foreground/90">
                      {getRuntimeLabel(analysis.runtime)}
                      {analysis.runtime_version && (
                        <span className="text-xs text-muted-foreground ml-1">{analysis.runtime_version}</span>
                      )}
                    </p>
                  </div>
                  <div className="glass-card rounded-lg p-3 text-left">
                    <div className="flex items-center gap-2 mb-1">
                      <Layers className="h-3.5 w-3.5 text-primary" />
                      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Framework</span>
                    </div>
                    <p className="text-sm font-semibold text-foreground/90">
                      {getFrameworkLabel(analysis.framework)}
                      {analysis.framework_version && (
                        <span className="text-xs text-muted-foreground ml-1">{analysis.framework_version}</span>
                      )}
                    </p>
                  </div>
                  <div className="glass-card rounded-lg p-3 text-left">
                    <div className="flex items-center gap-2 mb-1">
                      <Radio className="h-3.5 w-3.5 text-chart-4" />
                      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Port</span>
                    </div>
                    <p className="text-sm font-semibold text-foreground/90">{analysis.detected_port}</p>
                  </div>
                  <div className="glass-card rounded-lg p-3 text-left">
                    <div className="flex items-center gap-2 mb-1">
                      <Package className="h-3.5 w-3.5 text-chart-3" />
                      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Dependencies</span>
                    </div>
                    <p className="text-sm font-semibold text-foreground/90">{analysis.dependencies_count}</p>
                  </div>
                </div>

                {/* Stats row */}
                <div className="grid grid-cols-3 gap-3 pt-3 border-t border-border/20">
                  <div>
                    <p className="text-lg font-bold text-chart-2">{analysis.file_count}</p>
                    <p className="text-[10px] text-muted-foreground">Files</p>
                  </div>
                  <div>
                    <p className="text-lg font-bold text-primary">{formatBytes(analysis.total_size_bytes)}</p>
                    <p className="text-[10px] text-muted-foreground">Size</p>
                  </div>
                  <div>
                    <p className="text-lg font-bold text-chart-3">{analysis.scripts.length}</p>
                    <p className="text-[10px] text-muted-foreground">Scripts</p>
                  </div>
                </div>

                {/* Deploy button */}
                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.5 }}
                >
                  <Button
                    className="w-full bg-gradient-to-r from-primary via-chart-4 to-chart-2 hover:opacity-90 text-white font-semibold gap-2 h-10"
                    id="deploy-application-button"
                  >
                    <Rocket className="h-4 w-4" />
                    Deploy Application
                  </Button>
                  <p className="text-[10px] text-muted-foreground/50 mt-2">
                    Deployment ID: {deploymentId}
                  </p>
                </motion.div>
              </motion.div>
            </div>
          </motion.div>
        )}

        {/* Error state */}
        {stage === "error" && (
          <div className="absolute inset-0 flex flex-col items-center justify-center z-10">
            <motion.div
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              className="glass-card rounded-2xl p-8 flex flex-col items-center gap-5 max-w-xs mx-auto"
            >
              <div className="rounded-xl p-4 bg-destructive/10">
                <Signal className="h-8 w-8 text-destructive/70" />
              </div>
              <div className="text-center">
                <p className="text-sm font-semibold text-foreground/80">Upload Failed</p>
                <p className="text-xs text-muted-foreground mt-1">
                  Check the logs for error details
                </p>
              </div>
            </motion.div>
          </div>
        )}
      </div>

      {/* URL bar */}
      <div className="px-4 py-2.5 border-t border-border/30 bg-background/30">
        <div className="flex items-center gap-2 bg-muted/20 rounded-md px-3 py-1.5">
          <div className={cn(
            "h-2 w-2 rounded-full shrink-0",
            stage === "ready" ? "bg-chart-2 status-pulse" : "bg-muted-foreground/30"
          )} />
          <span className="text-xs font-mono text-muted-foreground truncate">
            {stage === "ready" && deploymentId
              ? `https://deploy.antigravity.dev/${deploymentId}`
              : "Waiting for deployment..."}
          </span>
        </div>
      </div>
    </div>
  )
}
