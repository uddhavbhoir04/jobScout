import { forward } from "@/lib/server/backend";

// Check the Gmail login, optionally send a test email to yourself.

export async function POST(request: Request) {
  return forward(request, "/api/email/test");
}
