import type { Metadata } from "next";

import { EvidenceBase } from "@/components/knowledge/evidence-base";
import { KnowledgeSearch } from "@/components/knowledge/knowledge-search";

export const metadata: Metadata = { title: "Knowledge Search · PDOS" };

export default function KnowledgePage() {
  return (
    <div className="space-y-10">
      <KnowledgeSearch />
      {/* V2-7 evidence base: sources and the immutable snapshots agent
          conclusions cite. It lives beside knowledge search because both
          answer "what do we actually know, and how do we know it". */}
      <EvidenceBase />
    </div>
  );
}
