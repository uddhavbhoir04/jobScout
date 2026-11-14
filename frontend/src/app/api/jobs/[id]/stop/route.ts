import { forward, isJobId, notFound } from "@/lib/server/backend";

// Ask a running job to stop.
type Ctx = { params: Promise<{ id: string }> };

export async function POST(request: Request, { params }: Ctx) {
  const { id } = await params;
  if (!isJobId(id)) return notFound();
  return forward(request, `/api/jobs/${id}/stop`);
}
