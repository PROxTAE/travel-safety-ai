import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import "maplibre-gl/dist/maplibre-gl.css";
import { Providers } from "@/components/providers";

export const metadata: Metadata = {
  title: "Smart Travel Assistant",
  description: "Travel safety guidance based on current, sourced information.",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
