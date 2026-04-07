-- Drop all tables and types. Run this before re-running 001_initial_schema.sql.
DROP TABLE IF EXISTS competitor_appearances CASCADE;
DROP TABLE IF EXISTS brand_mentions CASCADE;
DROP TABLE IF EXISTS responses CASCADE;
DROP TABLE IF EXISTS conversation_messages CASCADE;
DROP TABLE IF EXISTS conversation_threads CASCADE;
DROP TABLE IF EXISTS daily_runs CASCADE;
DROP TABLE IF EXISTS prompts CASCADE;
DROP TABLE IF EXISTS brand CASCADE;

DROP TYPE IF EXISTS run_status;
DROP TYPE IF EXISTS mention_sentiment;
DROP TYPE IF EXISTS recommendation_strength;
DROP TYPE IF EXISTS message_role;
