import type { Metadata } from "next"

import { Hero, MarketingNav } from "@/components/marketing/hero"
import { FinalCta, Footer, Stats, Trust, Workflow } from "@/components/marketing/sections"

export const metadata: Metadata = {
  title: "AI revenue recovery agent",
  description: "Scores every open deal, explains what is going wrong with evidence, and drafts a grounded next step for your approval.",
}

export default function LandingPage() {
  return (
    <div className="min-h-dvh overflow-x-clip">
      <MarketingNav />
      <main>
        <Hero />
        <Stats />
        <Workflow />
        <Trust />
        <FinalCta />
      </main>
      <Footer />
    </div>
  )
}
