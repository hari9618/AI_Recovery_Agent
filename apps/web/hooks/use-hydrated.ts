import { useSyncExternalStore } from "react"

const subscribe = () => () => {}

/**
 * False while a component hydrates, true afterwards.
 *
 * Suspense boundaries hydrate independently, so a query started by an earlier boundary (the header) can
 * already have data when a later one (the sidebar, the page) hydrates. Rendering that data during
 * hydration would not match the server HTML; gate it on this hook instead.
 */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  )
}
