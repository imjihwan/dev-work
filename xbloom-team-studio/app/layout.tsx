import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "xBloom Team Studio",
  description: "하나의 xBloom, 함께 만드는 커피. 팀 레시피와 공유 기기를 관리하세요.",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <body className="antialiased">{children}</body>
    </html>
  );
}
