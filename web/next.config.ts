import type { NextConfig } from "next";

/** Aperium AIS collector (FastAPI). `../dev.sh` sets this to match BACKEND_PORT. */
const APERIUM_API_URL = process.env.APERIUM_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  // Proxy the collector same-origin: the FastAPI app has no CORS and binds to loopback.
  async rewrites() {
    return [{ source: "/aperium/:path*", destination: `${APERIUM_API_URL}/api/:path*` }];
  },
};

export default nextConfig;
