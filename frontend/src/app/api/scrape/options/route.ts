import { forward } from "@/lib/server/backend";

// Date presets and limits for the search form.

export async function GET(request: Request) {
  return forward(request, "/api/scrape/options");
}
