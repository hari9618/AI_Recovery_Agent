import type { Metadata } from "next"
import { Bricolage_Grotesque, Geist, Geist_Mono } from "next/font/google"

import { Providers } from "@/components/providers"

import "./globals.css"

const geist = Geist({ variable: "--font-geist", subsets: ["latin"] })
const bricolage = Bricolage_Grotesque({ variable: "--font-bricolage", subsets: ["latin"], axes: ["opsz"] })
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] })

export const metadata: Metadata = {
  title: { default: "Revenue Recovery", template: "%s · Revenue Recovery" },
  description: "AI revenue recovery agent — finds, explains, prioritises and helps recover at-risk revenue.",
}

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geist.variable} ${bricolage.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full">
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
