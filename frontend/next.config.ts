import type { NextConfig } from "next";

const gateway = process.env.GATEWAY_INTERNAL_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  compress: false, // SSE buffering 방지
  devIndicators: false, // 개발 표시기가 워크스페이스 버튼을 가리지 않게
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${gateway}/api/:path*` }];
  },
};

export default nextConfig;
