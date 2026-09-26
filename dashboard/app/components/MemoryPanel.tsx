import type { GenomeRecord } from "@/lib/types";

export default function MemoryPanel({ record }: { record: GenomeRecord | undefined }) {
  const ev = record?.memory_evidence;
  if (!ev) {
    return <div className="empty">Memory evidence appears once the meta-agent proposes a mutation.</div>;
  }
  return (
    <div>
      <div style={{ fontSize: 13, color: "var(--ink-2)", marginBottom: 6 }}>
        Dominant train failure: <b className="mono" style={{ color: "var(--reject)" }}>{ev.dominant_failure ?? "—"}</b>. Query embedded with Voyage:
      </div>
      <div className="mem-query">{ev.query}</div>
      <ul className="mem-list">
        {ev.retrieved.length === 0 && <li><span className="q">No earlier failures in memory yet.</span></li>}
        {ev.retrieved.map((r, i) => (
          <li key={i}>
            <span className="q">{r.question}</span>
            <span className="score">{r.score !== undefined ? r.score.toFixed(3) : ""}</span>
            <span className="ft">{r.failure_type}{r.generation !== undefined ? ` · gen ${r.generation}` : ""}</span>
          </li>
        ))}
      </ul>
      {ev.lessons.length > 0 && (
        <div style={{ marginTop: 10, fontSize: 13 }}>
          <b>Lessons recalled:</b>
          <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{ev.lessons.map((l, i) => <li key={i}>{l}</li>)}</ul>
        </div>
      )}
    </div>
  );
}
