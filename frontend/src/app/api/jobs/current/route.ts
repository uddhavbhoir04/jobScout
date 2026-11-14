import { forward } from "@/lib/server/backend";

// The user's running (or latest) job of a kind.

export async function GET(request: Request) {
  return forward(request, "/api/jobs/current");
}
