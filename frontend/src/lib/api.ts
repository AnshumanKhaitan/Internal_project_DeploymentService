/**
 * Anti Gravity Deployments - API Client
 *
 * Handles communication with the FastAPI backend for
 * project upload, analysis, and deployment management.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ─── Types ───────────────────────────────────────────────────────────────────

export interface DependencyInfo {
  name: string;
  version: string;
  is_dev: boolean;
}

export interface ScriptInfo {
  name: string;
  command: string;
}

export interface ProjectAnalysis {
  runtime: string;
  runtime_version: string | null;
  framework: string;
  framework_version: string | null;
  detected_port: number;
  has_dockerfile: boolean;
  has_docker_compose: boolean;
  entry_point: string | null;
  startup_command: string | null;
  dependencies: DependencyInfo[];
  dependencies_count: number;
  scripts: ScriptInfo[];
  env_template_keys: string[];
  env_template_file: string | null;
  project_root: string | null;
  file_count: number;
  total_size_bytes: number;
}

export interface UploadResponse {
  deployment_id: string;
  status: string;
  message: string;
  analysis: ProjectAnalysis | null;
  preview_url: string | null;
  services?: {
    runtime: string;
    working_directory: string;
    url: string;
  }[];
}

export interface DeploymentState {
  id: string;
  status: string;
  project_name: string | null;
  analysis: ProjectAnalysis | null;
  created_at: string;
  updated_at: string;
  logs: string[];
  error: string | null;
  url: string | null;
}

export interface HealthResponse {
  status: string;
  version: string;
  service: string;
  timestamp: string;
}

// ─── API Functions ───────────────────────────────────────────────────────────

/**
 * Upload a project ZIP file with progress tracking.
 */
export async function uploadProject(
 frontendFile: File,
backendFile?: File,
  onProgress?: (progress: number) => void
): Promise<UploadResponse> {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    formData.append(
  "frontend_file",
  frontendFile
)

if (backendFile) {

  formData.append(
    "backend_file",
    backendFile
  )
}

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/api/upload`);

    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable && onProgress) {
        const percent = (e.loaded / e.total) * 100;
        onProgress(percent);
      }
    });

    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const data = JSON.parse(xhr.responseText);
          resolve(data);
        } catch {
          reject(new Error("Invalid response from server"));
        }
      } else {
        try {
          const error = JSON.parse(xhr.responseText);
          reject(new Error(error.detail || `Upload failed (${xhr.status})`));
        } catch {
          reject(new Error(`Upload failed with status ${xhr.status}`));
        }
      }
    });

    xhr.addEventListener("error", () => {
      reject(new Error("Network error — is the backend running?"));
    });

    xhr.addEventListener("abort", () => {
      reject(new Error("Upload was cancelled"));
    });

    xhr.send(formData);
  });
}

/**
 * Check backend health.
 */
export async function checkHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/api/health`);
  if (!res.ok) throw new Error("Health check failed");
  return res.json();
}

/**
 * Get all deployments.
 */
export async function listDeployments(): Promise<DeploymentState[]> {
  const res = await fetch(`${API_BASE}/api/deployments`);
  if (!res.ok) throw new Error("Failed to list deployments");
  return res.json();
}

/**
 * Get a specific deployment by ID.
 */
export async function getDeployment(id: string): Promise<DeploymentState> {
  const res = await fetch(`${API_BASE}/api/deployments/${id}`);
  if (!res.ok) throw new Error("Deployment not found");
  return res.json();
}

/**
 * Delete a deployment.
 */
export async function deleteDeployment(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/deployments/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to delete deployment");
}

// ─── Display Helpers ─────────────────────────────────────────────────────────

const RUNTIME_LABELS: Record<string, string> = {
  nodejs: "Node.js",
  python: "Python",
  go: "Go",
  rust: "Rust",
  static: "Static",
  unknown: "Unknown",
};

const FRAMEWORK_LABELS: Record<string, string> = {
  nextjs: "Next.js",
  react: "React",
  vite: "Vite",
  vue: "Vue.js",
  angular: "Angular",
  express: "Express",
  fastapi: "FastAPI",
  flask: "Flask",
  django: "Django",
  static: "Static",
  unknown: "Unknown",
};

export function getRuntimeLabel(runtime: string): string {
  return RUNTIME_LABELS[runtime] || runtime;
}

export function getFrameworkLabel(framework: string): string {
  return FRAMEWORK_LABELS[framework] || framework;
}

export function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}
