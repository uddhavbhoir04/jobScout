import { forward } from "@/lib/server/backend";

// Log in; sets the session cookie.

export async function POST(request: Request) {
  return forward(request, "/api/auth/login");
}
