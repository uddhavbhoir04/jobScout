import { forward, isId, notFound } from "@/lib/server/backend";

// Pause/resume or remove one Telegram channel.
type Ctx = { params: Promise<{ id: string }> };

export async function PATCH(request: Request, { params }: Ctx) {
  const { id } = await params;
  if (!isId(id)) return notFound();
  return forward(request, `/api/telegram/channels/${id}`);
}

export async function DELETE(request: Request, { params }: Ctx) {
  const { id } = await params;
  if (!isId(id)) return notFound();
  return forward(request, `/api/telegram/channels/${id}`);
}
