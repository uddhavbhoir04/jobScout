import { forward } from "@/lib/server/backend";

// List or connect LinkedIn accounts.

export async function GET(request: Request) {
  return forward(request, "/api/accounts");
}

export async function POST(request: Request) {
  return forward(request, "/api/accounts");
}
