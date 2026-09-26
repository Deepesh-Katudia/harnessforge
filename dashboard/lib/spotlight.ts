import type { Db } from "mongodb";

// Most telling failure types first; the ticket chosen for the before/after story is the one whose
// Gen-0 failure ranks highest among tickets the best genome now passes on EVERY repeat.
const STORY_PRIORITY = [
  "missing_verification", "unwarranted_action", "missed_escalation", "missed_approval", "policy_violation",
  "unauthorized_action", "missed_refusal", "invalid_field", "missing_sort", "skipped_explain", "wrong_match",
  "result_mismatch",
];

const SPOT_FIELDS = {
  _id: 0, task_id: 1, question: 1, failure_type: 1, reason: 1, generated_pipeline: 1, action: 1,
  action_args: 1, tool_calls: 1, expected_behavior: 1, generation: 1, pass: 1, diagnosis: 1,
};

async function passCounts(db: Db, runId: string, generation: number) {
  const rows = await db.collection("trajectories").aggregate<{ _id: string; runs: number; passes: number }>([
    { $match: { run_id: runId, generation, split: "train" } },
    { $group: { _id: "$task_id", runs: { $sum: 1 }, passes: { $sum: { $cond: ["$pass", 1, 0] } } } },
  ], { maxTimeMS: 5000 }).toArray();
  return new Map(rows.map((r) => [r._id, r]));
}

/** Gen-0 failure of a ticket that the best accepted genome now solves on every repeat (plus that passing run). */
export async function beforeAfter(db: Db, runId: string, bestVersion: number) {
  const trajectories = db.collection("trajectories");
  if (bestVersion > 0) {
    const [before, after] = await Promise.all([passCounts(db, runId, 0), passCounts(db, runId, bestVersion)]);
    const fixed = [...before.values()]
      .filter((b) => b.passes === 0 && after.get(b._id)?.passes === after.get(b._id)?.runs && (after.get(b._id)?.runs ?? 0) > 0)
      .map((b) => b._id);
    if (fixed.length) {
      const [failures, passes] = await Promise.all([
        trajectories.find({ run_id: runId, generation: 0, task_id: { $in: fixed }, pass: false },
                          { projection: SPOT_FIELDS }).toArray(),
        trajectories.find({ run_id: runId, generation: bestVersion, task_id: { $in: fixed }, pass: true },
                          { projection: SPOT_FIELDS }).toArray(),
      ]);
      const passedBy = new Map(passes.map((t) => [String(t.task_id), t]));
      const rank = (t: Record<string, unknown>) => {
        const i = STORY_PRIORITY.indexOf(String(t.failure_type ?? ""));
        return i === -1 ? STORY_PRIORITY.length : i;
      };
      // Prefer tickets where the evolved harness takes a *different* action: the clearest before/after.
      const changed = (t: Record<string, unknown>) =>
        passedBy.get(String(t.task_id))?.action !== t.action ? 0 : 1;
      failures.sort((a, b) => changed(a) - changed(b) || rank(a) - rank(b)
        || String(a.task_id).localeCompare(String(b.task_id)));
      const chosen = failures[0];
      return { spotlight: chosen, spotlightAfter: passedBy.get(String(chosen.task_id)) ?? null };
    }
  }
  // No fully-fixed ticket yet (e.g. a run in progress): show a Gen-0 failure on its own.
  const spotlight = await trajectories
    .find({ run_id: runId, generation: 0, split: "train", pass: false,
            failure_type: { $in: STORY_PRIORITY } }, { projection: SPOT_FIELDS })
    .sort({ task_id: 1 }).limit(1).next();
  return { spotlight, spotlightAfter: null };
}
