import { cn } from "cn"

function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn("shimmer-skeleton rounded-lg", className)}
      {...props}
    />
  )
}

export { Skeleton }
