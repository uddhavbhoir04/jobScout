import { forward } from "@/lib/server/backend";

// Upload the CV auto apply answers from (and attaches where a form asks for a file).

export async function POST(request: Request) {
  return forward(request, "/api/apply/resume");
}
