import { forward } from "@/lib/server/backend";

// Download contacts as an Excel sheet (SNo, Name, Email, Title, Company).

export async function GET(request: Request) {
  return forward(request, "/api/contacts.xlsx");
}
