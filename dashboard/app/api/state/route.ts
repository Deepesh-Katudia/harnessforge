import { NextResponse } from "next/server";
import { hfDb } from "@/lib/mongo";
import { beforeAfter } from "@/lib/spotlight";
import type { StatePayload } from "@/lib/types";

export const dynamic = "force-dynamic";

const RUN_ID_RE = /^[a-f0-9]{6,32}$/;

export async function GET(req: Request) {
  const requested = new URL(req.url).searchParams.get("run");
  try {
    const db = await hfDb();
    // Explicit ?run= wins; otherwise the pinned DEFAULT_RUN_ID; otherwise the most recent run.
    const pinned = process.env.DEFAULT_RUN_ID;
    const target = requested && RUN_ID_RE.test(requested) ? requested
      : pinned && RUN_ID_RE.test(pinned) ? pinned : null;
    const sortLatest = { sort: { started_at: -1 as const }, projection: { _id: 0 } };
    const run = (target ? await db.collection("runs").findOne({ run_id: target }, sortLatest) : null)
      ?? await db.collection("runs").findOne({}, sortLatest);
    if (!run) {
      const empty: StatePayload = { run: null, runs: [], genomes: [], events: [], spotlight: null,
        spotlightAfter: null, bestVersion: 0,
        counts: { trajectories: 0, embedded: 0, lessons: 0 } };
      return NextResponse.json(empty);
    }
    const runId = run.run_id as string;
    const [genomes, events, trajectories, embedded, lessons, runs] = await Promise.all([
      db.collection("genomes").find({ run_id: runId }, { projection: { _id: 0, "train.failures": 0 } })
        .sort({ version: 1 }).limit(50).toArray(),
      db.collection("events").find({ run_id: runId }, { projection: { _id: 0, data: 0 } })
        .sort({ ts: -1 }).limit(60).toArray(),
      db.collection("trajectories").countDocuments({ run_id: runId }),
      db.collection("trajectories").countDocuments({ run_id: runId, embedding: { $exists: true } }),
      db.collection("lessons").countDocuments({ run_id: runId }),
      db.collection("runs").find({}, { projection: { _id: 0, run_id: 1, domain: 1, domain_title: 1, status: 1, started_at: 1 } })
        .sort({ started_at: -1 }).limit(12).toArray(),
    ]);
    const bestVersion = genomes.filter((g) => g.accepted).reduce((m, g) => Math.max(m, g.version as number), 0);
    const { spotlight, spotlightAfter } = await beforeAfter(db, runId, bestVersion);
    const payload = { run, runs, genomes, events, spotlight, spotlightAfter, bestVersion,
                      counts: { trajectories, embedded, lessons } };
    return NextResponse.json(payload, { headers: { "Cache-Control": "no-store" } });
  } catch (err) {
    console.error("state route failed", err);
    return NextResponse.json({ error: "Could not read HarnessForge state from Atlas." }, { status: 500 });
  }
}
