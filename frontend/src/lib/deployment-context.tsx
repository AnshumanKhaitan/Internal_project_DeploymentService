"use client"

/**
 * Anti Gravity Deployments - Deployment Context
 *
 * Shared state for the deployment pipeline.
 * Manages upload → analysis → config → deploy flow.
 */

import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useRef,
  ReactNode,
} from "react"

import {
  uploadProject,
  type ProjectAnalysis,
  type UploadResponse,
} from "@/lib/api"

// ─── Types ───────────────────────────────────────────────────────────────────

export type PipelineStage =
  | "idle"
  | "uploading"
  | "analyzing"
  | "building"
  | "starting"
  | "running"
  | "degraded"
  | "error"

export interface EnvVar {
  id: string
  key: string
  value: string
  isSecret: boolean
}

interface DeploymentContextType {
  // Pipeline state
  stage: PipelineStage
  error: string | null

  // Upload state
  frontendFile: File | null
  backendFile: File | null
  uploadProgress: number

  // Analysis results
  deploymentId: string | null
  analysis: ProjectAnalysis | null

  // URLs — always defined (may be null)
  deploymentUrl: string | null      // frontend proxy URL (via backend /api/preview)
  frontendUrl: string | null        // raw frontend container URL
  backendUrl: string | null         // raw backend container URL
  deploymentStatus: string

  // Environment variables
  envVars: EnvVar[]
  setEnvVars: React.Dispatch<React.SetStateAction<EnvVar[]>>

  // Actions
  startUpload: (frontendFile: File, backendFile?: File) => Promise<void>
  reset: () => void
}

// ─── Context ─────────────────────────────────────────────────────────────────

const DeploymentContext = createContext<DeploymentContextType | null>(null)

export function useDeployment() {
  const ctx = useContext(DeploymentContext)
  if (!ctx) {
    throw new Error("useDeployment must be used within DeploymentProvider")
  }
  return ctx
}

// ─── Provider ────────────────────────────────────────────────────────────────

export function DeploymentProvider({ children }: { children: ReactNode }) {
  const [stage, setStage] = useState<PipelineStage>("idle")
  const [error, setError] = useState<string | null>(null)

  const [frontendFile, setFrontendFile] = useState<File | null>(null)
  const [backendFile, setBackendFile] = useState<File | null>(null)
  const [uploadProgress, setUploadProgress] = useState(0)

  const [deploymentId, setDeploymentId] = useState<string | null>(null)
  const [analysis, setAnalysis] = useState<ProjectAnalysis | null>(null)

  // Three distinct URL states
  const [deploymentUrl, setDeploymentUrl] = useState<string | null>(null)
  const [frontendUrl, setFrontendUrl] = useState<string | null>(null)
  const [backendUrl, setBackendUrl] = useState<string | null>(null)
  const [deploymentStatus, setDeploymentStatus] = useState<string>("idle")

  const [envVars, setEnvVars] = useState<EnvVar[]>([])

  // Prevents a late XHR progress callback from downgrading stage after deploy completes
  const uploadFinishedRef = useRef(false)

  // ─────────────────────────────────────────────
  // Upload Flow
  // ─────────────────────────────────────────────

  const startUpload = useCallback(
    async (selectedFrontendFile: File, selectedBackendFile?: File) => {

      uploadFinishedRef.current = false

      // Reset identity; keep preview URL until the new deploy returns (avoids blank iframe + overlay races)
      setError(null)
      setDeploymentId(null)
      setBackendUrl(null)
      setDeploymentStatus("idle")
      setAnalysis(null)
      setFrontendFile(selectedFrontendFile)
      setBackendFile(selectedBackendFile || null)
      setUploadProgress(0)
      setStage("uploading")

      try {
        const response: UploadResponse = await uploadProject(
          selectedFrontendFile,
          selectedBackendFile,
          (progress) => {
            if (uploadFinishedRef.current) return
            setUploadProgress(progress)
            if (progress >= 100) {
              setStage("analyzing")
            }
          }
        )

        uploadFinishedRef.current = true

        // ── Set deployment identity ──────────────────────────────────────
        const depId = response.deployment_id
        setDeploymentId(depId)
        setAnalysis(response.analysis)

        // ── Set URLs from response ───────────────────────────────────────
        // preview_url/frontend_url → use backend proxy for iframe embedding
        const rawFrontend = response.frontend_url || response.preview_url
        const rawBackend = response.backend_url

        if (rawFrontend) {
          // Direct container URL — Next.js apps do not hydrate reliably via /api/preview proxy
          setDeploymentUrl(rawFrontend)
          setFrontendUrl(rawFrontend)
        } else {
          setDeploymentUrl(null)
          setFrontendUrl(null)
        }

        if (rawBackend) {
          setBackendUrl(rawBackend)
        }

        // ── Determine stage ──────────────────────────────────────────────
        const status = response.status
        if (status === "running" || status === "degraded") {
          setDeploymentStatus(status)
          // degraded = partial success (e.g. only backend deployed)
          setStage(rawFrontend ? "running" : "degraded")
        } else if (status === "failed") {
          setDeploymentStatus("failed")
          setError(response.message || "Deployment failed")
          setStage("error")
        } else {
          // Fallback: if we got a deployment_id and any URL, consider running
          if (depId && (rawFrontend || rawBackend)) {
            setDeploymentStatus("running")
            setStage("running")
          } else {
            setDeploymentStatus("failed")
            setError("No deployment URLs returned from server")
            setStage("error")
          }
        }

        // ── Populate detected env vars ───────────────────────────────────
        if (response.analysis?.env_template_keys?.length) {
          const detected: EnvVar[] = response.analysis.env_template_keys.map(
            (key, idx) => ({
              id: `env-${Date.now()}-${idx}`,
              key,
              value: "",
              isSecret:
                key.includes("SECRET") ||
                key.includes("KEY") ||
                key.includes("PASSWORD") ||
                key.includes("TOKEN"),
            })
          )
          setEnvVars(detected)
        } else {
          setEnvVars([])
        }

      } catch (err: unknown) {
        uploadFinishedRef.current = true
        const message = err instanceof Error ? err.message : "Upload failed"
        console.error("[Deployment] Upload error:", message)
        setError(message)
        setDeploymentStatus("failed")
        setDeploymentUrl(null)
        setFrontendUrl(null)
        setStage("error")
      }
    },
    []
  )

  // ─────────────────────────────────────────────
  // Reset State
  // ─────────────────────────────────────────────

  const reset = useCallback(() => {
    setStage("idle")
    setError(null)
    setFrontendFile(null)
    setBackendFile(null)
    setUploadProgress(0)
    setDeploymentId(null)
    setDeploymentUrl(null)
    setFrontendUrl(null)
    setBackendUrl(null)
    setDeploymentStatus("idle")
    setAnalysis(null)
    setEnvVars([])
  }, [])

  // ─────────────────────────────────────────────
  // Provider
  // ─────────────────────────────────────────────

  return (
    <DeploymentContext.Provider
      value={{
        stage,
        error,
        frontendFile,
        backendFile,
        uploadProgress,
        deploymentId,
        analysis,
        deploymentUrl,
        frontendUrl,
        backendUrl,
        deploymentStatus,
        envVars,
        setEnvVars,
        startUpload,
        reset,
      }}
    >
      {children}
    </DeploymentContext.Provider>
  )
}