import { forward } from "@/lib/server/backend";

// Totals for the dashboard.

export async function GET(request: Request) {
  return forward(request, "/api/stats");
}
