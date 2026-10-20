export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: React.ReactNode
  description?: React.ReactNode
  actions?: React.ReactNode
  eyebrow?: React.ReactNode
}) {
  return (
    <div className="mb-8 flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0 space-y-2">
        {eyebrow ? <div className="eyebrow">{eyebrow}</div> : null}
        <h1 className="font-display text-3xl leading-[1.08] font-bold md:text-[2.5rem]">{title}</h1>
        {description ? <p className="max-w-3xl text-[15px] leading-relaxed text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  )
}
