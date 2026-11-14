import { forward, isId, notFound } from "@/lib/server/backend";

// Edit one email's subject/body/status.
type Ctx = { params: Promise<{ id: string }> };

export async function PATCH(request: Request, { params }: Ctx) {
  const { id } = await params;
  if (!isId(id)) return notFound();
  return forward(request, `/api/emails/${id}`);
}
