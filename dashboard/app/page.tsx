"use client";

import { useEffect, useMemo, useState } from "react";
import type { GenomeRecord, RunSummary, Spotlight, StatePayload } from "@/lib/types";
import EvolutionChart from "./components/EvolutionChart";
import EventsPanel from "./components/EventsPanel";
import MemoryPanel from "./components/MemoryPanel";
import MutationPanel from "./components/MutationPanel";

const POLL_MS = 2000;
const FLOW = ["Request", "Agent actions", "Failure", "MongoDB memory", "Harness mutation", "Re-evaluation", "Accept / reject"];

function pct(v: number | undefined) {
  return v === undefined ? "—" : `${Math.round(v * 100)}%`;
}

function currentRunParam(): string | null {
  return typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get("run");
}

function useHarnessState() {
  const [state, setState] = useState<StatePayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    let id: ReturnType<typeof setInterval> | undefined;
    const run = currentRunParam();
    const tick = async () => {
      try {
        const res = await fetch(`/api/state${run ? `?run=${encodeURIComponent(run)}` : ""}`, { cache: "no-store" });
        const body = await res.json();
        if (!alive) return;
        if (!res.ok) { setError(body.error ?? "Failed to load state"); return; }
        setState(body);
        setError(null);
        // A finished run never changes: stop polling instead of refreshing forever.
        if (body.run?.status === "complete" && id !== undefined) { clearInterval(id); id = undefined; }
      } catch {
        if (alive) setError("Dashboard cannot reach the API.");
      }
    };
    id = setInterval(tick, POLL_MS);
    tick();
    return () => { alive = false; if (id !== undefined) clearInterval(id); };
  }, []);
  return { state, error };
}

function RunSwitcher({ runs, current }: { runs: RunSummary[]; current?: string }) {
  if (runs.length < 2) return null;
  return (
    <label className="chip run-switch">
      proving ground{" "}
      <select value={current} onChange={(e) => { window.location.search = `?run=${e.target.value}`; }}>
        {runs.map((r) => (
          <option key={r.run_id} value={r.run_id}>
            {(r.domain_title ?? "MongoDB database-operations agent")} · {r.run_id} · {r.status}
          </option>
        ))}
      </select>
    </label>
  );
}

function decisionOf(spot: NonNullable<Spotlight>) {
  if (spot.action_args && Object.keys(spot.action_args).length) return { action: spot.action, args: spot.action_args };
  return spot.generated_pipeline ?? spot.diagnosis ?? { action: spot.action };
}

function Trajectory({ spot, label, passed }: { spot: NonNullable<Spotlight>; label: string; passed: boolean }) {
  return (
    <div className={`traj ${passed ? "traj-pass" : "traj-fail"}`}>
      <div className="traj-head">
        <span className="story-label">{label}</span>
        <span className={`verdict ${passed ? "acc" : "rej"}`}>{passed ? "PASSED" : "FAILED"}</span>
      </div>
      {spot.tool_calls && spot.tool_calls.length > 0 && (
        <div className="toolchips">
          {spot.tool_calls.map((c, i) => (
            <span key={i} className={`toolchip ${c.ok ? "" : "bad"}`}>{c.tool}{c.ok ? "" : " ✕"}</span>
          ))}
        </div>
      )}
      <pre>{JSON.stringify(decisionOf(spot), null, 1)}</pre>
      <p className="traj-why">{passed ? "Deterministic check: correct action, correct arguments, evidence gathered first."
                                      : <><b className="fail mono">{spot.failure_type}</b>: {spot.reason}</>}</p>
    </div>
  );
}

function FailureStory({ before, after, bestVersion }: { before: Spotlight; after: Spotlight; bestVersion: number }) {
  if (!before) return null;
  return (
    <section className="panel spot">
      <h2><span className="num">00</span> Same ticket, before and after evolution
        <span className="note">real trajectories stored in MongoDB · scored deterministically, no LLM judge</span></h2>
      <p className="q">“{before.question}”</p>
      {before.expected_behavior && <p className="mono expected">Expected: {before.expected_behavior}</p>}
      <div className="story">
        <Trajectory spot={before} label="Gen 0 · weak harness" passed={false} />
        {after
          ? <Trajectory spot={after} label={`Gen ${bestVersion} · evolved harness`} passed />
          : <div className="traj traj-pending"><span className="story-label">Evolving…</span>
              <p className="note-small">The failure is embedded with Voyage and retrieved via Atlas <code>$vectorSearch</code> while the harness evolves.</p></div>}
      </div>
    </section>
  );
}

function Hero({ genomes }: { genomes: GenomeRecord[] }) {
  const accepted = genomes.filter((g) => g.accepted);
  const gen0 = genomes.find((g) => g.version === 0);
  const best = accepted[accepted.length - 1];
  const rejected = genomes.filter((g) => !g.accepted).length;
  const costPerTask = (g?: GenomeRecord) => {
    const n = g?.train?.runs ?? g?.train?.total;
    return g?.cost_usd !== undefined && n ? g.cost_usd / n : undefined;
  };
  return (
    <section className="hero">
      <div className="stat primary">
        <div className="label">Hidden holdout accuracy</div>
        <div className="big">{pct(gen0?.holdout_accuracy)}<span className="arrow">→</span><span className="up">{pct(best?.holdout_accuracy)}</span></div>
        <div className="sub">Gen 0 → Gen {best?.version ?? 0} · never shown to the meta-agent</div>
      </div>
      <div className="stat">
        <div className="label">Train accuracy</div>
        <div className="big">{pct(gen0?.train_accuracy)}<span className="arrow">→</span><span className="up">{pct(best?.train_accuracy)}</span></div>
      </div>
      <div className="stat">
        <div className="label">Cost / 1k tasks</div>
        <div className="big">{costPerTask(best) !== undefined ? `$${(costPerTask(best)! * 1000).toFixed(2)}` : "—"}</div>
        <div className="sub">Gen 0: {costPerTask(gen0) !== undefined ? `$${(costPerTask(gen0)! * 1000).toFixed(2)}` : "—"}</div>
      </div>
      <div className="stat">
        <div className="label">Mutations</div>
        <div className="big">{Math.max(0, accepted.length - 1)}<small> accepted</small></div>
        <div className="sub">{rejected} rejected by the gates</div>
      </div>
    </section>
  );
}

export default function Page() {
  const { state, error } = useHarnessState();
  const [selected, setSelected] = useState<number | null>(null);
  const genomes = useMemo(() => state?.genomes ?? [], [state]);
  const latest = genomes[genomes.length - 1];
  const current = genomes.find((g) => g.version === selected) ?? latest;
  const running = state?.run?.status === "running";
  const domainTitle = state?.run?.domain_title ?? (state?.run ? "MongoDB database-operations agent" : "");

  return (
    <main className="page">
      <header className="masthead">
        <div>
          <h1 className="wordmark">Harness<span>Forge</span></h1>
          <p className="tagline">Evolutionary CI/CD for operational AI agents. Production failures become measurable harness improvements.</p>
        </div>
        <div className="run-meta">
          <span className={`live ${running ? "" : "done"}`}><i />{running ? "evolving" : state?.run ? "run complete" : "idle"}</span>
          {domainTitle && <span className="chip">proving ground: {domainTitle}</span>}
          {state?.run && <span className="chip">CHEAP {state.run.models.CHEAP}</span>}
          {state && <span className="chip">{state.counts.trajectories} trajectories · {state.counts.embedded} embedded · {state.counts.lessons} lessons</span>}
          {state && <RunSwitcher runs={state.runs ?? []} current={state.run?.run_id} />}
        </div>
      </header>

      <ol className="flow" aria-label="HarnessForge loop">
        {FLOW.map((step) => <li key={step}>{step}</li>)}
      </ol>

      {error && <div className="err">{error}</div>}
      <FailureStory before={state?.spotlight ?? null} after={state?.spotlightAfter ?? null} bestVersion={state?.bestVersion ?? 0} />
      <Hero genomes={genomes} />

      <nav className="lineage" aria-label="Generations">
        {genomes.map((g) => (
          <button key={g.version} type="button" onClick={() => setSelected(g.version)}
            className={`gen ${g.accepted ? "acc" : "rej"} ${current?.version === g.version ? "sel" : ""}`}>
            G{g.version} {g.train_accuracy !== undefined ? pct(g.train_accuracy) : "invalid"}
          </button>
        ))}
      </nav>

      <div className="grid-two">
        <section className="panel">
          <h2><span className="num">01</span> Harness mutation under test</h2>
          <MutationPanel record={current} />
        </section>
        <section className="panel">
          <h2><span className="num">02</span> Memory evidence <span className="badge-atlas">Atlas $vectorSearch</span></h2>
          <MemoryPanel record={current} />
        </section>
      </div>

      <div className="grid-main">
        <section className="panel">
          <h2><span className="num">03</span> Re-evaluation per generation <span className="note">click a point to inspect</span></h2>
          <EvolutionChart genomes={genomes} selected={current?.version ?? null} onSelect={setSelected} />
        </section>
        <section className="panel">
          <h2><span className="num">04</span> Live events <span className="note">polling Atlas every 2s</span></h2>
          <EventsPanel events={state?.events ?? []} />
        </section>
      </div>

      <p className="closing">LLMs propose. <span>Metrics decide.</span> MongoDB remembers.</p>
    </main>
  );
}
