import type { NextConfig } from "next";

const gateway = process.env.GATEWAY_INTERNAL_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  compress: false, // SSE buffering 방지
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${gateway}/api/:path*` }];
  },
};

export default nextConfig;
