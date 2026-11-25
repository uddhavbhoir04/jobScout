import { forward, isId, notFound } from "@/lib/server/backend";

// Mark an application as applied by hand (or not interested).
type Ctx = { params: Promise<{ id: string }> };

export async function PATCH(request: Request, { params }: Ctx) {
  const { id } = await params;
  if (!isId(id)) return notFound();
  return forward(request, `/api/applications/${id}`);
}
