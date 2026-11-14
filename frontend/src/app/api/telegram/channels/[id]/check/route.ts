import { forward, isId, notFound } from "@/lib/server/backend";

// Re-measure one channel (how many recent posts carry a recruiter email or phone).
type Ctx = { params: Promise<{ id: string }> };

export async function POST(request: Request, { params }: Ctx) {
  const { id } = await params;
  if (!isId(id)) return notFound();
  return forward(request, `/api/telegram/channels/${id}/check`);
}
