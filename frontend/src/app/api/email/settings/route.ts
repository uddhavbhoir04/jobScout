import { forward } from "@/lib/server/backend";

// Gmail sender settings (paid plan).

export async function GET(request: Request) {
  return forward(request, "/api/email/settings");
}

export async function PUT(request: Request) {
  return forward(request, "/api/email/settings");
}
