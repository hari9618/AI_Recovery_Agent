"use client"

import { Fragment } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

import { cn } from "@/lib/utils"

// Models sometimes put <br> inside table cells (markdown has no in-cell line break). Raw HTML is never
// rendered, so the tag is swapped for an invisible marker that cells turn back into a real line break.
const BREAK = String.fromCharCode(0x2063) // invisible separator
const BR_TAG = /<br\s*\/?>/gi

function withBreaks(children: React.ReactNode): React.ReactNode {
  const parts = Array.isArray(children) ? children : [children]
  return parts.map((child, i) =>
    typeof child === "string" && child.includes(BREAK) ? (
      <Fragment key={i}>
        {child.split(BREAK).map((piece, j) => (
          <Fragment key={j}>
            {j > 0 ? <br /> : null}
            {piece}
          </Fragment>
        ))}
      </Fragment>
    ) : (
      child
    ),
  )
}

/** Renders model output as markdown. Raw HTML is never rendered (react-markdown's default). */
export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cn("prose-chat", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          td: ({ children }) => <td>{withBreaks(children)}</td>,
          p: ({ children }) => <p>{withBreaks(children)}</p>,
          li: ({ children }) => <li>{withBreaks(children)}</li>,
          table: ({ children }) => (
            <div className="table-wrap">
              <table>{children}</table>
            </div>
          ),
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer noopener">
              {children}
            </a>
          ),
        }}
      >
        {children.replace(BR_TAG, BREAK)}
      </ReactMarkdown>
    </div>
  )
}
