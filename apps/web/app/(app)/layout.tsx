import { Suspense } from "react"

import { ChatProvider } from "@/components/chat/chat-provider"
import { ChatWidget } from "@/components/chat/chat-widget"
import { AppSidebar } from "@/components/layout/app-sidebar"
import { SiteHeader } from "@/components/layout/site-header"
import { LoadingBlock } from "@/components/shared/states"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"

// With cacheComponents (partial prerendering) the static shell is prerendered; components that read the URL
// (usePathname / useParams) stream in inside Suspense boundaries.
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <ChatProvider>
      <SidebarProvider>
        <Suspense fallback={<div className="hidden w-(--sidebar-width) md:block" />}>
          <AppSidebar />
        </Suspense>
        <SidebarInset className="min-w-0 md:border md:border-sidebar-border/40">
          <SiteHeader />
          <main className="flex-1 px-4 py-8 md:px-8">
            <div className="mx-auto w-full max-w-7xl">
              <Suspense fallback={<LoadingBlock rows={6} />}>{children}</Suspense>
            </div>
          </main>
        </SidebarInset>
        <Suspense fallback={null}>
          <ChatWidget />
        </Suspense>
      </SidebarProvider>
    </ChatProvider>
  )
}
