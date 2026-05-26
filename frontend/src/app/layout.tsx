import type { Metadata } from "next"
import "./globals.css"

export const metadata: Metadata = {
  title: "Anti Gravity Deployments — Internal Deployment Platform",
  description:
    "Enterprise-grade internal deployment platform for containerized applications. Deploy, manage, and monitor your services with ease.",
  keywords: ["deployment", "docker", "containers", "devops", "platform"],
  authors: [{ name: "Anti Gravity" }],
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" className="dark">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-screen bg-background antialiased">
        {children}
      </body>
    </html>
  )
}
