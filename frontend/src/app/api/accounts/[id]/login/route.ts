import { forward, isId, notFound } from "@/lib/server/backend";

// Open a browser to log in to one LinkedIn account.
type Ctx = { params: Promise<{ id: string }> };

export async function POST(request: Request, { params }: Ctx) {
  const { id } = await params;
  if (!isId(id)) return notFound();
  return forward(request, `/api/accounts/${id}/login`);
}
