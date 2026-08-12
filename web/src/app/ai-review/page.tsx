import type { Metadata } from "next";

import { AiReviewInbox } from "@/components/ai/ai-review-inbox";

export const metadata: Metadata = { title: "AI Review 收件箱 · PDOS" };

export default function AiReviewPage() {
  return <AiReviewInbox />;
}
