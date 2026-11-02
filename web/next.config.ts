import type { NextConfig } from "next";
const config: NextConfig = { poweredByHeader: false, devIndicators: false, ...(process.env.PDOS_NEXT_PREVIEW_CONFIG ? { distDir: process.env.PDOS_NEXT_PREVIEW_DIST_DIR || ".next-comprehensive" } : {}) };
export default config;
