"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2, Save } from "lucide-react"
import { useEffect } from "react"
import { useForm, useWatch } from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"

import { PageHeader } from "@/components/shared/page-header"
import { ErrorState, LoadingBlock } from "@/components/shared/states"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { apiGet, apiSend, errorMessage } from "@/lib/api"

interface SettingsResponse {
  company: {
    policy: Record<string, unknown> & { max_discount_without_approval_pct: string; max_discount_manager_pct: string; refund_approval_threshold: string; high_value_deal_threshold: string; min_confidence_for_auto: number; auto_send_email: boolean }
    risk_thresholds: { critical: number; high: number; medium: number }
    roi: { minutes_saved_per_deal_review: number; minutes_saved_per_draft: number; minutes_saved_per_followup_created: number; assumed_recovery_rate: number }
    [key: string]: unknown
  }
  llm: Record<string, unknown>
  rag: Record<string, unknown>
}

const num = z.coerce.number()
const schema = z
  .object({
    max_discount_without_approval_pct: num.min(0).max(100),
    max_discount_manager_pct: num.min(0).max(100),
    refund_approval_threshold: num.min(0),
    high_value_deal_threshold: num.min(0),
    min_confidence_for_auto: num.min(0).max(1),
    auto_send_email: z.boolean(),
    critical: num.int().min(1).max(100),
    high: num.int().min(1).max(100),
    medium: num.int().min(1).max(100),
    minutes_saved_per_deal_review: num.min(0).max(600),
    minutes_saved_per_draft: num.min(0).max(600),
    minutes_saved_per_followup_created: num.min(0).max(600),
    assumed_recovery_rate: num.min(0).max(1),
  })
  .refine((v) => v.critical > v.high && v.high > v.medium, { message: "Thresholds must satisfy critical > high > medium", path: ["critical"] })
  .refine((v) => v.max_discount_manager_pct >= v.max_discount_without_approval_pct, { message: "Manager limit must be ≥ rep limit", path: ["max_discount_manager_pct"] })
type Values = z.input<typeof schema>

function NumField({ id, label, hint, form, step = "any" }: { id: keyof Values; label: string; hint?: string; form: ReturnType<typeof useForm<Values>>; step?: string }) {
  const err = form.formState.errors[id]
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} type="number" step={step} {...form.register(id)} />
      {err ? <p className="text-xs text-destructive">{String(err.message)}</p> : hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  )
}

export default function SettingsPage() {
  const qc = useQueryClient()
  const { data, error, isLoading } = useQuery({ queryKey: ["settings"], queryFn: () => apiGet<SettingsResponse>("/settings") })
  const form = useForm<Values>({ resolver: zodResolver(schema) })
  const autoSend = useWatch({ control: form.control, name: "auto_send_email" })
  useEffect(() => {
    if (!data) return
    const { policy, risk_thresholds: t, roi } = data.company
    form.reset({
      max_discount_without_approval_pct: Number(policy.max_discount_without_approval_pct),
      max_discount_manager_pct: Number(policy.max_discount_manager_pct),
      refund_approval_threshold: Number(policy.refund_approval_threshold),
      high_value_deal_threshold: Number(policy.high_value_deal_threshold),
      min_confidence_for_auto: policy.min_confidence_for_auto,
      auto_send_email: policy.auto_send_email,
      ...t,
      ...roi,
    })
  }, [data, form])
  const save = useMutation({
    mutationFn: (v: z.output<typeof schema>) => {
      const c = data!.company
      return apiSend("PUT", "/settings", {
        ...c,
        policy: {
          ...c.policy,
          max_discount_without_approval_pct: String(v.max_discount_without_approval_pct),
          max_discount_manager_pct: String(v.max_discount_manager_pct),
          refund_approval_threshold: String(v.refund_approval_threshold),
          high_value_deal_threshold: String(v.high_value_deal_threshold),
          min_confidence_for_auto: v.min_confidence_for_auto,
          auto_send_email: v.auto_send_email,
        },
        risk_thresholds: { critical: v.critical, high: v.high, medium: v.medium },
        roi: {
          minutes_saved_per_deal_review: v.minutes_saved_per_deal_review,
          minutes_saved_per_draft: v.minutes_saved_per_draft,
          minutes_saved_per_followup_created: v.minutes_saved_per_followup_created,
          assumed_recovery_rate: v.assumed_recovery_rate,
        },
      })
    },
    onSuccess: () => {
      toast.success("Settings saved", { description: "New thresholds apply to the next risk recompute and agent run. Change recorded in the audit log." })
      qc.invalidateQueries()
    },
    onError: (e) => toast.error("Not saved", { description: errorMessage(e) }),
  })
  if (isLoading) return <LoadingBlock rows={8} />
  if (error) return <ErrorState error={error} />

  return (
    <form onSubmit={form.handleSubmit((v) => save.mutate(v as z.output<typeof schema>))}>
      <PageHeader
        title="Settings"
        description="Business thresholds used by the deterministic policy and risk engines. Changes are validated server-side and audited."
        actions={
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? <Loader2 className="animate-spin" /> : <Save />} Save changes
          </Button>
        }
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Approval policy</CardTitle>
            <CardDescription>What the AI may do automatically vs. what needs a human</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <NumField id="max_discount_without_approval_pct" label="Max discount without approval (%)" form={form} />
            <NumField id="max_discount_manager_pct" label="Max discount a manager can approve (%)" hint="Above this needs the owner" form={form} />
            <NumField id="refund_approval_threshold" label="Refund threshold needing owner (₹)" form={form} />
            <NumField id="high_value_deal_threshold" label="High-value deal threshold (₹)" hint="Customer-facing actions above this need a manager" form={form} />
            <NumField id="min_confidence_for_auto" label="Min AI confidence for automation (0–1)" step="0.05" form={form} />
            <div className="flex items-center justify-between rounded-lg border p-3">
              <div>
                <Label htmlFor="auto_send_email">Auto-send low-risk emails</Label>
                <p className="text-xs text-muted-foreground">Off by default: emails are drafted, then approved</p>
              </div>
              <Switch id="auto_send_email" checked={autoSend ?? false} onCheckedChange={(v) => form.setValue("auto_send_email", v, { shouldDirty: true })} />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Risk levels</CardTitle>
            <CardDescription>Score cut-offs for the deterministic Revenue Risk Engine (0–100)</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-3">
            <NumField id="critical" label="Critical ≥" form={form} step="1" />
            <NumField id="high" label="High ≥" form={form} step="1" />
            <NumField id="medium" label="Medium ≥" form={form} step="1" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>ROI assumptions</CardTitle>
            <CardDescription>Used only for figures labelled “Estimated”</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <NumField id="minutes_saved_per_deal_review" label="Minutes saved per deal review" form={form} />
            <NumField id="minutes_saved_per_draft" label="Minutes saved per drafted message" form={form} />
            <NumField id="minutes_saved_per_followup_created" label="Minutes saved per follow-up created" form={form} />
            <NumField id="assumed_recovery_rate" label="Assumed recovery rate (0–1)" step="0.01" form={form} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>AI configuration</CardTitle>
            <CardDescription>Read-only — set via environment variables. Secrets are never shown.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            {[...Object.entries(data?.llm ?? {}), ...Object.entries(data?.rag ?? {})].map(([k, v]) => (
              <p key={k} className="flex justify-between gap-3 border-b py-1 last:border-0">
                <span className="text-muted-foreground">{k}</span>
                <span className="truncate font-mono text-xs">{v === null ? "—" : Array.isArray(v) ? v.join(" / ") : String(v)}</span>
              </p>
            ))}
          </CardContent>
        </Card>
      </div>
    </form>
  )
}
