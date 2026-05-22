"use client"

import { useEffect, useState } from "react"

import {
  ExternalLink,
} from "lucide-react"

interface Deployment {

  deployment_id: string

  project_name?: string

  status?: string

  frontend_url?: string

  backend_url?: string

  created_at?: string

}

export function DeploymentHistory() {

  const [
    deployments,
    setDeployments,
  ] = useState<Deployment[]>([])

  const fetchDeployments =
    async () => {

      try {

        const response =
          await fetch(
            "http://localhost:8000/api/deployments"
          )

        const data =
          await response.json()

        setDeployments(data)

      } catch (err) {

        console.error(
          "DEPLOYMENT FETCH ERROR:",
          err
        )

      }

    }

  useEffect(() => {

    fetchDeployments()

    const interval =
      setInterval(
        fetchDeployments,
        5000
      )

    return () =>
      clearInterval(interval)

  }, [])

  return (

    <div
      className="
        rounded-2xl
        border
        border-border
        bg-card/40
        backdrop-blur-xl
        p-5
      "
    >

      <div
        className="
          mb-4
          flex
          items-center
          justify-between
        "
      >

        <div>

          <h2
            className="
              text-lg
              font-semibold
            "
          >
            Deployments
          </h2>

          <p
            className="
              text-xs
              text-muted-foreground
              mt-1
            "
          >
            Persistent deployment history
          </p>

        </div>

      </div>

      <div className="space-y-3">

        {
          deployments.length === 0 && (

            <div
              className="
                rounded-xl
                border
                border-border
                bg-background/40
                p-4
                text-sm
                text-muted-foreground
              "
            >

              No deployments found

            </div>

          )
        }

        {
          deployments.map(
            (
              deployment,
              index
            ) => (

              <div
                key={
                  `${deployment.deployment_id}-${index}`
                }
                className="
                  rounded-xl
                  border
                  border-border
                  bg-background/40
                  p-4
                "
              >

                <div
                  className="
                    flex
                    items-start
                    justify-between
                    gap-4
                  "
                >

                  <div>

                    <div
                      className="
                        flex
                        items-center
                        gap-2
                      "
                    >

                      <div
                        className={`
                          h-2
                          w-2
                          rounded-full
                          ${
                            deployment.status ===
                            "running"
                              ? "bg-green-400"
                              : "bg-yellow-400"
                          }
                        `}
                      />

                      <p className="font-medium">

                        {
                          deployment.project_name ||
                          deployment.deployment_id
                        }

                      </p>

                    </div>

                    <div
                      className="
                        mt-2
                        flex
                        flex-wrap
                        items-center
                        gap-2
                        text-xs
                        text-muted-foreground
                      "
                    >

                      <span>
                        {deployment.status}
                      </span>

                      {
                        deployment.created_at && (
                          <>
                            <span>•</span>

                            <span>

                              {
                                new Date(
                                  deployment.created_at
                                ).toLocaleString()
                              }

                            </span>
                          </>
                        )
                      }

                    </div>

                    {
                      deployment.backend_url && (

                        <div
                          className="
                            mt-2
                            text-xs
                            text-muted-foreground
                          "
                        >

                          Backend:
                          {" "}
                          {
                            deployment.backend_url
                          }

                        </div>

                      )
                    }

                  </div>

                  {
                    deployment.frontend_url && (

                      <button
                        onClick={() =>
                          window.open(
                            deployment.frontend_url,
                            "_blank"
                          )
                        }
                        className="
                          rounded-lg
                          border
                          border-border
                          bg-background
                          px-3
                          py-2
                          text-xs
                          hover:bg-accent
                          transition
                        "
                      >

                        <div
                          className="
                            flex
                            items-center
                            gap-2
                          "
                        >

                          <ExternalLink
                            className="
                              h-3
                              w-3
                            "
                          />

                          Open

                        </div>

                      </button>

                    )
                  }

                </div>

              </div>

            )
          )
        }

      </div>

    </div>

  )

}