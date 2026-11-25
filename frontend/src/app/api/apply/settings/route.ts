import { forward } from "@/lib/server/backend";

// The auto-apply answers sheet, learned answers and daily cap.

export async function GET(request: Request) {
  return forward(request, "/api/apply/settings");
}

export async function PUT(request: Request) {
  return forward(request, "/api/apply/settings");
}
