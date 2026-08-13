import type { Metadata } from "next";

import { KnowledgeSearch } from "@/components/knowledge/knowledge-search";

export const metadata: Metadata = { title: "Knowledge Search · PDOS" };

export default function KnowledgePage() {
  return <KnowledgeSearch />;
}
