from datetime import date, datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, HttpUrl


# --- Enums ---

class RunStatus(str, Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"


class Sentiment(str, Enum):
    positive = "positive"
    neutral = "neutral"
    negative = "negative"


class RecommendationStrength(str, Enum):
    strong_recommend = "strong_recommend"
    recommend = "recommend"
    mentioned = "mentioned"
    compared_unfavorably = "compared_unfavorably"
    not_mentioned = "not_mentioned"


# --- Request models ---

class SetupRequest(BaseModel):
    website: str
    country: str | None = None


# --- Response models ---

class Prompt(BaseModel):
    id: UUID
    question_text: str
    category_context: str | None = None
    is_active: bool = True


class BrandResponse(BaseModel):
    id: UUID
    name: str
    website: str
    description: str | None = None
    category: str | None = None
    country: str | None = None
    created_at: datetime
    prompts: list[Prompt] = []


class SetupResponse(BaseModel):
    brand: BrandResponse
    message: str


class RunSummary(BaseModel):
    run_id: UUID
    run_date: date
    status: RunStatus
    total_messages_analyzed: int
    total_mentions: int
    target_brand_mentions: int


class SimulateResponse(BaseModel):
    run: RunSummary
    message: str


class BackfillResponse(BaseModel):
    runs: list[RunSummary]
    message: str


class CompetitorBreakdown(BaseModel):
    competitor_name: str
    appearance_count: int
    mention_rate: float
    avg_position: float | None = None
    avg_sentiment: float | None = None


class TrendPoint(BaseModel):
    run_date: date
    mention_rate: float
    avg_position: float | None = None
    avg_sentiment: float | None = None
    response_count: int


class LatestRunDetail(BaseModel):
    run_id: UUID
    run_date: date
    status: RunStatus
    total_responses: int
    target_mentions: int
    mention_rate: float
    avg_position: float | None = None
    avg_sentiment: float | None = None


class DashboardResponse(BaseModel):
    brand_name: str
    visibility_score: float
    mention_rate: float
    avg_position: float | None = None
    avg_sentiment: float | None = None
    competitors: list[CompetitorBreakdown]
    trends: list[TrendPoint]
    latest_run: LatestRunDetail | None = None
    total_runs: int


# --- Conversation detail models ---

class MentionInMessage(BaseModel):
    brand_name: str
    is_target_brand: bool
    sentiment: str
    recommendation_strength: str
    context_snippet: str | None = None


class ConversationThread(BaseModel):
    seed_question: str
    response_content: str
    mentions: list[MentionInMessage] = []
    mention_count: int = 0
    dominant_sentiment: str | None = None
    best_strength: str | None = None


class ConversationsResponse(BaseModel):
    run_date: date | None = None
    threads: list[ConversationThread]
