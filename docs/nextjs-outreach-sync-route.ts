// Place at: app/api/admin/outreach-sync/route.ts
// Install/use the Postgres client already used by your Olmem Tech site.

import { createHmac, timingSafeEqual } from "node:crypto";
import { sql } from "@vercel/postgres";

export const runtime = "nodejs";

function isValidSignature(rawBody: string, provided: string | null): boolean {
  const secret = process.env.LEAD_SYNC_SECRET;
  if (!secret || !provided?.startsWith("sha256=")) return false;

  const expected = createHmac("sha256", secret).update(rawBody).digest("hex");
  const received = provided.slice("sha256=".length);
  if (expected.length !== received.length) return false;

  return timingSafeEqual(Buffer.from(expected), Buffer.from(received));
}

export async function POST(request: Request) {
  const rawBody = await request.text();
  if (!isValidSignature(rawBody, request.headers.get("x-olmem-signature"))) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const body = JSON.parse(rawBody) as {
    event_type: string;
    payload: Record<string, unknown>;
  };

  await sql`
    CREATE TABLE IF NOT EXISTS admin_outreach_events (
      id BIGSERIAL PRIMARY KEY,
      event_type TEXT NOT NULL,
      payload JSONB NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
  `;

  await sql`
    INSERT INTO admin_outreach_events (event_type, payload)
    VALUES (${body.event_type}, ${JSON.stringify(body.payload)}::jsonb)
  `;

  return Response.json({ ok: true });
}
