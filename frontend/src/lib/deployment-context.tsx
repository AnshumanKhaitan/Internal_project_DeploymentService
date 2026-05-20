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
  setEnvVars: React.Dispatch<
    React.SetStateAction<EnvVar[]>
  >

  // Actions
  startUpload: (file: File) => Promise<void>
  reset: () => void
}

// ─── Context ─────────────────────────────────────────────────────────────────

const DeploymentContext =
  createContext<DeploymentContextType | null>(
    null
  )

export function useDeployment() {

  const ctx = useContext(
    DeploymentContext
  )

  if (!ctx) {

    throw new Error(
      "useDeployment must be used within DeploymentProvider"
    )
  }

  return ctx
}

// ─── Provider ────────────────────────────────────────────────────────────────

export function DeploymentProvider({
  children,
}: {
  children: ReactNode
}) {

  const [stage, setStage] =
    useState<PipelineStage>("idle")

  const [error, setError] =
    useState<string | null>(null)

  const [file, setFile] =
    useState<File | null>(null)

  const [uploadProgress, setUploadProgress] =
    useState(0)

  const [deploymentId, setDeploymentId] =
    useState<string | null>(null)

  const [deploymentUrl, setDeploymentUrl] =
    useState<string | null>(null)

  const [deploymentStatus, setDeploymentStatus] =
    useState<string>("idle")

  const [analysis, setAnalysis] =
    useState<ProjectAnalysis | null>(null)

  const [envVars, setEnvVars] =
    useState<EnvVar[]>([])

  // ─────────────────────────────────────────────
  // Upload Flow
  // ─────────────────────────────────────────────

  const startUpload = useCallback(
    async (selectedFile: File) => {

      console.log(
        "STARTING UPLOAD:",
        selectedFile.name
      )

      // Reset previous deployment state
      setError(null)
      setDeploymentId(null)
      setDeploymentUrl(null)
      setDeploymentStatus("idle")
      setAnalysis(null)

      setFile(selectedFile)
      setUploadProgress(0)
      setStage("uploading")

      try {

        const response: UploadResponse =
          await uploadProject(
            selectedFile,
            (progress) => {

              setUploadProgress(progress)

              if (progress >= 100) {

                setStage("analyzing")
              }
            }
          )

        console.log(
          "FULL RESPONSE:",
          response
        )

        // ─────────────────────────────────────────
        // Deployment Results
        // ─────────────────────────────────────────

        setDeploymentId(
          response.deployment_id
        )

        setAnalysis(
          response.analysis
        )

        // IMPORTANT FIX
        if (response.preview_url) {

          console.log(
            "SETTING PREVIEW URL:",
            response.preview_url
          )

          setDeploymentUrl(
            response.preview_url
          )

          setDeploymentStatus(
            "running"
          )

          setStage("running")

        } else {

          console.error(
            "preview_url missing from response"
          )

          setDeploymentStatus(
            "failed"
          )

          setStage("error")
        }

        // ─────────────────────────────────────────
        // Environment Variables
        // ─────────────────────────────────────────

        if (
          response.analysis
            ?.env_template_keys
            ?.length
        ) {

          const detected: EnvVar[] =
            response.analysis.env_template_keys.map(
              (
                key,
                idx
              ) => ({
                id:
                  `env-${Date.now()}-${idx}`,

                key,

                value: "",

                isSecret:
                  key.includes("SECRET")
                  || key.includes("KEY")
                  || key.includes("PASSWORD")
                  || key.includes("TOKEN"),
              })
            )

          setEnvVars(detected)

        } else {

          setEnvVars([])
        }

      } catch (err: unknown) {

        console.error(
          "UPLOAD FAILED:",
          err
        )

        const message =
          err instanceof Error
            ? err.message
            : "Upload failed"

        setError(message)

        setDeploymentStatus(
          "failed"
        )

        setStage("error")
      }
    },
    []
  )

  // ─────────────────────────────────────────────
  // Reset State
  // ─────────────────────────────────────────────

  const reset = useCallback(() => {

    console.log(
      "RESETTING DEPLOYMENT STATE"
    )

    setStage("idle")
    setError(null)

    setFile(null)

    setUploadProgress(0)

    setDeploymentId(null)

    setDeploymentUrl(null)

    setDeploymentStatus("idle")

    setAnalysis(null)

    setEnvVars([])

  }, [])

  // ─────────────────────────────────────────────
  // Debug
  // ─────────────────────────────────────────────

  console.log(
    "deploymentUrl:",
    deploymentUrl
  )

  // ─────────────────────────────────────────────
  // Provider
  // ─────────────────────────────────────────────

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
        setEnvVars,

        startUpload,
        reset,
      }}
    >
      {children}
    </DeploymentContext.Provider>
  )
}