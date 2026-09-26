import type { Metadata } from "next";

import { Portfolio } from "@/components/portfolio/portfolio";

export const metadata: Metadata = {
  title: "项目组合 · PDOS",
  description: "PDOS portfolio view across all visible projects",
};

export default function PortfolioPage() {
  return <Portfolio />;
}
