import type { NextConfig } from "next";

const bffOrigin = process.env.STUDIO_BFF_INTERNAL_URL ?? "http://localhost:8010";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/bff/:path*", destination: `${bffOrigin}/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
