"use client"

import React, {
  useCallback,
  useState,
} from "react"
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
    frontendFile,
backendFile,
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
  const [
  selectedFrontend,
  setSelectedFrontend,
] = useState<File | null>(null)

const [
  selectedBackend,
  setSelectedBackend,
] = useState<File | null>(null)

const onFrontendDrop = useCallback(
  (acceptedFiles: File[]) => {

    const selected =
      acceptedFiles[0]

    if (!selected) return

    if (
      !selected.name.endsWith(".zip")
    ) {
      return
    }

    setSelectedFrontend(
      selected
    )
  },
  []
)

const onBackendDrop = useCallback(
  (acceptedFiles: File[]) => {

    const selected =
      acceptedFiles[0]

    if (!selected) return

    if (
      !selected.name.endsWith(".zip")
    ) {
      return
    }

    setSelectedBackend(
      selected
    )
  },
  []
)

const frontendDropzone =
  useDropzone({
    onDrop: onFrontendDrop,
    accept: {
      "application/zip": [".zip"],
    },
    maxFiles: 1,
    multiple: false,
    disabled: isProcessing,
  })

const backendDropzone =
  useDropzone({
    onDrop: onBackendDrop,
    accept: {
      "application/zip": [".zip"],
    },
    maxFiles: 1,
    multiple: false,
    disabled: isProcessing,
  })

  const formatSize = (bytes: number) => {
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(2)} MB`
  }

 return (
  <div className="space-y-4">

    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

  {/* Frontend Upload */}
  <div
    {...frontendDropzone.getRootProps()}
    className={cn(
      "relative rounded-xl border-2 border-dashed transition-all duration-300 cursor-pointer group",
      "flex flex-col items-center justify-center gap-3 p-6 min-h-[220px]",
      frontendDropzone.isDragActive
        ? "border-primary/60 bg-primary/5"
        : "border-border/50 hover:border-primary/30 hover:bg-primary/[0.02]"
    )}
  >
    <input
      {...frontendDropzone.getInputProps()}
    />

    <div className="rounded-xl p-3 bg-primary/10 text-primary">
      <Upload className="h-6 w-6" />
    </div>

    <div className="text-center">
      <p className="text-sm font-semibold">
        Frontend ZIP
      </p>

      <p className="text-xs text-muted-foreground mt-1">
        React, Next.js, Vite, Vue
      </p>
    </div>

    {selectedFrontend && (
      <div className="w-full rounded-lg bg-chart-2/10 border border-chart-2/20 p-3">
        <p className="text-xs font-medium truncate">
          {selectedFrontend.name}
        </p>

        <p className="text-[10px] text-muted-foreground mt-1">
          {formatSize(selectedFrontend.size)}
        </p>
      </div>
    )}
  </div>

  {/* Backend Upload */}
  <div
    {...backendDropzone.getRootProps()}
    className={cn(
      "relative rounded-xl border-2 border-dashed transition-all duration-300 cursor-pointer group",
      "flex flex-col items-center justify-center gap-3 p-6 min-h-[220px]",
      backendDropzone.isDragActive
        ? "border-chart-4/60 bg-chart-4/5"
        : "border-border/50 hover:border-chart-4/30 hover:bg-chart-4/[0.02]"
    )}
  >
    <input
      {...backendDropzone.getInputProps()}
    />

    <div className="rounded-xl p-3 bg-chart-4/10 text-chart-4">
      <Upload className="h-6 w-6" />
    </div>

    <div className="text-center">
      <p className="text-sm font-semibold">
        Backend ZIP
      </p>

      <p className="text-xs text-muted-foreground mt-1">
        FastAPI, Express, Django
      </p>
    </div>

    {selectedBackend && (
      <div className="w-full rounded-lg bg-chart-4/10 border border-chart-4/20 p-3">
        <p className="text-xs font-medium truncate">
          {selectedBackend.name}
        </p>

        <p className="text-[10px] text-muted-foreground mt-1">
          {formatSize(selectedBackend.size)}
        </p>
      </div>
    )}
  </div>
</div>

<Button
  className="w-full mt-4 bg-gradient-to-r from-primary via-chart-4 to-chart-2 hover:opacity-90 text-white font-semibold h-11"
  disabled={!selectedFrontend || isProcessing}
  onClick={() => {

  if (!selectedFrontend)
    return

  startUpload(
    selectedFrontend,
    selectedBackend || undefined
  )
}}
>
  {isProcessing ? (
    <>
      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
      Deploying...
    </>
  ) : (
    <>
      <Upload className="h-4 w-4 mr-2" />
      Deploy Full Stack App
    </>
  )}
</Button>

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
