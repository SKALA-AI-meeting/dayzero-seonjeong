import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Day Zero — 모아마켓 협업 과제",
  description: "AI 동료와 함께하는 서비스 기획 협업 관찰 MVP",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
