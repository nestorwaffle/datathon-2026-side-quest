export type Row = Record<string, unknown>;

export interface Identity {
  user_id: string;
  org_id: string;
  name?: string;
  role: string;
  team_id?: string | null;
  org_name?: string;
  organization_name?: string;
  organizations: {id: string; name: string}[];
  source_scope?: 'workspace' | 'organization';
}

export interface Scope {
  hours: number;
  source_scope?: 'workspace' | 'organization';
  run_id?: string;
  session_id?: string;
  provider?: string;
  model?: string;
  origin_user_id?: string;
  agent?: string;
  activity_kind?: string;
  team_id?: string;
  project_id?: string;
}

export interface SourceInfo {
  id?: string;
  name?: string;
  database?: string;
  endpoint?: string;
  scope?: 'workspace' | 'organization';
  can_read_global?: boolean;
  can_manage_source?: boolean;
  grants?: {org_id: string; name: string; owner?: boolean | number}[];
  read_configured?: boolean;
  write_configured?: boolean;
  tables?: (string | {name: string; state?: string; rows?: number})[];
  coverage?: Row | string;
  error?: string;
}

export interface DeliveryInfo {
  total?: number;
  pending?: number;
  retries?: number;
  last_sync?: number | string | null;
  last_attempt?: number | string | null;
  last_error?: string | null;
  oldest_pending_age_seconds?: number | null;
  available?: boolean;
  scope?: string;
}

export interface Evidence {
  tool?: string;
  arguments?: Row;
  sql?: string;
  data?: Row[];
  source?: string;
  [key: string]: unknown;
}

export interface Investigation {
  id: string;
  conversation_id?: string;
  question: string;
  conclusion?: string;
  status: string;
  created_at?: string;
  timestamp?: string;
  updated_at?: string;
  scope?: Scope;
  phase?: string;
  evidence?: Evidence[];
  progress_events?: {at?: string; phase?: string; message?: string}[];
  calls?: Row[];
  usage?: {prompt_tokens?: number; completion_tokens?: number; total_tokens?: number};
  query_count?: number;
  iterations?: number;
  model?: string;
  error?: string;
  finish_reason?: string;
  truncated?: boolean;
  partial_summary?: string;
  conversation_context_turns?: number;
  context_bounded?: boolean;
  read_only?: boolean;
  historical_scope_unverified?: boolean;
  context_eligible?: boolean;
  journal_unavailable?: boolean;
  persistence_status?: string;
  seconds?: number;
  followup_view?: Row;
}

export interface AnalystStatus {
  configured?: boolean;
  model?: string;
  base_url?: string;
  status?: string;
  error?: string;
  max_iterations?: number;
  max_queries?: number;
  configuration_valid?: boolean;
  rawtree_configured?: boolean;
}

export interface Overview {
  summary?: Row;
  agents?: Row[];
  trend?: Row[];
  source?: string;
  scope?: Row;
  coverage?: Row;
  trend_limited?: boolean;
  trend_limit?: number;
}

export interface PageResult {
  items: Row[];
  page?: number;
  has_more?: boolean;
  total?: number | null;
  source?: string;
  scope?: Row;
  limited?: boolean;
  limit?: number;
}

export interface ExperimentResult {
  items: Row[];
  summary?: {runs?: number; comparable_groups?: number; latest_accuracy?: number | null};
  breakdown?: Row[];
  coverage?: Row;
  scope?: Row;
  source?: string;
}
