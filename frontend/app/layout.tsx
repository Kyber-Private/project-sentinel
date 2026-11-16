import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Project Sentinel",
  description: "Upload your business documents. Answer a few intelligent questions. Understand where your finances are heading and why.",
};

export const viewport: Viewport = { themeColor: "#F7F8FC", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen font-sans">{children}</body>
    </html>
  );
}
