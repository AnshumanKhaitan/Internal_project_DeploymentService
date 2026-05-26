"use client"

import React from "react"
import {
  Code2,
  Layers,
  Hash,
  Radio,
  FileText,
  Package,
  Play,
  FolderTree,
  HardDrive,
  FileArchive,
  Loader2,
} from "lucide-react"
import { motion, AnimatePresence } from "framer-motion"
import { Badge } from "@/components/ui/badge"
import { useDeployment } from "@/lib/deployment-context"
import { getRuntimeLabel, getFrameworkLabel, formatBytes } from "@/lib/api"

interface AnalysisItem {
  label: string
  value: string
  icon: React.ReactNode
  color: string
}

function AnalysisGrid({ items }: { items: AnalysisItem[] }) {
  return (
    <div className="grid grid-cols-2 gap-2.5">
      {items.map((item, index) => (
        <motion.div
          key={item.label}
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: index * 0.06, duration: 0.3 }}
          className="glass-card rounded-lg p-3 flex items-start gap-2.5 glass-card-hover transition-all duration-200"
        >
          <div className={`${item.color} mt-0.5 opacity-80`}>{item.icon}</div>
          <div className="min-w-0 flex-1">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
              {item.label}
            </p>
            <p className="text-sm font-semibold text-foreground/90 truncate mt-0.5">
              {item.value}
            </p>
          </div>
        </motion.div>
      ))}
    </div>
  )
}

export function ProjectAnalysis() {
  const { stage, analysis } = useDeployment()

  // Idle state — no upload yet
  if (stage === "idle") {
    return (
      <div className="flex flex-col items-center justify-center py-6 text-center">
        <div className="rounded-xl p-3 bg-muted/20 text-muted-foreground/40 mb-3">
          <FolderTree className="h-6 w-6" />
        </div>
        <p className="text-xs text-muted-foreground/60">
          Upload a project to see analysis results
        </p>
      </div>
    )
  }

  // Uploading / analyzing
  if (stage === "uploading" || stage === "analyzing") {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-center">
        <Loader2 className="h-6 w-6 text-primary animate-spin mb-3" />
        <p className="text-xs text-muted-foreground">
          {stage === "uploading" ? "Uploading project..." : "Scanning project structure..."}
        </p>
        {/* Skeleton grid */}
        <div className="grid grid-cols-2 gap-2.5 w-full mt-4">
          {[1, 2, 3, 4].map((i) => (
            <div
              key={i}
              className="glass-card rounded-lg p-3 animate-pulse"
            >
              <div className="h-2 w-12 bg-muted-foreground/10 rounded mb-2" />
              <div className="h-3 w-20 bg-muted-foreground/10 rounded" />
            </div>
          ))}
        </div>
      </div>
    )
  }

  // Error state
  if (stage === "error" || !analysis) {
    return (
      <div className="flex flex-col items-center justify-center py-6 text-center">
        <div className="rounded-xl p-3 bg-destructive/10 text-destructive/60 mb-3">
          <FolderTree className="h-6 w-6" />
        </div>
        <p className="text-xs text-muted-foreground/60">
          {stage === "error" ? "Analysis failed — try uploading again" : "No analysis data available"}
        </p>
      </div>
    )
  }

  // ─── Build analysis items from real data ─────────────────────────────

  const primaryItems: AnalysisItem[] = [
    {
      label: "Runtime",
      value: `${getRuntimeLabel(analysis.runtime)}${analysis.runtime_version ? ` ${analysis.runtime_version}` : ""}`,
      icon: <Code2 className="h-4 w-4" />,
      color: "text-chart-2",
    },
    {
      label: "Framework",
      value: `${getFrameworkLabel(analysis.framework)}${analysis.framework_version ? ` ${analysis.framework_version}` : ""}`,
      icon: <Layers className="h-4 w-4" />,
      color: "text-primary",
    },
    {
      label: "Port",
      value: String(analysis.detected_port),
      icon: <Radio className="h-4 w-4" />,
      color: "text-chart-4",
    },
    {
      label: "Dependencies",
      value: `${analysis.dependencies_count} packages`,
      icon: <Package className="h-4 w-4" />,
      color: "text-chart-3",
    },
  ]

  const secondaryItems: AnalysisItem[] = []

  if (analysis.startup_command) {
    secondaryItems.push({
      label: "Start Command",
      value: analysis.startup_command,
      icon: <Play className="h-4 w-4" />,
      color: "text-chart-2",
    })
  }

  if (analysis.entry_point) {
    secondaryItems.push({
      label: "Entry Point",
      value: analysis.entry_point,
      icon: <FileText className="h-4 w-4" />,
      color: "text-primary",
    })
  }

  secondaryItems.push({
    label: "Files",
    value: `${analysis.file_count} files`,
    icon: <FolderTree className="h-4 w-4" />,
    color: "text-muted-foreground",
  })

  secondaryItems.push({
    label: "Size",
    value: formatBytes(analysis.total_size_bytes),
    icon: <HardDrive className="h-4 w-4" />,
    color: "text-muted-foreground",
  })

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key="analysis-results"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="space-y-3"
      >
        {/* Primary analysis grid */}
        <AnalysisGrid items={primaryItems} />

        {/* Feature badges */}
        <div className="flex flex-wrap gap-1.5">
          {analysis.has_dockerfile && (
            <Badge
              variant="outline"
              className="text-[10px] h-5 gap-1 border-chart-2/30 text-chart-2"
            >
              <FileArchive className="h-2.5 w-2.5" />
              Dockerfile
            </Badge>
          )}
          {analysis.has_docker_compose && (
            <Badge
              variant="outline"
              className="text-[10px] h-5 gap-1 border-chart-4/30 text-chart-4"
            >
              <FileArchive className="h-2.5 w-2.5" />
              Docker Compose
            </Badge>
          )}
          {analysis.env_template_file && (
            <Badge
              variant="outline"
              className="text-[10px] h-5 gap-1 border-chart-3/30 text-chart-3"
            >
              <Hash className="h-2.5 w-2.5" />
              {analysis.env_template_file}
            </Badge>
          )}
          {analysis.scripts.length > 0 && (
            <Badge
              variant="outline"
              className="text-[10px] h-5 gap-1 border-primary/30 text-primary"
            >
              <Play className="h-2.5 w-2.5" />
              {analysis.scripts.length} scripts
            </Badge>
          )}
        </div>

        {/* Secondary info */}
        <AnalysisGrid items={secondaryItems} />

        {/* Scripts list (if detected) */}
        {analysis.scripts.length > 0 && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.3 }}
            className="space-y-1.5"
          >
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium px-1">
              Scripts
            </p>
            <div className="glass-card rounded-lg overflow-hidden">
              {analysis.scripts.slice(0, 6).map((script, idx) => (
                <div
                  key={script.name}
                  className={`flex items-center gap-2 px-3 py-1.5 text-xs ${
                    idx > 0 ? "border-t border-border/10" : ""
                  }`}
                >
                  <span className="font-mono text-chart-2 font-medium w-20 shrink-0 truncate">
                    {script.name}
                  </span>
                  <span className="font-mono text-muted-foreground/60 truncate">
                    {script.command}
                  </span>
                </div>
              ))}
              {analysis.scripts.length > 6 && (
                <div className="px-3 py-1.5 text-[10px] text-muted-foreground/40 border-t border-border/10">
                  +{analysis.scripts.length - 6} more scripts
                </div>
              )}
            </div>
          </motion.div>
        )}
      </motion.div>
    </AnimatePresence>
  )
}
