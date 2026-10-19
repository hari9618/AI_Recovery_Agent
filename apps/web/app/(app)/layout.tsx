import { Suspense } from "react"

import { AppSidebar } from "@/components/layout/app-sidebar"
import { SiteHeader } from "@/components/layout/site-header"
import { LoadingBlock } from "@/components/shared/states"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"

// With cacheComponents (partial prerendering) the static shell is prerendered; components that read the URL
// (usePathname / useParams) stream in inside Suspense boundaries.
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <SidebarProvider>
      <Suspense fallback={<div className="hidden w-(--sidebar-width) md:block" />}>
        <AppSidebar />
      </Suspense>
      <SidebarInset>
        <SiteHeader />
        <main className="flex-1 px-4 py-6 md:px-8">
          <div className="mx-auto w-full max-w-7xl">
            <Suspense fallback={<LoadingBlock rows={6} />}>{children}</Suspense>
          </div>
        </main>
      </SidebarInset>
    </SidebarProvider>
  )
}
