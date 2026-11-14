import { forward } from "@/lib/server/backend";

// Email counts and today's sending budget.

export async function GET(request: Request) {
  return forward(request, "/api/email/stats");
}
