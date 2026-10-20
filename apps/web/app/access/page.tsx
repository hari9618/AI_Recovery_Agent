import type { Metadata } from "next"
import { Suspense } from "react"

import { AccessForm } from "./access-form"

export const metadata: Metadata = { title: "Private demo", robots: { index: false, follow: false } }

export default function AccessPage() {
  return (
    <main className="relative flex min-h-dvh items-center justify-center overflow-hidden px-5 py-16">
      <div className="bg-grid pointer-events-none absolute inset-0 -z-10 [mask-image:radial-gradient(ellipse_60%_55%_at_50%_40%,black,transparent)]" />
      <div className="glow-copper pointer-events-none absolute top-1/4 left-1/2 -z-10 h-[28rem] w-[44rem] -translate-x-1/2" />
      <Suspense fallback={null}>
        <AccessForm contactUrl={process.env.NEXT_PUBLIC_CONTACT_URL ?? null} />
      </Suspense>
    </main>
  )
}
