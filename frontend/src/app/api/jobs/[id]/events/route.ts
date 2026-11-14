import { forward, isJobId, notFound } from "@/lib/server/backend";

// Live job events (Server-Sent Events stream).
type Ctx = { params: Promise<{ id: string }> };

export async function GET(request: Request, { params }: Ctx) {
  const { id } = await params;
  if (!isJobId(id)) return notFound();
  return forward(request, `/api/jobs/${id}/events`, { stream: true });
}
