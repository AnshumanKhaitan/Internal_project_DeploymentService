"use client"

import React from "react"
import {
  ExternalLink,
  RefreshCw,
  Loader2,
  CheckCircle2,
  Globe,
  Signal,
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

import {
  getRuntimeLabel,
  getFrameworkLabel,
  formatBytes,
} from "@/lib/api"

export function LivePreview() {

  const {
    stage,
    analysis,
    deploymentId,
    deploymentUrl,
    frontendFile,
  } = useDeployment()

  const statusConfig = {
    idle: {
      label: "Waiting",
      color: "text-muted-foreground",
      dotColor: "bg-muted-foreground",
    },

    uploading: {
      label: "Uploading",
      color: "text-chart-3",
      dotColor: "bg-chart-3",
    },

    analyzing: {
      label: "Analyzing",
      color: "text-primary",
      dotColor: "bg-primary",
    },

    ready: {
      label: "Ready",
      color: "text-chart-2",
      dotColor: "bg-chart-2",
    },

    building: {
      label: "Building",
      color: "text-chart-3",
      dotColor: "bg-chart-3",
    },

    starting: {
      label: "Starting",
      color: "text-chart-3",
      dotColor: "bg-chart-3",
    },

    running: {
      label: "Live",
      color: "text-chart-2",
      dotColor: "bg-chart-2",
    },

    degraded: {
      label: "Degraded",
      color: "text-yellow-400",
      dotColor: "bg-yellow-400",
    },

    error: {
      label: "Error",
      color: "text-destructive",
      dotColor: "bg-destructive",
    },
  }

  const currentStatus =
    statusConfig[stage as keyof typeof statusConfig] || statusConfig.idle

  return (

    <div className="h-full flex flex-col">

      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border/30">

        <div className="flex items-center gap-3">

          <div className="flex items-center gap-2">
            <Globe className="h-4 w-4 text-primary/70" />

            <span className="text-sm font-semibold text-foreground/90">
              Live Preview
            </span>
          </div>

          <Badge
            variant="outline"
            className={cn(
              "text-[10px] gap-1.5 px-2 py-0.5 font-medium",
              currentStatus.color
            )}
          >
            <span
              className={cn(
                "h-1.5 w-1.5 rounded-full status-pulse",
                currentStatus.dotColor
              )}
            />

            {currentStatus.label}
          </Badge>
        </div>

        <div className="flex items-center gap-1.5">

          {/* Refresh */}
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-muted-foreground"
            onClick={() => {

              if (deploymentUrl) {

                window.open(
                  deploymentUrl,
                  "_blank"
                )
              }
            }}
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>

          {/* External */}
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-muted-foreground"
            onClick={() => {

              if (deploymentUrl) {

                window.open(
                  deploymentUrl,
                  "_blank"
                )
              }
            }}
          >
            <ExternalLink className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Preview Area */}
      <div className="flex-1 relative">

        {/* Background — pointer-events-none so it never blocks the iframe */}
        <div className="absolute inset-0 grid-pattern opacity-30 pointer-events-none" />

        {/* ─── LIVE PREVIEW IFRAME ─────────────────────────────────────── */}
        {deploymentUrl && (
          <iframe
            key={deploymentUrl}
            src={deploymentUrl}
            className="absolute inset-0 w-full h-full border-0 bg-white"
            style={{ zIndex: 30, pointerEvents: "auto" }}
            title="Live Preview"
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals allow-downloads"
          />
        )}

        {/* Idle — only when no URL, never blocks iframe */}
        {stage === "idle" && !deploymentUrl && (
          <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none" style={{ zIndex: 10 }}>
            <motion.div
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              className="glass-card rounded-2xl p-8 flex flex-col items-center gap-5 max-w-xs mx-auto pointer-events-auto"
            >
              <div className="rounded-xl p-4 bg-muted/30">
                <Signal className="h-8 w-8 text-muted-foreground/50" />
              </div>
              <div className="text-center">
                <p className="text-sm font-semibold text-foreground/80">No Active Deployment</p>
                <p className="text-xs text-muted-foreground mt-1">Upload a project ZIP to get started</p>
              </div>
            </motion.div>
          </div>
        )}

        {/* Uploading / Building — only when no URL yet, never blocks iframe */}
        {(stage === "uploading" || stage === "analyzing" || stage === "building" || stage === "starting")
          && !deploymentUrl && (
          <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none" style={{ zIndex: 10 }}>
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
                <p className="text-sm font-semibold text-foreground/80">Deploying Application...</p>
                <p className="text-xs text-muted-foreground">{frontendFile?.name}</p>
              </div>
            </motion.div>
          </div>
        )}

        {/* Ready Analysis */}
        {
          false /* 'ready' stage removed — analysis flows directly to building */
          && analysis
          && !deploymentUrl && (

            <motion.div
              initial={{ opacity: 0 }}

              animate={{ opacity: 1 }}

              transition={{
                duration: 0.5,
              }}

              className="absolute inset-0 z-10"
            >

              <div className="h-full w-full flex flex-col items-center justify-center bg-gradient-to-br from-background via-primary/[0.02] to-chart-2/[0.03]">

                <motion.div
                  initial={{
                    y: 20,
                    opacity: 0,
                  }}

                  animate={{
                    y: 0,
                    opacity: 1,
                  }}

                  transition={{
                    delay: 0.2,
                  }}

                  className="glass-card rounded-2xl p-8 max-w-md mx-auto text-center space-y-5"
                >

                  <div className="flex items-center justify-center gap-2 mb-2">

                    <CheckCircle2 className="h-6 w-6 text-chart-2" />

                    <span className="text-lg font-bold bg-gradient-to-r from-chart-2 to-primary bg-clip-text text-transparent">
                      Analysis Complete
                    </span>
                  </div>

                  <div className="grid grid-cols-2 gap-3">

                    <div className="glass-card rounded-lg p-3 text-left">

                      <div className="flex items-center gap-2 mb-1">

                        <Code2 className="h-3.5 w-3.5 text-chart-2" />

                        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
                          Runtime
                        </span>
                      </div>

                      <p className="text-sm font-semibold text-foreground/90">
                        {getRuntimeLabel(
                          analysis?.runtime ?? ''
                        )}
                      </p>
                    </div>

                    <div className="glass-card rounded-lg p-3 text-left">

                      <div className="flex items-center gap-2 mb-1">

                        <Layers className="h-3.5 w-3.5 text-primary" />

                        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
                          Framework
                        </span>
                      </div>

                      <p className="text-sm font-semibold text-foreground/90">
                        {getFrameworkLabel(
                          analysis?.framework ?? ''
                        )}
                      </p>
                    </div>

                    <div className="glass-card rounded-lg p-3 text-left">

                      <div className="flex items-center gap-2 mb-1">

                        <Radio className="h-3.5 w-3.5 text-chart-4" />

                        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
                          Port
                        </span>
                      </div>

                      <p className="text-sm font-semibold text-foreground/90">
                        {analysis?.detected_port}
                      </p>
                    </div>

                    <div className="glass-card rounded-lg p-3 text-left">

                      <div className="flex items-center gap-2 mb-1">

                        <Package className="h-3.5 w-3.5 text-chart-3" />

                        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
                          Dependencies
                        </span>
                      </div>

                      <p className="text-sm font-semibold text-foreground/90">
                        {analysis?.dependencies_count}
                      </p>
                    </div>
                  </div>

                  <Button
                    className="w-full bg-gradient-to-r from-primary via-chart-4 to-chart-2 hover:opacity-90 text-white font-semibold gap-2 h-10"
                  >
                    <Rocket className="h-4 w-4" />
                    Deployment Ready
                  </Button>

                  <p className="text-[10px] text-muted-foreground/50">
                    Deployment ID: {deploymentId}
                  </p>
                </motion.div>
              </div>
            </motion.div>
          )
        }

        {/* Error — only when no URL so it never overlaps a running iframe */}
        {stage === "error" && !deploymentUrl && (
          <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none" style={{ zIndex: 10 }}>
            <motion.div
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              className="glass-card rounded-2xl p-8 flex flex-col items-center gap-5 max-w-xs mx-auto pointer-events-auto"
            >
              <div className="rounded-xl p-4 bg-destructive/10">
                <Signal className="h-8 w-8 text-destructive/70" />
              </div>
              <div className="text-center">
                <p className="text-sm font-semibold text-foreground/80">Deployment Failed</p>
                <p className="text-xs text-muted-foreground mt-1">Check deployment logs</p>
              </div>
            </motion.div>
          </div>
        )}
      </div>

      {/* URL Bar */}
      <div className="px-4 py-2.5 border-t border-border/30 bg-background/30">

        <div className="flex items-center gap-2 bg-muted/20 rounded-md px-3 py-1.5">

          <div
            className={cn(
              "h-2 w-2 rounded-full shrink-0",

              deploymentUrl
                ? "bg-chart-2 status-pulse"
                : "bg-muted-foreground/30"
            )}
          />

          <span className="text-xs font-mono text-muted-foreground truncate">

            {
              deploymentUrl
                ? deploymentUrl
                : "Waiting for deployment..."
            }
          </span>
        </div>
      </div>
    </div>
  )
}