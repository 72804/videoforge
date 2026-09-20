import type { NextConfig } from "next";

const isProd =
  process.env.NEXT_PUBLIC_APP_ENV === "production" || process.env.NODE_ENV === "production";
const api = process.env.API_PROXY_TARGET || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  async rewrites() {
    if (isProd) return [];
    return [
      { source: "/api/:path*", destination: `${api}/api/:path*` },
      { source: "/health", destination: `${api}/health` },
      { source: "/ready", destination: `${api}/ready` },
      { source: "/telegram/:path*", destination: `${api}/telegram/:path*` },
      { source: "/internal/:path*", destination: `${api}/internal/:path*` },
      { source: "/docs", destination: `${api}/docs` },
      { source: "/docs/:path*", destination: `${api}/docs/:path*` },
      { source: "/openapi.json", destination: `${api}/openapi.json` },
    ];
  },
};

export default nextConfig;
