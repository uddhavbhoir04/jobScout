import { forward } from "@/lib/server/backend";

// Create an account; sets the session cookie.

export async function POST(request: Request) {
  return forward(request, "/api/auth/register");
}
