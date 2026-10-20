import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Day Zero — 루프랩 프로덕트팀",
  description: "AI 동료와 함께 일하는 하루를 통해 협업 행동을 관찰하는 MVP",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
