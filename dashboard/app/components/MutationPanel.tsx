import type { GenomeRecord } from "@/lib/types";

const CHECK_LABELS: Record<string, string> = {
  accuracy_improved: "Child train accuracy > parent",
  regression_ok: "Regression rate ≤ 10%",
  cost_ok: "Cost within budget (or big accuracy gain)",
  valid_patch: "Patch passes allowlist validation",
};

function fmt(v: unknown) {
  return v === null || v === undefined ? "∅" : JSON.stringify(v);
}

function signedPct(v: number | undefined) {
  if (v === undefined) return "—";
  const n = Math.round(v * 1000) / 10;
  return `${n > 0 ? "+" : ""}${n}%`;
}

export default function MutationPanel({ record }: { record: GenomeRecord | undefined }) {
  if (!record) return <div className="empty">No mutation yet.</div>;
  if (record.version === 0) {
    return (
      <div>
        <p style={{ marginTop: 0 }}><b>Gen 0 — the blank harness.</b> No rules, no schema, no memory, cheap model, no retries,
          only the <code>run_aggregate</code> tool. Locked guardrails: read-only, allowlisted collections, blocked stages, maxTimeMS.</p>
        <div className="diff">{JSON.stringify(record.genome, null, 1)}</div>
      </div>
    );
  }
  const v = record.verdict;
  const parentAcc = record.parent_train?.accuracy;
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <span className="mono" style={{ fontSize: 13, color: "var(--ink-2)" }}>
          Gen {record.parent_version} → candidate Gen {record.version}
        </span>
        <span className={`verdict ${record.accepted ? "acc" : "rej"}`}>{record.accepted ? "ACCEPTED" : "REJECTED"}</span>
      </div>
      <div className="diff">
        {(record.diff ?? []).length === 0 && <span>(no valid patch)</span>}
        {(record.diff ?? []).map((d, i) => (
          <div key={i}>
            <div>{d.path}:</div>
            {d.before !== null && d.before !== undefined && <div className="minus">- {fmt(d.before)}</div>}
            {d.after !== null && d.after !== undefined && <div className="plus">+ {fmt(d.after)}</div>}
          </div>
        ))}
      </div>
      {record.rationale && <p className="rationale"><b>Meta-agent rationale:</b> {record.rationale}</p>}
      <table className="gates">
        <tbody>
          <tr><td>Parent → child train accuracy</td><td>{parentAcc !== undefined ? `${Math.round(parentAcc * 100)}%` : "—"} → {record.train_accuracy !== undefined ? `${Math.round(record.train_accuracy * 100)}%` : "—"}</td></tr>
          <tr><td>Regression rate</td><td>{v?.regression_rate !== undefined ? `${Math.round(v.regression_rate * 100)}%` : "—"}</td></tr>
          <tr><td>Cost change</td><td>{signedPct(v?.cost_change)}</td></tr>
          <tr><td>Latency change</td><td>{v?.latency_change_ms !== undefined ? `${v.latency_change_ms > 0 ? "+" : ""}${v.latency_change_ms} ms` : "—"}</td></tr>
          {Object.entries(v?.checks ?? {}).map(([k, ok]) => (
            <tr key={k}><td>{CHECK_LABELS[k] ?? k}</td><td className={ok ? "pass" : "fail"}>{ok ? "PASS" : "FAIL"}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
