"use client"

import React, { useState } from "react"
import { Plus, Trash2, Eye, EyeOff, Lock, KeyRound, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { motion, AnimatePresence } from "framer-motion"
import { Badge } from "@/components/ui/badge"
import { useDeployment, type EnvVar } from "@/lib/deployment-context"

export function EnvVariables() {
  const { stage, analysis, envVars, setEnvVars } = useDeployment()
  const [visibleSecrets, setVisibleSecrets] = useState<Set<string>>(new Set())

  // Idle state
  if (stage === "idle") {
    return (
      <div className="flex flex-col items-center justify-center py-6 text-center">
        <div className="rounded-xl p-3 bg-muted/20 text-muted-foreground/40 mb-3">
          <KeyRound className="h-6 w-6" />
        </div>
        <p className="text-xs text-muted-foreground/60">
          Environment variables will appear after project analysis
        </p>
      </div>
    )
  }

  // Loading state
  if (stage === "uploading" || stage === "analyzing") {
    return (
      <div className="flex flex-col items-center justify-center py-6 text-center">
        <Loader2 className="h-5 w-5 text-primary animate-spin mb-3" />
        <p className="text-xs text-muted-foreground">Detecting environment variables...</p>
      </div>
    )
  }

  const addVar = () => {
    const newVar: EnvVar = {
      id: `env-${Date.now()}`,
      key: "",
      value: "",
      isSecret: false,
    }
    setEnvVars((prev) => [...prev, newVar])
  }

  const removeVar = (id: string) => {
    setEnvVars((prev) => prev.filter((v) => v.id !== id))
  }

  const toggleSecret = (id: string) => {
    setVisibleSecrets((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const updateVar = (id: string, field: "key" | "value", val: string) => {
    setEnvVars((prev) =>
      prev.map((v) => (v.id === id ? { ...v, [field]: val } : v))
    )
  }

  const toggleIsSecret = (id: string) => {
    setEnvVars((prev) =>
      prev.map((v) => (v.id === id ? { ...v, isSecret: !v.isSecret } : v))
    )
  }

  return (
    <div className="space-y-2.5">
      {/* Source info */}
      {analysis?.env_template_file && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex items-center gap-2 text-xs text-muted-foreground/60 px-1 mb-1"
        >
          <Badge
            variant="outline"
            className="text-[10px] h-5 gap-1 border-chart-3/30 text-chart-3"
          >
            Auto-detected from {analysis.env_template_file}
          </Badge>
        </motion.div>
      )}

      {/* No env vars message */}
      {envVars.length === 0 && stage !== "idle" && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="text-center py-4"
        >
          <p className="text-xs text-muted-foreground/50">
            No environment template detected
          </p>
          <p className="text-[10px] text-muted-foreground/40 mt-0.5">
            Add variables manually below
          </p>
        </motion.div>
      )}

      {/* Env var rows */}
      <AnimatePresence>
        {envVars.map((envVar, index) => (
          <motion.div
            key={envVar.id}
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="flex items-center gap-2"
          >
            <div className="flex-1 flex gap-2">
              <Input
                placeholder="KEY"
                value={envVar.key}
                onChange={(e) => updateVar(envVar.id, "key", e.target.value)}
                className="font-mono text-xs h-8 bg-background/50 border-border/40 focus:border-primary/40"
                id={`env-key-${index}`}
              />
              <div className="relative flex-1">
                <Input
                  placeholder="Value"
                  value={envVar.value}
                  onChange={(e) => updateVar(envVar.id, "value", e.target.value)}
                  type={envVar.isSecret && !visibleSecrets.has(envVar.id) ? "password" : "text"}
                  className="font-mono text-xs h-8 bg-background/50 border-border/40 pr-8 focus:border-primary/40"
                  id={`env-value-${index}`}
                />
                {envVar.isSecret && (
                  <button
                    onClick={() => toggleSecret(envVar.id)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                    type="button"
                  >
                    {visibleSecrets.has(envVar.id) ? (
                      <EyeOff className="h-3 w-3" />
                    ) : (
                      <Eye className="h-3 w-3" />
                    )}
                  </button>
                )}
              </div>
            </div>
            <button
              onClick={() => toggleIsSecret(envVar.id)}
              className={`shrink-0 transition-colors cursor-pointer ${
                envVar.isSecret ? "text-chart-3/80" : "text-muted-foreground/30 hover:text-muted-foreground/60"
              }`}
              type="button"
              title={envVar.isSecret ? "Marked as secret" : "Mark as secret"}
            >
              <Lock className="h-3 w-3" />
            </button>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => removeVar(envVar.id)}
              className="h-8 w-8 text-muted-foreground hover:text-destructive shrink-0"
              id={`env-delete-${index}`}
            >
              <Trash2 className="h-3 w-3" />
            </Button>
          </motion.div>
        ))}
      </AnimatePresence>

      <Button
        variant="ghost"
        size="sm"
        onClick={addVar}
        className="w-full border border-dashed border-border/40 text-muted-foreground hover:text-foreground hover:border-primary/30 h-8 text-xs"
        id="add-env-var-button"
      >
        <Plus className="h-3 w-3" />
        Add Variable
      </Button>
    </div>
  )
}
