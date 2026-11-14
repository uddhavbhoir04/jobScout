import { forward } from "@/lib/server/backend";

// Outreach emails (filter + paging via query string).

export async function GET(request: Request) {
  return forward(request, "/api/emails");
}
