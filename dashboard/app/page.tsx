"use client";

import { useEffect, useMemo, useState } from "react";
import type { GenomeRecord, StatePayload } from "@/lib/types";
import EvolutionChart from "./components/EvolutionChart";
import EventsPanel from "./components/EventsPanel";
import MemoryPanel from "./components/MemoryPanel";
import MutationPanel from "./components/MutationPanel";

const POLL_MS = 2000;

function pct(v: number | undefined) {
  return v === undefined ? "—" : `${Math.round(v * 100)}%`;
}

function useHarnessState() {
  const [state, setState] = useState<StatePayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const run = new URLSearchParams(window.location.search).get("run");
    const tick = async () => {
      try {
        const res = await fetch(`/api/state${run ? `?run=${encodeURIComponent(run)}` : ""}`, { cache: "no-store" });
        const body = await res.json();
        if (!alive) return;
        if (!res.ok) setError(body.error ?? "Failed to load state");
        else { setState(body); setError(null); }
      } catch {
        if (alive) setError("Dashboard cannot reach the API.");
      }
    };
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => { alive = false; clearInterval(id); };
  }, []);
  return { state, error };
}

function Hero({ genomes }: { genomes: GenomeRecord[] }) {
  const accepted = genomes.filter((g) => g.accepted);
  const gen0 = genomes.find((g) => g.version === 0);
  const best = accepted[accepted.length - 1];
  const rejected = genomes.filter((g) => !g.accepted).length;
  const costPerTask = (g?: GenomeRecord) => (g?.cost_usd !== undefined && g.train?.total ? g.cost_usd / g.train.total : undefined);
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
        <div className="label">Cost / task</div>
        <div className="big">{costPerTask(best) !== undefined ? `$${(costPerTask(best)! * 1000).toFixed(2)}` : "—"}<small> per 1k</small></div>
        <div className="sub">Gen 0: {costPerTask(gen0) !== undefined ? `$${(costPerTask(gen0)! * 1000).toFixed(2)}` : "—"} per 1k tasks</div>
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
  const gen0 = genomes.find((g) => g.version === 0);
  const best = [...genomes].reverse().find((g) => g.accepted);
  const running = state?.run?.status === "running";

  return (
    <main className="page">
      <header className="masthead">
        <div>
          <h1 className="wordmark">Harness<span>Forge</span></h1>
          <p className="tagline">Evolutionary CI/CD for AI agent harnesses — a MongoDB database agent that hardens itself from its own failures.</p>
        </div>
        <div className="run-meta">
          <span className={`live ${running ? "" : "done"}`}><i />{running ? "evolving" : state?.run ? "run complete" : "idle"}</span>
          {state?.run && <span className="chip">run {state.run.run_id}</span>}
          {state?.run && <span className="chip">CHEAP {state.run.models.CHEAP}</span>}
          {state?.run && <span className="chip">STRONG {state.run.models.STRONG}</span>}
          {state && <span className="chip">{state.counts.trajectories} trajectories · {state.counts.embedded} embedded · {state.counts.lessons} lessons</span>}
        </div>
      </header>

      {error && <div className="err">{error}</div>}
      <Hero genomes={genomes} />

      <div className="grid-main">
        <section className="panel">
          <h2><span className="num">01</span> Evolution metrics <span className="note">per generation · click a point to inspect</span></h2>
          <EvolutionChart genomes={genomes} selected={current?.version ?? null} onSelect={setSelected} />
        </section>
        <section className="panel">
          <h2><span className="num">04</span> Live events <span className="note">polling Atlas every 2s</span></h2>
          <EventsPanel events={state?.events ?? []} />
        </section>
      </div>

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
          <h2><span className="num">02</span> Mutation under test</h2>
          <MutationPanel record={current} />
        </section>
        <section className="panel">
          <h2><span className="num">03</span> Memory evidence <span className="badge-atlas">Atlas $vectorSearch</span></h2>
          <MemoryPanel record={current} />
        </section>
      </div>

      {state?.spotlight && (
        <section className="panel spot">
          <h2><span className="num">00</span> A Gen 0 failure <span className="note">stored as a trajectory, embedded, and turned into a regression test</span></h2>
          <p className="q">“{state.spotlight.question}”</p>
          <pre>{JSON.stringify(state.spotlight.generated_pipeline, null, 1)}</pre>
          <div><b className="fail mono">{state.spotlight.failure_type}</b> — {state.spotlight.reason}</div>
          {gen0?.train && best?.train && (
            <div className="fam">
              {Object.keys(gen0.train.by_family).map((f) => (
                <div key={f}>{f}: <b>{pct(gen0.train!.by_family[f])}</b> → <b className="pass">{pct(best.train!.by_family[f])}</b></div>
              ))}
            </div>
          )}
        </section>
      )}

      <p className="closing">LLMs propose. <span>Metrics decide.</span> MongoDB remembers.</p>
    </main>
  );
}
