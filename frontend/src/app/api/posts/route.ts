import { forward } from "@/lib/server/backend";

// Saved posts (search + paging via query string).

export async function GET(request: Request) {
  return forward(request, "/api/posts");
}
