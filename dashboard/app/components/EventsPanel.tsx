import type { EventRecord } from "@/lib/types";

function hhmmss(ts: string) {
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

export default function EventsPanel({ events }: { events: EventRecord[] }) {
  if (events.length === 0) return <div className="empty">No events yet.</div>;
  const chronological = [...events].reverse();
  return (
    <ol className="events" aria-live="polite">
      {chronological.map((e, i) => (
        <li key={i} className={`ev-${e.type}`}>
          <time>{hhmmss(e.ts)}</time>
          <div>
            <span className="t">{e.type}{e.generation !== null ? ` · G${e.generation}` : ""}</span>
            <span className="m">{e.message}</span>
          </div>
        </li>
      ))}
    </ol>
  );
}
