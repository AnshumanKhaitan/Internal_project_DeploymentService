"use client"

import React from "react"
import { Container, Box, Route, MemoryStick, Cpu, Loader2, Settings2 } from "lucide-react"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { motion } from "framer-motion"
import { useDeployment } from "@/lib/deployment-context"
import { getRuntimeLabel, getFrameworkLabel } from "@/lib/api"

export function DeploymentConfig() {
  const { stage, analysis, deploymentId } = useDeployment()

  // Idle state
  if (stage === "idle") {
    return (
      <div className="flex flex-col items-center justify-center py-6 text-center">
        <div className="rounded-xl p-3 bg-muted/20 text-muted-foreground/40 mb-3">
          <Settings2 className="h-6 w-6" />
        </div>
        <p className="text-xs text-muted-foreground/60">
          Configuration will be available after project analysis
        </p>
      </div>
    )
  }

  // Loading state
  if (stage === "uploading" || stage === "analyzing") {
    return (
      <div className="flex flex-col items-center justify-center py-6 text-center">
        <Loader2 className="h-5 w-5 text-primary animate-spin mb-3" />
        <p className="text-xs text-muted-foreground">Preparing configuration...</p>
      </div>
    )
  }

  // Generate config fields from analysis
  const projectName = analysis
    ? `${getFrameworkLabel(analysis.framework).toLowerCase().replace(/[\s.]/g, "-")}-app`
    : "project"

  const configFields = [
    {
      label: "Image Name",
      value: `ag-deploy-${projectName}`,
      icon: <Container className="h-3.5 w-3.5" />,
      id: "config-image-name",
    },
    {
      label: "Container Name",
      value: `${projectName}-${deploymentId || "prod"}`,
      icon: <Box className="h-3.5 w-3.5" />,
      id: "config-container-name",
    },
    {
      label: "Route",
      value: `/${projectName}`,
      icon: <Route className="h-3.5 w-3.5" />,
      id: "config-route",
    },
    {
      label: "Memory",
      value: "512",
      icon: <MemoryStick className="h-3.5 w-3.5" />,
      id: "config-memory",
      suffix: "MB",
    },
    {
      label: "CPU",
      value: "0.5",
      icon: <Cpu className="h-3.5 w-3.5" />,
      id: "config-cpu",
      suffix: "cores",
    },
  ]

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="space-y-3"
    >
      {configFields.map((field, idx) => (
        <motion.div
          key={field.id}
          initial={{ opacity: 0, x: -8 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: idx * 0.05 }}
          className="space-y-1.5"
        >
          <Label
            htmlFor={field.id}
            className="text-xs text-muted-foreground flex items-center gap-1.5"
          >
            <span className="text-primary/70">{field.icon}</span>
            {field.label}
          </Label>
          <div className="relative">
            <Input
              id={field.id}
              defaultValue={field.value}
              className="font-mono text-xs h-8 bg-background/50 border-border/40 focus:border-primary/40"
            />
            {field.suffix && (
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-muted-foreground/60 font-medium uppercase tracking-wide">
                {field.suffix}
              </span>
            )}
          </div>
        </motion.div>
      ))}
    </motion.div>
  )
}
