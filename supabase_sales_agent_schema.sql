-- Instaagent autonomous sales-agent schema
-- Safe to run in Supabase SQL editor. Existing runtime code falls back to
-- dashboard_workspace_state when these tables are not present.

create table if not exists public.ai_actions (
  id uuid primary key default gen_random_uuid(),
  business_id text not null,
  customer_id text not null,
  platform text not null,
  channel text default '',
  action_type text not null,
  input_message text default '',
  ai_decision jsonb default '{}'::jsonb,
  confidence numeric default 0,
  tool_used text default '',
  reply_sent text default '',
  handoff_required boolean default false,
  manager_corrected boolean default false,
  created_at timestamptz not null default now()
);

create index if not exists ai_actions_business_created_idx
  on public.ai_actions (business_id, created_at desc);

create index if not exists ai_actions_customer_idx
  on public.ai_actions (business_id, platform, channel, customer_id);

create index if not exists ai_actions_handoff_idx
  on public.ai_actions (business_id, handoff_required, created_at desc);

create table if not exists public.customer_leads (
  id uuid primary key default gen_random_uuid(),
  business_id text not null,
  platform text not null,
  channel text default '',
  customer_id text not null,
  customer_name text default '',
  phone text default '',
  product_interest text default '',
  stage text not null default 'new',
  score integer not null default 0,
  handoff_required boolean not null default false,
  handoff_reason text default '',
  qualification_summary text default '',
  state jsonb default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (business_id, platform, channel, customer_id)
);

create index if not exists customer_leads_business_stage_idx
  on public.customer_leads (business_id, stage, updated_at desc);

create index if not exists customer_leads_hot_idx
  on public.customer_leads (business_id, handoff_required, score desc);
