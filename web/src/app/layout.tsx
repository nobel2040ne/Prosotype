import type {Metadata, Viewport} from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AutoCWI Studio",
  description: "Real-time expressive captions shaped by the voice.",
};

export const viewport: Viewport = {
  colorScheme: "dark",
  themeColor: "#090a0b",
};

export default function RootLayout({
  children,
}: Readonly<{children: React.ReactNode}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
