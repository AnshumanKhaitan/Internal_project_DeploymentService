"use client"

/**
 * Anti Gravity Deployments - Deployment Context
 *
 * Shared state for the deployment pipeline.
 * Manages upload → analysis → config → deploy flow.
 */

import React, { createContext, useContext, useState, useCallback, ReactNode } from "react"
import { uploadProject, type ProjectAnalysis, type UploadResponse } from "@/lib/api"

// ─── Types ───────────────────────────────────────────────────────────────────

export type PipelineStage =
  | "idle"
  | "uploading"
  | "analyzing"
  | "building"
  | "starting"
  | "running"
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
  file: File | null
  uploadProgress: number

  // Analysis results
  deploymentId: string | null
  analysis: ProjectAnalysis | null
  deploymentUrl: string | null
  deploymentStatus: string

  // Environment variables
  envVars: EnvVar[]
  setEnvVars: React.Dispatch<React.SetStateAction<EnvVar[]>>

  // Actions
  startUpload: (file: File) => Promise<void>
  reset: () => void
}

// ─── Context ─────────────────────────────────────────────────────────────────

const DeploymentContext = createContext<DeploymentContextType | null>(null)

export function useDeployment() {
  const ctx = useContext(DeploymentContext)
  if (!ctx) throw new Error("useDeployment must be used within DeploymentProvider")
  return ctx
}

// ─── Provider ────────────────────────────────────────────────────────────────

export function DeploymentProvider({ children }: { children: ReactNode }) {
  const [stage, setStage] = useState<PipelineStage>("idle")
  const [error, setError] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [deploymentId, setDeploymentId] = useState<string | null>(null)
  const [deploymentUrl, setDeploymentUrl] =
  useState<string | null>(null)
  const [deploymentStatus, setDeploymentStatus] =
  useState<string>("idle")
  const [analysis, setAnalysis] = useState<ProjectAnalysis | null>(null)
  const [envVars, setEnvVars] = useState<EnvVar[]>([])

  const startUpload = useCallback(async (selectedFile: File) => {
    setFile(selectedFile)
    setError(null)
    setUploadProgress(0)
   

    try {
      const response: UploadResponse = await uploadProject(
        selectedFile,
        (progress) => {
          setUploadProgress(progress)
          // When upload reaches 100%, transition to analyzing
          if (progress >= 100) {
            setStage("analyzing")
          }
        }
      )

      // Upload + analysis complete
      setDeploymentId(response.deployment_id)
      setAnalysis(response.analysis)
      setDeploymentUrl(
  response.deployment_url
)

setStage("running")

      // Auto-generate env vars from detected template keys
      if (response.analysis?.env_template_keys?.length) {
        const detected: EnvVar[] = response.analysis.env_template_keys.map(
          (key, idx) => ({
            id: `env-${Date.now()}-${idx}`,
            key,
            value: "",
            isSecret: key.includes("SECRET") || key.includes("KEY") || key.includes("PASSWORD") || key.includes("TOKEN"),
          })
        )
        setEnvVars(detected)
      } else {
        setEnvVars([])
      }

    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Upload failed"
      setError(message)
      setStage("error")
    }
  }, [])

  const reset = useCallback(() => {
    setStage("idle")
    setError(null)
    setFile(null)
    setUploadProgress(0)
    setDeploymentId(null)
    setAnalysis(null)
    setEnvVars([])
  }, [])

  return (
    <DeploymentContext.Provider
      value={{
  stage,
  error,
  file,
  uploadProgress,
  deploymentId,
  deploymentUrl,
  deploymentStatus,
  analysis,
  envVars,
  startUpload,
  reset,
}}
    >
      {children}
    </DeploymentContext.Provider>
  )
}
