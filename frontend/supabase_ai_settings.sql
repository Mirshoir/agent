alter table public.businesses
  add column if not exists ai_provider text default 'mistral',
  add column if not exists ai_model text default 'mistral-small-latest',
  add column if not exists ai_temperature numeric default 0.5,
  add column if not exists ai_max_tokens integer default 130,
  add column if not exists ai_reply_rules text,
  add column if not exists mistral_api_key text,
  add column if not exists openai_api_key text,
  add column if not exists gemini_api_key text,
  add column if not exists anthropic_api_key text;
