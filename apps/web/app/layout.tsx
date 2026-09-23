import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Noto_Sans_Thai } from "next/font/google";
import "./globals.css";
import "maplibre-gl/dist/maplibre-gl.css";
import { Providers } from "@/components/providers";

const notoSansThai = Noto_Sans_Thai({
  subsets: ["thai", "latin"],
  weight: ["300", "400", "500", "600", "700", "800"],
  variable: "--font-noto-sans-thai",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Smart Travel Assistant — ผู้ช่วยการเดินทางอัจฉริยะ",
  description: "ระบบประเมินความปลอดภัยและแนะนำเส้นทางการเดินทางแบบเรียลไทม์",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="th" className={notoSansThai.variable}>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Noto+Sans+Thai:wght@300;400;500;600;700;800&family=Prompt:wght@300;400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className={notoSansThai.className}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}

