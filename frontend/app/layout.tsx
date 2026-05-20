import type { Metadata } from "next";
import { IBM_Plex_Sans, IBM_Plex_Mono } from "next/font/google";
import { WsProvider } from "@/components/WsProvider";
import "./globals.css";

const plexSans = IBM_Plex_Sans({
  weight: ["400", "600"],
  subsets: ["latin"],
  variable: "--font-plex-sans",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  weight: ["400", "600"],
  subsets: ["latin"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Volta — Energy Trader's Copilot",
  description: "Voice + text-driven canvas for energy traders, by Volue.",
};

export const viewport = {
  themeColor: "#487d74",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${plexSans.variable} ${plexMono.variable}`}>
      <body>
        <WsProvider>{children}</WsProvider>
      </body>
    </html>
  );
}
