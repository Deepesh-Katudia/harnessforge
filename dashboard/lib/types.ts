export type Patch = { op: string; path?: string; value?: unknown } | null;

export type Verdict = {
  accepted: boolean;
  checks: Record<string, boolean>;
  accuracy_gain?: number;
  regression_rate?: number;
  cost_change?: number;
  latency_change_ms?: number;
};

export type RetrievedFailure = {
  question: string;
  failure_type: string;
  reason?: string;
  generation?: number;
  score?: number;
};

export type Metrics = {
  accuracy: number;
  passed: number;
  total: number;
  runs?: number;
  by_family: Record<string, number>;
  failure_counts: Record<string, number>;
  cost_usd: number;
  latency_ms: number;
};

export type GenomeRecord = {
  version: number;
  parent_version: number | null;
  accepted: boolean;
  genome: Record<string, unknown>;
  patch: Patch;
  rationale?: string;
  lesson?: string;
  target_failure_type?: string;
  diff?: { path: string; before: unknown; after: unknown }[];
  verdict?: Verdict;
  train?: Metrics;
  parent_train?: Metrics;
  holdout?: Metrics;
  train_accuracy?: number;
  holdout_accuracy?: number;
  cost_usd?: number;
  latency_ms?: number;
  memory_evidence?: { query: string; dominant_failure: string | null; retrieved: RetrievedFailure[]; lessons: string[] };
};

export type EventRecord = { type: string; generation: number | null; message: string; ts: string };

export type Spotlight = {
  question: string;
  failure_type: string;
  reason: string;
  generated_pipeline: unknown;
  action: string | null;
} | null;

export type StatePayload = {
  run: { run_id: string; status: string; models: Record<string, string>; meta_model: string; started_at: string } | null;
  genomes: GenomeRecord[];
  events: EventRecord[];
  spotlight: Spotlight;
  counts: { trajectories: number; embedded: number; lessons: number };
  error?: string;
};
