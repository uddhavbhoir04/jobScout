import { forward } from "@/lib/server/backend";

// Start an auto-apply run (LinkedIn / Naukri / Indeed Easy Apply).

export async function POST(request: Request) {
  return forward(request, "/api/apply");
}
