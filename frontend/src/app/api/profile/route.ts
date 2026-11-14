import { forward } from "@/lib/server/backend";

// The logged-in user's profile and plan.

export async function GET(request: Request) {
  return forward(request, "/api/profile");
}
