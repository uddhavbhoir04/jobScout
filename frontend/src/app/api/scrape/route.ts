import { forward } from "@/lib/server/backend";

// Start a LinkedIn search job.

export async function POST(request: Request) {
  return forward(request, "/api/scrape");
}
