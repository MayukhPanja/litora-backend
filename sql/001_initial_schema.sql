-- Litora database schema
-- Paste this entire script into Supabase SQL Editor and run it once.

-- 1. Brand (single brand for now)
CREATE TABLE brand (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    website     TEXT NOT NULL,
    description TEXT,
    category    TEXT,
    country     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. Prompts (generated once from brand website, reused daily)
CREATE TABLE prompts (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id         UUID NOT NULL REFERENCES brand(id) ON DELETE CASCADE,
    question_text    TEXT NOT NULL,
    category_context TEXT,
    is_active        BOOLEAN NOT NULL DEFAULT true,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_prompts_brand_id ON prompts (brand_id);

-- 3. Daily runs (one per simulation)
CREATE TYPE run_status AS ENUM ('pending', 'completed', 'failed');
CREATE TABLE daily_runs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id      UUID NOT NULL REFERENCES brand(id) ON DELETE CASCADE,
    run_date      DATE NOT NULL,
    status        run_status NOT NULL DEFAULT 'pending',
    started_at    TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    error_message TEXT
);
CREATE INDEX idx_daily_runs_brand_id ON daily_runs (brand_id);
CREATE INDEX idx_daily_runs_run_date ON daily_runs (run_date);

-- 4. Responses (one per prompt per run)
CREATE TABLE responses (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id      UUID NOT NULL REFERENCES daily_runs(id) ON DELETE CASCADE,
    prompt_id   UUID NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    model_used  TEXT,
    tokens_used INT,
    latency_ms  INT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_responses_run_id ON responses (run_id);
CREATE INDEX idx_responses_prompt_id ON responses (prompt_id);

-- 5. Brand mentions (analyzed from responses)
CREATE TYPE mention_sentiment AS ENUM ('positive', 'neutral', 'negative');
CREATE TYPE recommendation_strength AS ENUM ('strong_recommend', 'recommend', 'mentioned', 'compared_unfavorably', 'not_mentioned');
CREATE TABLE brand_mentions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    response_id             UUID NOT NULL REFERENCES responses(id) ON DELETE CASCADE,
    run_id                  UUID NOT NULL REFERENCES daily_runs(id) ON DELETE CASCADE,
    brand_name              TEXT NOT NULL,
    is_target_brand         BOOLEAN NOT NULL DEFAULT false,
    mention_position        INT,
    sentiment               mention_sentiment NOT NULL DEFAULT 'neutral',
    recommendation_strength recommendation_strength NOT NULL DEFAULT 'not_mentioned',
    context_snippet         TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_brand_mentions_response_id ON brand_mentions (response_id);
CREATE INDEX idx_brand_mentions_run_id ON brand_mentions (run_id);
CREATE INDEX idx_brand_mentions_is_target ON brand_mentions (is_target_brand);

-- 6. Competitor appearances (daily aggregate)
CREATE TABLE competitor_appearances (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id           UUID NOT NULL REFERENCES daily_runs(id) ON DELETE CASCADE,
    competitor_name  TEXT NOT NULL,
    appearance_count INT NOT NULL DEFAULT 0,
    avg_position     FLOAT,
    avg_sentiment    FLOAT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_competitor_appearances_run_id ON competitor_appearances (run_id);
