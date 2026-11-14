import { forward } from "@/lib/server/backend";

// Upload or remove the resume attached to emails.

export async function POST(request: Request) {
  return forward(request, "/api/email/settings/resume");
}

export async function DELETE(request: Request) {
  return forward(request, "/api/email/settings/resume");
}
