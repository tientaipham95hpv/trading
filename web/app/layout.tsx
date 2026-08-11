import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "Điều Khiển Giao Dịch",
  description: "Bảng điều khiển hệ thống giao dịch futures tự động",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi">
      <body>{children}</body>
    </html>
  );
}
