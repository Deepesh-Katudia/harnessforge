"use client";

import type { GenomeRecord } from "@/lib/types";

const W = 760;
const H = 300;
const PAD = { l: 44, r: 16, t: 16, b: 64 };
const COST_BAND = 44;

function pct(v: number) {
  return `${Math.round(v * 100)}%`;
}

export default function EvolutionChart({ genomes, selected, onSelect }: {
  genomes: GenomeRecord[];
  selected: number | null;
  onSelect: (v: number) => void;
}) {
  if (genomes.length === 0) return <div className="empty">Waiting for Gen 0 evaluation…</div>;
  const maxV = Math.max(1, ...genomes.map((g) => g.version));
  const plotH = H - PAD.t - PAD.b;
  const x = (v: number) => PAD.l + (v / maxV) * (W - PAD.l - PAD.r);
  const y = (a: number) => PAD.t + (1 - a) * plotH;

  const accepted = genomes.filter((g) => g.accepted && g.train_accuracy !== undefined);
  // Champion line: step through accepted genomes (the parent carried forward across rejections).
  const champion: [number, number][] = [];
  accepted.forEach((g, i) => {
    if (i > 0) champion.push([g.version, accepted[i - 1].train_accuracy!]);
    champion.push([g.version, g.train_accuracy!]);
  });
  if (accepted.length && accepted[accepted.length - 1].version < maxV) {
    champion.push([maxV, accepted[accepted.length - 1].train_accuracy!]);
  }
  const holdout = accepted.filter((g) => g.holdout_accuracy !== undefined);
  const rejected = genomes.filter((g) => !g.accepted && g.train_accuracy !== undefined);
  const costs = genomes.filter((g) => g.cost_usd !== undefined);
  const maxCost = Math.max(1e-9, ...costs.map((g) => g.cost_usd!));
  const costBase = H - 18;

  const path = (pts: [number, number][]) => pts.map(([v, a], i) => `${i ? "L" : "M"}${x(v)},${y(a)}`).join(" ");

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Accuracy and cost per generation">
        {[0, 0.25, 0.5, 0.75, 1].map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} stroke="var(--line)" strokeDasharray={t ? "3 4" : undefined} />
            <text x={PAD.l - 8} y={y(t) + 4} fontSize="11" textAnchor="end" fill="var(--ink-3)" fontFamily="var(--font-mono)">{pct(t)}</text>
          </g>
        ))}
        {costs.map((g) => {
          const h = (g.cost_usd! / maxCost) * COST_BAND;
          return (
            <rect key={`c${g.version}`} x={x(g.version) - 7} y={costBase - h} width={14} height={h} rx={2}
              fill="var(--cost)" opacity={g.accepted ? 0.75 : 0.3}>
              <title>{`Gen ${g.version} train eval cost $${g.cost_usd!.toFixed(4)}`}</title>
            </rect>
          );
        })}
        <path d={path(champion)} fill="none" stroke="var(--accept)" strokeWidth={3} strokeLinejoin="round" />
        <path d={path(holdout.map((g) => [g.version, g.holdout_accuracy!]))} fill="none" stroke="var(--holdout)"
          strokeWidth={2} strokeDasharray="6 5" />
        {holdout.map((g) => (
          <g key={`h${g.version}`}>
            <rect x={x(g.version) - 5} y={y(g.holdout_accuracy!) - 5} width={10} height={10} fill="var(--holdout)" transform={`rotate(45 ${x(g.version)} ${y(g.holdout_accuracy!)})`} />
          </g>
        ))}
        {rejected.map((g) => (
          <g key={`r${g.version}`} onClick={() => onSelect(g.version)} style={{ cursor: "pointer" }}>
            <circle cx={x(g.version)} cy={y(g.train_accuracy!)} r={6} fill="var(--surface)" stroke="var(--reject)" strokeWidth={2} />
            <line x1={x(g.version) - 4} x2={x(g.version) + 4} y1={y(g.train_accuracy!) - 4} y2={y(g.train_accuracy!) + 4} stroke="var(--reject)" strokeWidth={2} />
          </g>
        ))}
        {accepted.map((g) => (
          <g key={`a${g.version}`} onClick={() => onSelect(g.version)} style={{ cursor: "pointer" }}>
            <circle cx={x(g.version)} cy={y(g.train_accuracy!)} r={selected === g.version ? 8 : 6} fill="var(--accept)" stroke="var(--surface)" strokeWidth={2} />
            <text x={x(g.version)} y={y(g.train_accuracy!) - 12} fontSize="12" fontWeight="700" textAnchor="middle" fill="var(--ink)">{pct(g.train_accuracy!)}</text>
          </g>
        ))}
        {genomes.map((g) => (
          <text key={`x${g.version}`} x={x(g.version)} y={H - 2} fontSize="11" textAnchor="middle" fill="var(--ink-3)" fontFamily="var(--font-mono)">
            G{g.version}
          </text>
        ))}
      </svg>
      <div className="legend">
        <span><i className="sw" style={{ background: "var(--accept)" }} /> train accuracy (champion)</span>
        <span><i className="sw" style={{ background: "var(--holdout)" }} /> holdout accuracy <b className="lock">🔒 hidden from meta-agent</b></span>
        <span><i className="sw" style={{ background: "var(--reject)", height: 8, width: 8, borderRadius: 8 }} /> rejected candidate</span>
        <span><i className="sw" style={{ background: "var(--cost)", height: 10, width: 8 }} /> eval cost</span>
      </div>
    </div>
  );
}
