"use client"

import React from "react"
import {
  Rocket,
  Upload,
  Search,
  Settings2,
  KeyRound,
  Terminal,
  Shield,
  Activity,
  Zap,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import {
  DeploymentHistory,
} from "@/components/deployment/DeploymentHistory"
import { Separator } from "@/components/ui/separator"
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible"
import { UploadZone } from "@/components/deployment/UploadZone"
import { ProjectAnalysis } from "@/components/deployment/ProjectAnalysis"
import { EnvVariables } from "@/components/deployment/EnvVariables"
import { DeploymentConfig } from "@/components/deployment/DeploymentConfig"
import { DeploymentLogs } from "@/components/deployment/DeploymentLogs"
import { LivePreview } from "@/components/preview/LivePreview"
import { DeploymentProvider } from "@/lib/deployment-context"

function SectionCard({
  icon,
  title,
  children,
  defaultOpen = true,
  id,
}: {
  icon: React.ReactNode
  title: string
  children: React.ReactNode
  defaultOpen?: boolean
  id: string
}) {
  return (
    <Collapsible defaultOpen={defaultOpen}>
      <div className="glass-card rounded-xl overflow-hidden" id={id}>
        <CollapsibleTrigger className="px-4 py-3 hover:bg-accent/5 transition-colors">
          <div className="flex items-center gap-2.5">
            <span className="text-primary/70">{icon}</span>
            <span className="text-sm font-semibold text-foreground/90">{title}</span>
          </div>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <Separator className="opacity-30" />
          <div className="p-4">{children}</div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  )
}

export default function DashboardPage() {
  return (
    <DeploymentProvider>
      <div className="h-screen flex flex-col overflow-hidden">
        {/* Top bar */}
        <header className="h-12 border-b border-border/30 bg-background/80 backdrop-blur-xl flex items-center justify-between px-4 shrink-0 z-50">
          <div className="flex items-center gap-3">
            {/* Logo */}
            <div className="flex items-center gap-2">
              <div className="relative">
                <div className="h-7 w-7 rounded-lg bg-gradient-to-br from-primary via-chart-4 to-chart-2 flex items-center justify-center glow-primary">
                  <Rocket className="h-3.5 w-3.5 text-white" />
                </div>
              </div>
              <div className="flex flex-col">
                <span className="text-sm font-bold tracking-tight bg-gradient-to-r from-foreground to-foreground/70 bg-clip-text text-transparent leading-none">
                  Anti Gravity
                </span>
                <span className="text-[9px] uppercase tracking-[0.2em] text-muted-foreground/60 font-medium leading-none mt-0.5">
                  Deployments
                </span>
              </div>
            </div>

            <Separator orientation="vertical" className="h-5 opacity-20" />

            <span className="text-xs text-muted-foreground/60 font-medium hidden sm:block">
              Internal Deployment Platform
            </span>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5 text-xs">
              <Activity className="h-3 w-3 text-chart-2" />
              <span className="text-muted-foreground/60 hidden sm:block">System</span>
              <Badge
                variant="outline"
                className="text-[10px] h-5 px-1.5 gap-1 border-chart-2/30 text-chart-2"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-chart-2 status-pulse" />
                Operational
              </Badge>
            </div>
            <Separator orientation="vertical" className="h-5 opacity-20" />
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground/50">
              <Shield className="h-3 w-3" />
              <span className="hidden sm:block">Admin</span>
            </div>
          </div>
        </header>

        {/* Main content — split screen */}
        <div className="flex-1 flex overflow-hidden">
          {/* LEFT PANEL — Deployment Control Center */}
          <div className="w-full lg:w-[480px] xl:w-[520px] 2xl:w-[560px] border-r border-border/20 bg-background/50 flex flex-col overflow-hidden shrink-0">
            {/* Panel header */}
            <div className="px-4 py-3 border-b border-border/20 bg-background/30 shrink-0">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Zap className="h-3.5 w-3.5 text-primary/70" />
                  <h1 className="text-sm font-bold text-foreground/90">Deployment Control Center</h1>
                </div>
                <Badge
                  variant="secondary"
                  className="text-[10px] font-mono gap-1 bg-chart-2/10 text-chart-2 border-chart-2/20"
                >
                  <span className="h-1.5 w-1.5 rounded-full bg-chart-2 status-pulse" />
                  Ready
                </Badge>
              </div>
            </div>

            {/* Scrollable sections */}
            <div className="flex-1 overflow-y-auto p-3 space-y-3 scroll-smooth">
              {/* Upload ZIP */}
              <SectionCard
                icon={<Upload className="h-3.5 w-3.5" />}
                title="Upload Project"
                id="section-upload"
              >
                <UploadZone />
             
              </SectionCard>

              {/* Project Analysis */}
              <SectionCard
                icon={<Search className="h-3.5 w-3.5" />}
                title="Project Analysis"
                id="section-analysis"
              >
                <ProjectAnalysis />
              </SectionCard>

              {/* Environment Variables */}
              <SectionCard
                icon={<KeyRound className="h-3.5 w-3.5" />}
                title="Environment Variables"
                id="section-env-vars"
              >
                <EnvVariables />
              </SectionCard>

              {/* Deployment Configuration */}
              <SectionCard
                icon={<Settings2 className="h-3.5 w-3.5" />}
                title="Deployment Configuration"
                id="section-config"
              >
                <DeploymentConfig />
              </SectionCard>

              {/* Deployment Logs */}
              <SectionCard
                icon={<Terminal className="h-3.5 w-3.5" />}
                title="Deployment Logs"
                id="section-logs"
                defaultOpen={true}
              >
                <DeploymentLogs />
              </SectionCard>
              <DeploymentHistory />
            </div>
          </div>

          {/* RIGHT PANEL — Live Preview */}
          <div className="hidden lg:flex flex-1 flex-col bg-background/30 overflow-hidden">
            <LivePreview />
          </div>
        </div>
      </div>
    </DeploymentProvider>
  )
}
