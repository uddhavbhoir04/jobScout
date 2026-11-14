import { forward } from "@/lib/server/backend";

// Liveness check (frontend + backend).

export async function GET(request: Request) {
  return forward(request, "/api/health");
}
