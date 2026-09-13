import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "SAGE — Personal AI",
  description: "SAGE: a minimal, personal AI assistant.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-[#0f1117] text-slate-100 antialiased">{children}</body>
    </html>
  );
}
