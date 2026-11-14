import { forward } from "@/lib/server/backend";

// Disconnect Gmail (forget the App Password).

export async function DELETE(request: Request) {
  return forward(request, "/api/email/settings/password");
}
