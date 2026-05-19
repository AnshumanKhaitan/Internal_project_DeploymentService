"use client"

import React, { useCallback } from "react"
import { Upload, FileArchive, CheckCircle2, AlertCircle, X, Loader2, RefreshCw } from "lucide-react"
import { useDropzone } from "react-dropzone"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { motion, AnimatePresence } from "framer-motion"
import { useDeployment } from "@/lib/deployment-context"
import {
  DeploymentLogs,
} from "./DeploymentLogs"

export function UploadZone() {
  const {
    deploymentId,
    stage,
    error,
    file,
    deploymentUrl,
    deploymentStatus,
    uploadProgress,
    startUpload,
    reset,
  } = useDeployment()

  const isUploading = stage === "uploading"
  const isAnalyzing = stage === "analyzing"
  const isReady = stage === "running"
  const isError = stage === "error"
  const isProcessing = isUploading || isAnalyzing

  const onDrop = useCallback(
    (acceptedFiles: File[]) => {
      const selected = acceptedFiles[0]
      if (!selected) return

      if (!selected.name.endsWith(".zip")) {
        return
      }

      if (selected.size > 500 * 1024 * 1024) {
        return
      }

      startUpload(selected)
    },
    [startUpload]
  )

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "application/zip": [".zip"] },
    maxFiles: 1,
    multiple: false,
    disabled: isProcessing,
  })

  const formatSize = (bytes: number) => {
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(2)} MB`
  }

  return (
    <div className="space-y-3">
      <div
        {...getRootProps()}
        className={cn(
          "relative rounded-xl border-2 border-dashed transition-all duration-300 cursor-pointer group",
          "flex flex-col items-center justify-center gap-3 p-8",
          isProcessing && "pointer-events-none",
          isDragActive
            ? "border-primary/60 bg-primary/5 upload-zone-active"
            : "border-border/50 hover:border-primary/30 hover:bg-primary/[0.02]",
          isReady && "border-chart-2/40 bg-chart-2/[0.03]",
          isError && "border-destructive/40 bg-destructive/[0.03]"
        )}
      >
        <input {...getInputProps()} id="upload-zip-input" />

        <AnimatePresence mode="wait">
          {!file ? (
            <motion.div
              key="upload-prompt"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              className="flex flex-col items-center gap-3"
            >
              <div
                className={cn(
                  "rounded-xl p-3 transition-all duration-300",
                  "bg-primary/10 text-primary",
                  isDragActive && "bg-primary/20 scale-110"
                )}
              >
                <Upload className="h-6 w-6" />
              </div>
              <div className="text-center">
                <p className="text-sm font-medium text-foreground/90">
                  {isDragActive ? "Drop your ZIP file here" : "Drag & drop your project ZIP"}
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  or click to browse · Max 500MB
                </p>
              </div>
            </motion.div>
          ) : (
            <motion.div
              key="file-info"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              className="flex items-center gap-3 w-full"
            >
              <div
                className={cn(
                  "rounded-lg p-2",
                  isError ? "bg-destructive/10 text-destructive" : "bg-chart-2/10 text-chart-2"
                )}
              >
                <FileArchive className="h-5 w-5" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-foreground/90 truncate">
                  {file.name}
                </p>
                <p className="text-xs text-muted-foreground">
                  {formatSize(file.size)}
                  {isAnalyzing && " · Analyzing project..."}
                  {deploymentStatus === "running"
  ? "Running"
  : deploymentStatus}
                  {isError && " · Upload failed"}
                </p>
              </div>
              {isProcessing && (
                <Loader2 className="h-5 w-5 text-primary shrink-0 animate-spin" />
              )}
              {isReady && (
                <CheckCircle2 className="h-5 w-5 text-chart-2 shrink-0" />
              )}
              {isError && (
                <AlertCircle className="h-5 w-5 text-destructive shrink-0" />
              )}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Upload progress bar */}
        {isUploading && (
          <div className="w-full mt-2">
            <div className="h-1.5 w-full bg-primary/10 rounded-full overflow-hidden">
              <motion.div
                className="h-full bg-gradient-to-r from-primary to-chart-2 rounded-full"
                initial={{ width: 0 }}
                animate={{ width: `${uploadProgress}%` }}
                transition={{ duration: 0.2 }}
              />
            </div>
            <p className="text-xs text-muted-foreground mt-1.5 text-center">
              Uploading... {Math.round(uploadProgress)}%
            </p>
          </div>
        )}

        {/* Analyzing shimmer */}
        {isAnalyzing && (
          <div className="w-full mt-2">
            <div className="h-1.5 w-full bg-primary/10 rounded-full overflow-hidden">
              <motion.div
                className="h-full bg-gradient-to-r from-primary via-chart-4 to-chart-2 rounded-full"
                initial={{ width: "30%" }}
                animate={{ width: ["30%", "70%", "40%", "80%", "50%"] }}
                transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
              />
            </div>
            <p className="text-xs text-muted-foreground mt-1.5 text-center">
              Scanning project structure...
            </p>
          </div>
        )}
      </div>

      {/* Error message */}
      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="flex items-center gap-2 text-destructive text-xs px-1"
          >
            <AlertCircle className="h-3.5 w-3.5 shrink-0" />
            <span>{error}</span>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Action buttons */}
      {(isReady || isError) && (
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
              onClick={(e) => {
                e.stopPropagation()
                reset()
              }}
              id="retry-upload-button"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Try Again
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={(e) => {
              e.stopPropagation()
              reset()
            }}
            id="remove-file-button"
          >
            <X className="h-3.5 w-3.5" />
            {isError ? "Clear" : "Remove"}
          </Button>
        </motion.div>
      )}

      {isReady && (
  <motion.div
    initial={{ opacity: 0, y: 10 }}
    animate={{ opacity: 1, y: 0 }}
    className="rounded-xl border border-chart-2/20 bg-chart-2/5 p-4"
  >
    <div className="flex items-center justify-between gap-3">
      <div>
        <p className="text-sm font-semibold text-chart-2">
          Deployment Running
        </p>

        <p className="text-xs text-muted-foreground mt-1">
          Your application is live and accessible
        </p>
      </div>

      <Button
        size="sm"
        className="bg-chart-2 hover:bg-chart-2/90 text-black"
        onClick={() => {
          window.open(
            deploymentUrl!,
            "_blank"
          )
        }}
      >
        Open App
      </Button>
    </div>

    <div className="mt-3 rounded-lg bg-black/40 px-3 py-2 font-mono text-xs text-chart-2">
      {deploymentUrl}
    </div>
  </motion.div>
)}

{deploymentId != null && (
  <DeploymentLogs
    deploymentId={deploymentId}
  />
)}

    </div>
  )
}
