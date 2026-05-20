import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  experimental: {
    optimizePackageImports: ["date-fns", "date-fns-tz", "recharts"],
  },
};

export default nextConfig;
