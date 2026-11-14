import { forward } from "@/lib/server/backend";

// Start a job that writes drafts.

export async function POST(request: Request) {
  return forward(request, "/api/emails/draft");
}
