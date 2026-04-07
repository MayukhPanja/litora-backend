from app.database import supabase
from app.models import (
    CompetitorBreakdown,
    DashboardResponse,
    LatestRunDetail,
    TrendPoint,
)

SENTIMENT_MAP = {"positive": 1.0, "neutral": 0.0, "negative": -1.0}


def get_dashboard(brand_id: str) -> DashboardResponse:
    """Build the full dashboard response for a brand."""
    brand = supabase.table("brand").select("*").eq("id", brand_id).execute().data
    if not brand:
        raise ValueError("Brand not found")
    brand = brand[0]

    # Get all completed runs ordered by date
    runs = (
        supabase.table("daily_runs")
        .select("*")
        .eq("brand_id", brand_id)
        .eq("status", "completed")
        .order("run_date")
        .execute()
        .data
    )

    if not runs:
        return DashboardResponse(
            brand_name=brand["name"],
            visibility_score=0.0,
            mention_rate=0.0,
            competitors=[],
            trends=[],
            total_runs=0,
        )

    # Build trends from all runs
    trends = []
    for run in runs:
        run_id = run["id"]

        # Count responses for this run
        resp_rows = (
            supabase.table("responses")
            .select("id")
            .eq("run_id", run_id)
            .execute()
            .data
        )
        response_count = len(resp_rows)

        # Get target brand mentions
        target_mentions = (
            supabase.table("brand_mentions")
            .select("mention_position, sentiment, recommendation_strength")
            .eq("run_id", run_id)
            .eq("is_target_brand", True)
            .execute()
            .data
        )

        found = [m for m in target_mentions if m["recommendation_strength"] != "not_mentioned"]
        positions = [m["mention_position"] for m in found if m.get("mention_position")]
        sentiments = [SENTIMENT_MAP.get(m["sentiment"], 0.0) for m in found]

        mention_rate = len(found) / response_count if response_count else 0.0

        trends.append(TrendPoint(
            run_date=run["run_date"],
            mention_rate=round(mention_rate, 4),
            avg_position=round(sum(positions) / len(positions), 2) if positions else None,
            avg_sentiment=round(sum(sentiments) / len(sentiments), 2) if sentiments else None,
            response_count=response_count,
        ))

    # Latest run details
    latest_run = runs[-1]
    latest_trend = trends[-1] if trends else None

    latest_run_detail = None
    if latest_trend:
        latest_mentions = (
            supabase.table("brand_mentions")
            .select("id")
            .eq("run_id", latest_run["id"])
            .eq("is_target_brand", True)
            .execute()
            .data
        )
        latest_run_detail = LatestRunDetail(
            run_id=latest_run["id"],
            run_date=latest_run["run_date"],
            status=latest_run["status"],
            total_responses=latest_trend.response_count,
            target_mentions=len(latest_mentions),
            mention_rate=latest_trend.mention_rate,
            avg_position=latest_trend.avg_position,
            avg_sentiment=latest_trend.avg_sentiment,
        )

    # Competitors from latest run
    appearances = (
        supabase.table("competitor_appearances")
        .select("*")
        .eq("run_id", latest_run["id"])
        .execute()
        .data
    )

    total_responses = latest_trend.response_count if latest_trend else 0
    competitors = []
    for a in appearances:
        competitors.append(CompetitorBreakdown(
            competitor_name=a["competitor_name"],
            appearance_count=a["appearance_count"],
            mention_rate=round(a["appearance_count"] / total_responses, 4) if total_responses else 0.0,
            avg_position=a.get("avg_position"),
            avg_sentiment=a.get("avg_sentiment"),
        ))
    competitors.sort(key=lambda x: x.appearance_count, reverse=True)

    # Visibility score: weighted combination of mention rate, position, sentiment
    # Score = mention_rate * 40 + position_score * 30 + sentiment_score * 30
    # If never mentioned, position and sentiment are meaningless → score is 0.
    mr = latest_trend.mention_rate if latest_trend else 0.0
    has_mentions = mr > 0
    pos = latest_trend.avg_position if latest_trend and latest_trend.avg_position else 5.0
    sent = latest_trend.avg_sentiment if latest_trend and latest_trend.avg_sentiment else 0.0

    position_score = max(0, 1 - (pos - 1) / 9) if has_mentions else 0.0
    sentiment_score = ((sent + 1) / 2) if has_mentions else 0.0
    visibility_score = round(mr * 40 + position_score * 30 + sentiment_score * 30, 2)

    return DashboardResponse(
        brand_name=brand["name"],
        visibility_score=visibility_score,
        mention_rate=mr,
        avg_position=latest_trend.avg_position if latest_trend else None,
        avg_sentiment=latest_trend.avg_sentiment if latest_trend else None,
        competitors=competitors,
        trends=trends,
        latest_run=latest_run_detail,
        total_runs=len(runs),
    )
