import { forward } from "@/lib/server/backend";

// Jobs auto apply tried: applied, dry run, needs you, skipped, failed.

export async function GET(request: Request) {
  return forward(request, "/api/applications");
}
