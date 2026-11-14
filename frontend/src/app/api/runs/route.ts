import { forward } from "@/lib/server/backend";

// Search history.

export async function GET(request: Request) {
  return forward(request, "/api/runs");
}
