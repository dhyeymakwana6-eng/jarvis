import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  // <title> is rendered by JarvisOrb so it can follow the JARVIS/ULTRON mode.
  description: "Personal AI assistant with long-term memory",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#000000",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
