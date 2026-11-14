import { forward } from "@/lib/server/backend";

// Download contacts as CSV.

export async function GET(request: Request) {
  return forward(request, "/api/contacts.csv");
}
