import { NextResponse } from "next/server";
import { hfDb } from "@/lib/mongo";
import type { StatePayload } from "@/lib/types";

export const dynamic = "force-dynamic";

const RUN_ID_RE = /^[a-f0-9]{6,32}$/;

export async function GET(req: Request) {
  const requested = new URL(req.url).searchParams.get("run");
  try {
    const db = await hfDb();
    const runFilter = requested && RUN_ID_RE.test(requested) ? { run_id: requested } : {};
    const run = await db.collection("runs").findOne(runFilter, { sort: { started_at: -1 }, projection: { _id: 0 } });
    if (!run) {
      const empty: StatePayload = { run: null, genomes: [], events: [], spotlight: null,
        counts: { trajectories: 0, embedded: 0, lessons: 0 } };
      return NextResponse.json(empty);
    }
    const runId = run.run_id as string;
    const [genomes, events, spotlight, trajectories, embedded, lessons] = await Promise.all([
      db.collection("genomes").find({ run_id: runId }, { projection: { _id: 0, "train.failures": 0 } })
        .sort({ version: 1 }).limit(50).toArray(),
      db.collection("events").find({ run_id: runId }, { projection: { _id: 0, data: 0 } })
        .sort({ ts: -1 }).limit(60).toArray(),
      db.collection("trajectories").findOne(
        { run_id: runId, generation: 0, split: "train", pass: false, family: "query",
          failure_type: { $in: ["invalid_field", "missing_sort", "wrong_match", "result_mismatch"] } },
        { projection: { _id: 0, question: 1, failure_type: 1, reason: 1, generated_pipeline: 1, action: 1 } }),
      db.collection("trajectories").countDocuments({ run_id: runId }),
      db.collection("trajectories").countDocuments({ run_id: runId, embedding: { $exists: true } }),
      db.collection("lessons").countDocuments({ run_id: runId }),
    ]);
    const payload = { run, genomes, events, spotlight, counts: { trajectories, embedded, lessons } };
    return NextResponse.json(payload, { headers: { "Cache-Control": "no-store" } });
  } catch (err) {
    console.error("state route failed", err);
    return NextResponse.json({ error: "Could not read HarnessForge state from Atlas." }, { status: 500 });
  }
}
