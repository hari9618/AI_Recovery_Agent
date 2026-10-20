"use client"

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MotionConfig } from "motion/react"
import { ThemeProvider } from "next-themes"
import { useState } from "react"

import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { ApiError } from "@/lib/api"

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            refetchOnWindowFocus: false,
            // Retry only errors the API marks as retryable (closed error contract).
            retry: (count, error) => count < 2 && (!(error instanceof ApiError) || error.payload.retryable),
          },
        },
      }),
  )
  return (
    <ThemeProvider attribute="class" defaultTheme="light" enableSystem disableTransitionOnChange>
      <QueryClientProvider client={client}>
        <MotionConfig reducedMotion="user">
          <TooltipProvider delayDuration={200}>
            {children}
            <Toaster richColors closeButton position="top-right" />
          </TooltipProvider>
        </MotionConfig>
      </QueryClientProvider>
    </ThemeProvider>
  )
}
