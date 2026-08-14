import type {Metadata, Viewport} from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Weave Studio",
  description: "Real-time expressive captions shaped by the voice.",
};

export const viewport: Viewport = {
  colorScheme: "light dark",
  // Apple parchment -- the same `--bg` the default (light) stage paints, so the
  // browser chrome matches the page instead of the off-palette cream that used
  // to sit here. The stage theme is a data-attribute toggle, not
  // prefers-color-scheme, so this is one value rather than a media list.
  themeColor: "#f5f5f7",
};

export default function RootLayout({
  children,
}: Readonly<{children: React.ReactNode}>) {
  // The light stage is the default, so the exported HTML carries it and the
  // first paint is already correct. LiveStudio's toggle rewrites this attribute.
  return (
    <html lang="en" data-theme="light">
      <body>{children}</body>
    </html>
  );
}
