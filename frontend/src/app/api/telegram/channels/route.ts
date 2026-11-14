import { forward } from "@/lib/server/backend";

// List the user's Telegram channels, or add one (it is checked first).

export async function GET(request: Request) {
  return forward(request, "/api/telegram/channels");
}

export async function POST(request: Request) {
  return forward(request, "/api/telegram/channels");
}
