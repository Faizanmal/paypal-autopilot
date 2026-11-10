import { existsSync } from "node:fs";
import { resolve } from "node:path";
import type { NextConfig } from "next";

// Next loads apps/web/.env itself; local development shares the repository .env.
// loadEnvFile preserves values already provided by the host or Next.
const rootEnv = resolve(process.cwd(), "../../.env");
if (existsSync(rootEnv)) {
  process.loadEnvFile(rootEnv);
}

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.API_INTERNAL_BASE_URL ?? "http://127.0.0.1:8000"}/api/:path*`,
      },
    ];
  },
  cacheComponents: true,
  partialPrefetching: true,
  experimental: {
    webpackMemoryOptimizations: true,
  },
};

export default nextConfig;
