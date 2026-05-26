"use client"

import React, { useCallback, useState } from "react"
import {
  Upload,
  CheckCircle2,
  AlertCircle,
  X,
  Loader2,
  RefreshCw,
  Globe,
  Server,
  AlertTriangle,
} from "lucide-react"
import { useDropzone } from "react-dropzone"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { motion, AnimatePresence } from "framer-motion"
import { useDeployment } from "@/lib/deployment-context"
import { DeploymentLogs } from "./DeploymentLogs"

export function UploadZone() {
  const {
    deploymentId,
    stage,
    error,
    frontendUrl,
    backendUrl,
    deploymentUrl,
    deploymentStatus,
    uploadProgress,
    startUpload,
    reset,
  } = useDeployment()

  const isUploading = stage === "uploading"
  const isAnalyzing = stage === "analyzing"
  const isRunning = stage === "running"
  const isDegraded = stage === "degraded"
  const isError = stage === "error"
  const isProcessing = isUploading || isAnalyzing

  const [selectedFrontend, setSelectedFrontend] = useState<File | null>(null)
  const [selectedBackend, setSelectedBackend] = useState<File | null>(null)

  const onFrontendDrop = useCallback((acceptedFiles: File[]) => {
    const selected = acceptedFiles[0]
    if (!selected || !selected.name.endsWith(".zip")) return
    setSelectedFrontend(selected)
  }, [])

  const onBackendDrop = useCallback((acceptedFiles: File[]) => {
    const selected = acceptedFiles[0]
    if (!selected || !selected.name.endsWith(".zip")) return
    setSelectedBackend(selected)
  }, [])

  const frontendDropzone = useDropzone({
    onDrop: onFrontendDrop,
    accept: { "application/zip": [".zip"] },
    maxFiles: 1,
    multiple: false,
    disabled: isProcessing,
  })

  const backendDropzone = useDropzone({
    onDrop: onBackendDrop,
    accept: { "application/zip": [".zip"] },
    maxFiles: 1,
    multiple: false,
    disabled: isProcessing,
  })

  const formatSize = (bytes: number) => {
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(2)} MB`
  }

  const handleDeploy = () => {
    if (!selectedFrontend) return
    startUpload(selectedFrontend, selectedBackend || undefined)
  }

  return (
    <div className="space-y-4">
      {/* Drop zones */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Frontend Drop */}
        <div
          {...frontendDropzone.getRootProps()}
          className={cn(
            "relative rounded-xl border-2 border-dashed transition-all duration-300 cursor-pointer",
            "flex flex-col items-center justify-center gap-3 p-6 min-h-[180px]",
            frontendDropzone.isDragActive
              ? "border-primary/60 bg-primary/5"
              : "border-border/50 hover:border-primary/30 hover:bg-primary/[0.02]"
          )}
        >
          <input {...frontendDropzone.getInputProps()} />
          <div className="rounded-xl p-3 bg-primary/10 text-primary">
            <Upload className="h-6 w-6" />
          </div>
          <div className="text-center">
            <p className="text-sm font-semibold">Frontend ZIP</p>
            <p className="text-xs text-muted-foreground mt-1">
              React, Next.js, Vite, Vue
            </p>
          </div>
          {selectedFrontend && (
            <div className="w-full rounded-lg bg-chart-2/10 border border-chart-2/20 p-3">
              <p className="text-xs font-medium truncate">{selectedFrontend.name}</p>
              <p className="text-[10px] text-muted-foreground mt-1">
                {formatSize(selectedFrontend.size)}
              </p>
            </div>
          )}
        </div>

        {/* Backend Drop */}
        <div
          {...backendDropzone.getRootProps()}
          className={cn(
            "relative rounded-xl border-2 border-dashed transition-all duration-300 cursor-pointer",
            "flex flex-col items-center justify-center gap-3 p-6 min-h-[180px]",
            backendDropzone.isDragActive
              ? "border-chart-4/60 bg-chart-4/5"
              : "border-border/50 hover:border-chart-4/30 hover:bg-chart-4/[0.02]"
          )}
        >
          <input {...backendDropzone.getInputProps()} />
          <div className="rounded-xl p-3 bg-chart-4/10 text-chart-4">
            <Upload className="h-6 w-6" />
          </div>
          <div className="text-center">
            <p className="text-sm font-semibold">Backend ZIP</p>
            <p className="text-xs text-muted-foreground mt-1">
              FastAPI, Express, Django (optional)
            </p>
          </div>
          {selectedBackend && (
            <div className="w-full rounded-lg bg-chart-4/10 border border-chart-4/20 p-3">
              <p className="text-xs font-medium truncate">{selectedBackend.name}</p>
              <p className="text-[10px] text-muted-foreground mt-1">
                {formatSize(selectedBackend.size)}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Deploy button */}
      <Button
        id="deploy-button"
        className="w-full bg-gradient-to-r from-primary via-chart-4 to-chart-2 hover:opacity-90 text-white font-semibold h-11"
        disabled={!selectedFrontend || isProcessing}
        onClick={handleDeploy}
      >
        {isProcessing ? (
          <>
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            {isAnalyzing ? "Building & Deploying..." : "Uploading..."}
          </>
        ) : (
          <>
            <Upload className="h-4 w-4 mr-2" />
            Deploy Full Stack App
          </>
        )}
      </Button>

      {/* Upload progress */}
      <AnimatePresence>
        {isUploading && uploadProgress > 0 && uploadProgress < 100 && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="space-y-1"
          >
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>Uploading...</span>
              <span>{uploadProgress.toFixed(0)}%</span>
            </div>
            <div className="h-1.5 rounded-full bg-border overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-primary to-chart-2 transition-all"
                style={{ width: `${uploadProgress}%` }}
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Error */}
      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="flex items-start gap-2 text-destructive text-xs px-1"
          >
            <AlertCircle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
            <span>{error}</span>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Action buttons */}
      {(isRunning || isDegraded || isError) && (
        <motion.div
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex gap-2"
        >
          {isError && (
            <Button
              variant="default"
              size="sm"
              className="flex-1 bg-gradient-to-r from-primary to-chart-1 hover:opacity-90"
              onClick={reset}
              id="retry-upload-button"
            >
              <RefreshCw className="h-3.5 w-3.5 mr-1" />
              Try Again
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={reset}
            id="remove-file-button"
          >
            <X className="h-3.5 w-3.5 mr-1" />
            {isError ? "Clear" : "New Deployment"}
          </Button>
        </motion.div>
      )}

      {/* ── Success / Degraded banner ─────────────────────────────────────── */}
      <AnimatePresence>
        {(isRunning || isDegraded) && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className={cn(
              "rounded-xl border p-4 space-y-3",
              isRunning
                ? "border-chart-2/20 bg-chart-2/5"
                : "border-yellow-400/20 bg-yellow-400/5"
            )}
          >
            {/* Status header */}
            <div className="flex items-center gap-2">
              {isRunning ? (
                <CheckCircle2 className="h-4 w-4 text-chart-2" />
              ) : (
                <AlertTriangle className="h-4 w-4 text-yellow-400" />
              )}
              <p
                className={cn(
                  "text-sm font-semibold",
                  isRunning ? "text-chart-2" : "text-yellow-400"
                )}
              >
                {isRunning ? "Deployment Running" : "Deployment Degraded"}
              </p>
            </div>

            {/* URL list */}
            <div className="space-y-2">
              {(frontendUrl || deploymentUrl) && (
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <Globe className="h-3.5 w-3.5 text-chart-2 shrink-0" />
                    <div className="rounded bg-black/40 px-2 py-1 font-mono text-xs text-chart-2 truncate">
                      {frontendUrl || deploymentUrl}
                    </div>
                  </div>
                  <Button
                    size="sm"
                    className="shrink-0 bg-chart-2 hover:bg-chart-2/90 text-black text-xs h-7"
                    onClick={() =>
                      window.open(deploymentUrl || frontendUrl!, "_blank")
                    }
                    id="open-frontend-button"
                  >
                    Open
                  </Button>
                </div>
              )}

              {backendUrl && (
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <Server className="h-3.5 w-3.5 text-blue-400 shrink-0" />
                    <div className="rounded bg-black/40 px-2 py-1 font-mono text-xs text-blue-400 truncate">
                      {backendUrl}
                    </div>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    className="shrink-0 text-xs h-7 border-blue-400/30 text-blue-400 hover:bg-blue-400/10"
                    onClick={() => window.open(backendUrl, "_blank")}
                    id="open-backend-button"
                  >
                    Open
                  </Button>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Deployment logs */}
      {deploymentId && (
        <DeploymentLogs deploymentId={deploymentId} />
      )}
    </div>
  )
}
