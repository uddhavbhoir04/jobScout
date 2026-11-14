import { forward } from "@/lib/server/backend";

// Start a job that sends ready drafts.

export async function POST(request: Request) {
  return forward(request, "/api/emails/send");
}
