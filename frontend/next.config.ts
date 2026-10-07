import { networkInterfaces } from "node:os";
import type { NextConfig } from "next";

// The Jarvis FastAPI backend. Requests to /api/jarvis/* are proxied
// there, so the browser only talks to this origin and the backend
// needs no CORS setup.
const JARVIS_API_URL = process.env.JARVIS_API_URL ?? "http://127.0.0.1:8000";

// This machine's LAN addresses, so `npm run dev -- -H 0.0.0.0` works
// from a phone on the same network (dev only; Next blocks other hosts).
const LAN_ADDRESSES = Object.values(networkInterfaces())
  .flat()
  .filter((net) => net && net.family === "IPv4" && !net.internal)
  .map((net) => net!.address);

const nextConfig: NextConfig = {
  allowedDevOrigins: LAN_ADDRESSES,
  // A stray lockfile higher up (e.g. in ~) would otherwise be picked
  // as the workspace root.
  turbopack: {
    root: __dirname,
  },
  async rewrites() {
    return [
      {
        source: "/api/jarvis/:path*",
        destination: `${JARVIS_API_URL}/:path*`,
      },
    ];
  },
  experimental: {
    // A local LLM reply can take a while on a cold model.
    proxyTimeout: 120_000,
  },
};

export default nextConfig;
