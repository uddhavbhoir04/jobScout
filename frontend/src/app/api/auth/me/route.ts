import { forward } from "@/lib/server/backend";

// The logged-in user.

export async function GET(request: Request) {
  return forward(request, "/api/auth/me");
}
