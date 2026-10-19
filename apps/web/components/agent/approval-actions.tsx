"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Check, Loader2, Pencil, X } from "lucide-react"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { apiSend, errorMessage } from "@/lib/api"
import type { Approval, Recommendation } from "@/lib/types"

const editSchema = z.object({
  email_subject: z.string().min(3, "Subject is too short").max(200).optional().or(z.literal("")),
  email_body: z.string().min(10, "Message is too short").max(5000).optional().or(z.literal("")),
  discount_pct: z.union([z.literal(""), z.coerce.number().gt(0, "Must be above 0").max(100, "Max 100")]).optional(),
  note: z.string().max(1000).optional(),
})
type EditValues = z.input<typeof editSchema>

interface DecisionResult {
  status: string
  execution?: { ok: boolean; results: { tool: string; ok: boolean; error?: { message?: string } | null }[] }
  verification?: { all_passed: boolean; checks: { check: string; passed: boolean }[] }
}

export function ApprovalActions({ approval, rec }: { approval: Approval; rec: Recommendation }) {
  const qc = useQueryClient()
  const [mode, setMode] = useState<null | "edit" | "reject">(null)
  const primary = rec.proposed_action.primary
  const form = useForm<EditValues>({
    resolver: zodResolver(editSchema),
    defaultValues: {
      email_subject: rec.draft_subject ?? "",
      email_body: rec.draft_body ?? "",
      discount_pct: primary?.discount_pct ?? "",
      note: "",
    },
  })

  const decide = useMutation({
    mutationFn: (body: Record<string, unknown>) => apiSend<DecisionResult>("POST", `/approvals/${approval.id}/decision`, body),
    onSuccess: (r) => {
      setMode(null)
      if (r.status === "rejected") toast.message("Recommendation rejected", { description: "Nothing was sent to the customer." })
      else if (r.execution?.ok)
        toast.success("Approved and executed", {
          description: `${r.execution.results.map((x) => x.tool).join(" → ")} · verification ${r.verification?.all_passed ? "passed" : "failed"}`,
        })
      else
        toast.warning("Approved, but execution failed", {
          description: r.execution?.results.find((x) => !x.ok)?.error?.message ?? "See the recommendation for details",
        })
      qc.invalidateQueries()
    },
    onError: (e) => toast.error("Decision not recorded", { description: errorMessage(e) }),
  })

  if (approval.status !== "pending") return null

  const submitEdit = form.handleSubmit((v) => {
    const body: Record<string, unknown> = { decision: "approve", note: v.note || undefined }
    if (v.email_subject && v.email_subject !== rec.draft_subject) body.email_subject = v.email_subject
    if (v.email_body && v.email_body !== rec.draft_body) body.email_body = v.email_body
    if (v.discount_pct !== "" && v.discount_pct !== undefined && Number(v.discount_pct) !== primary?.discount_pct)
      body.discount_pct = Number(v.discount_pct)
    decide.mutate(body)
  })

  return (
    <div className="flex flex-wrap gap-2">
      <Button onClick={() => decide.mutate({ decision: "approve" })} disabled={decide.isPending}>
        {decide.isPending ? <Loader2 className="animate-spin" /> : <Check />}
        Approve
      </Button>
      <Button variant="outline" onClick={() => setMode("edit")} disabled={decide.isPending}>
        <Pencil />
        Edit & approve
      </Button>
      <Button variant="ghost" className="text-destructive" onClick={() => setMode("reject")} disabled={decide.isPending}>
        <X />
        Reject
      </Button>

      <Dialog open={mode === "edit"} onOpenChange={(o) => setMode(o ? "edit" : null)}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Edit before approving</DialogTitle>
            <DialogDescription>
              Edits are re-checked by the policy engine. A discount above your authority will be refused.
            </DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={submitEdit}>
            {primary?.action_type === "offer_discount" ? (
              <div className="space-y-1.5">
                <Label htmlFor="discount_pct">Discount %</Label>
                <Input id="discount_pct" type="number" step="0.5" {...form.register("discount_pct")} className="w-32" />
                {form.formState.errors.discount_pct ? (
                  <p className="text-xs text-destructive">{String(form.formState.errors.discount_pct.message)}</p>
                ) : null}
              </div>
            ) : null}
            {rec.draft_body ? (
              <>
                <div className="space-y-1.5">
                  <Label htmlFor="email_subject">Subject</Label>
                  <Input id="email_subject" {...form.register("email_subject")} />
                  {form.formState.errors.email_subject ? (
                    <p className="text-xs text-destructive">{form.formState.errors.email_subject.message}</p>
                  ) : null}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="email_body">Message</Label>
                  <Textarea id="email_body" rows={9} {...form.register("email_body")} />
                  {form.formState.errors.email_body ? (
                    <p className="text-xs text-destructive">{form.formState.errors.email_body.message}</p>
                  ) : null}
                </div>
              </>
            ) : null}
            <div className="space-y-1.5">
              <Label htmlFor="note">Decision note (audit log)</Label>
              <Input id="note" placeholder="Why are you approving / changing this?" {...form.register("note")} />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setMode(null)}>
                Cancel
              </Button>
              <Button type="submit" disabled={decide.isPending}>
                {decide.isPending ? <Loader2 className="animate-spin" /> : <Check />}
                Approve with edits
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={mode === "reject"} onOpenChange={(o) => setMode(o ? "reject" : null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject this recommendation?</DialogTitle>
            <DialogDescription>Nothing will be sent to the customer. The internal follow-up task stays open.</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="reject_note">Reason (audit log)</Label>
            <Input id="reject_note" {...form.register("note")} />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setMode(null)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={() => decide.mutate({ decision: "reject", note: form.getValues("note") || undefined })}>
              Reject
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
