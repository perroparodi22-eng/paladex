/**
 * Health check for hosted previews: confirms the server can open the catalogue
 * database. Returns only a count, never data.
 */
import { NextResponse } from "next/server";
import { count } from "drizzle-orm";
import { getDb, schema } from "@/server/db";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const db = await getDb();
    const [row] = await db.select({ n: count() }).from(schema.products);
    return NextResponse.json({ ok: true, rackets: row.n });
  } catch (e) {
    return NextResponse.json({ ok: false, error: (e as Error).message }, { status: 500 });
  }
}
