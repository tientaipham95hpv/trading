import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./styles.css";

const inter = Inter({ subsets: ["latin", "vietnamese"], variable: "--font-inter" });
const jetBrainsMono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "Trading Bot",
  description: "Bảng điều khiển hệ thống giao dịch futures tự động",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi" suppressHydrationWarning>
      <body className={`${inter.variable} ${jetBrainsMono.variable}`}>{children}</body>
    </html>
  );
}
