import { forward } from "@/lib/server/backend";

// End the session and clear the cookie.

export async function POST(request: Request) {
  return forward(request, "/api/auth/logout");
}
