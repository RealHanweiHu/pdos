import { forwardPortfolioView } from "@/lib/portfolio-bff";

export function GET() {
  return forwardPortfolioView("risks");
}
