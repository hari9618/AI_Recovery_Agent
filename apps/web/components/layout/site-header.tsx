"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Database, Loader2, Moon, Sun } from "lucide-react"
import { useTheme } from "next-themes"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { AskAiButton } from "@/components/chat/chat-widget"
import { LiveDot } from "@/components/motion/primitives"
import { Separator } from "@/components/ui/separator"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { ApiError, apiGet, apiSend, errorMessage } from "@/lib/api"
import type { Me } from "@/lib/types"

interface LoadResult {
  counts: Record<string, number>
  documents_indexed: number
  risk_levels: Record<string, number>
  seconds: number
}

export function SiteHeader() {
  const qc = useQueryClient()
  const { resolvedTheme, setTheme } = useTheme()
  const me = useQuery({ queryKey: ["me"], queryFn: () => apiGet<Me>("/me"), retry: false })
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => apiGet<{ llm_configured: boolean; llm_model: string | null; langfuse_configured: boolean }>("/health"),
    staleTime: 60_000,
  })

  const load = useMutation({
    mutationFn: async () => {
      // First run: no tenant exists yet, so the demo is created via the token-guarded bootstrap endpoint.
      const status = await apiGet<{ tenant_exists: boolean }>("/demo/status")
      return apiSend<LoadResult>("POST", status.tenant_exists ? "/demo/load" : "/demo/bootstrap")
    },
    onSuccess: (r) => {
      toast.success("Synthetic demo dataset loaded", {
        description: `${r.counts.customers} customers · ${r.counts.opportunities} opportunities · ${r.documents_indexed} policy documents · ${r.seconds}s`,
      })
      qc.invalidateQueries()
    },
    onError: (e) => toast.error("Could not load demo data", { description: errorMessage(e) }),
  })

  const noTenant = me.error instanceof ApiError && me.error.status === 401

  return (
    <header className="glass sticky top-0 z-30 flex h-16 shrink-0 items-center gap-3 border-b border-border/70 px-4 md:rounded-t-2xl md:px-6">
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="mr-1 data-[orientation=vertical]:h-4" />
      <div className="flex min-w-0 shrink items-center gap-2.5">
        <span className="truncate text-sm font-semibold tracking-tight">{me.data?.company.name ?? "Revenue Recovery"}</span>
        {me.data?.company.is_demo ? (
          <Badge variant="outline" className="hidden rounded-md border-copper/30 bg-copper-soft px-2 font-mono text-[10px] font-medium tracking-[0.08em] text-bronze uppercase sm:inline-flex">
            Synthetic demo data
          </Badge>
        ) : null}
      </div>
      <div className="mx-auto min-w-0">
        <AskAiButton />
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {health.data ? (
          <Badge variant="outline" className="hidden gap-1.5 rounded-full bg-card px-2.5 py-1 font-mono text-[10px] 2xl:inline-flex">
            <LiveDot className={health.data.llm_configured ? "text-success" : "text-warning"} />
            {health.data.llm_configured ? health.data.llm_model : "LLM not configured"}
          </Badge>
        ) : null}
        <Dialog>
          <DialogTrigger asChild>
            <Button size="sm" variant={noTenant ? "default" : "outline"} disabled={load.isPending} className="rounded-lg">
              {load.isPending ? <Loader2 className="animate-spin" /> : <Database />}
              <span className="hidden xl:inline">Load demo dataset</span>
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Load the synthetic demo dataset?</DialogTitle>
              <DialogDescription>
                Replaces the demo tenant with ~340 customers, 520 leads, 270 opportunities, 210 quotations, 330 conversations
                and 9 policy documents, then runs the deterministic risk engine. All data is synthetic. AI analyses and
                recommendations are not pre-generated — they appear only when you run the agent.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <DialogClose asChild>
                <Button variant="outline">Cancel</Button>
              </DialogClose>
              <DialogClose asChild>
                <Button onClick={() => load.mutate()}>Load dataset</Button>
              </DialogClose>
            </DialogFooter>
          </DialogContent>
        </Dialog>
        <Button
          size="icon"
          variant="ghost"
          aria-label="Toggle theme"
          onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
        >
          <Sun className="hidden dark:block" />
          <Moon className="dark:hidden" />
        </Button>
        {me.data ? (
          <div className="flex items-center gap-2.5 border-l pl-3">
            <div className="flex size-8 items-center justify-center rounded-full bg-gradient-to-br from-copper to-coral text-xs font-semibold text-primary-foreground shadow-sm ring-2 ring-background">
              {me.data.name
                .split(" ")
                .map((p) => p[0])
                .join("")
                .slice(0, 2)}
            </div>
            <div className="hidden text-xs leading-tight whitespace-nowrap 2xl:block">
              <div className="font-medium">{me.data.name}</div>
              <div className="text-muted-foreground capitalize">{me.data.role.replace("_", " ")}</div>
            </div>
          </div>
        ) : null}
      </div>
    </header>
  )
}
