import type { NextConfig } from "next";

const securityHeaders = [
  {
    key: "Content-Security-Policy",
    value: "base-uri 'self'; frame-ancestors 'none'; object-src 'none'",
  },
  {
    key: "Permissions-Policy",
    // Same-origin recorder still requires the user's explicit browser microphone grant.
    // Keep this on the document so client-side navigation to /capture also works.
    value: "camera=(), geolocation=(), microphone=(self)",
  },
  {
    key: "Referrer-Policy",
    value: "strict-origin-when-cross-origin",
  },
  {
    key: "Strict-Transport-Security",
    value: "max-age=31536000; includeSubDomains",
  },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
];

const nextConfig: NextConfig = {
  output: "standalone",
  async headers() {
    return [{ headers: securityHeaders, source: "/:path*" }];
  },
};

export default nextConfig;
