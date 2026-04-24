import asyncio
import time
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException

from app.database import supabase
from app.models import (
    BackfillResponse,
    BrandResponse,
    ConversationsResponse,
    ConversationThread,
    DashboardResponse,
    MentionInMessage,
    RunSummary,
    Prompt,
    SetupRequest,
    SetupResponse,
    SimulateResponse,
)
from app.services.analyzer import analyze_all_messages, aggregate_competitor_appearances
from app.services.conversation import run_conversation, run_conversation_historical
from app.services.scoring import get_dashboard
from app.services.prompt_generator import setup_brand

router = APIRouter()


@router.post("/api/setup", response_model=SetupResponse)
async def setup(req: SetupRequest):
    """One-shot: create brand from website + generate 50 prompts."""
    try:
        brand_data = await setup_brand(req.website, country=req.country)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Setup failed: {e}")

    prompts = [Prompt(**p) for p in brand_data.get("prompts", [])]

    return SetupResponse(
        brand=BrandResponse(
            id=brand_data["id"],
            name=brand_data["name"],
            website=brand_data["website"],
            description=brand_data.get("description"),
            category=brand_data.get("category"),
            country=brand_data.get("country"),
            created_at=brand_data["created_at"],
            prompts=prompts,
        ),
        message=f"Brand '{brand_data['name']}' created with {len(prompts)} prompts.",
    )


@router.get("/api/brand", response_model=BrandResponse)
async def get_brand():
    """Get the current brand and its prompts."""
    brands = supabase.table("brand").select("*").execute().data
    if not brands:
        raise HTTPException(status_code=404, detail="No brand configured. POST /api/setup first.")

    brand = brands[0]
    prompts = (
        supabase.table("prompts")
        .select("*")
        .eq("brand_id", brand["id"])
        .eq("is_active", True)
        .order("created_at")
        .execute()
        .data
    )

    return BrandResponse(
        id=brand["id"],
        name=brand["name"],
        website=brand["website"],
        description=brand.get("description"),
        category=brand.get("category"),
        country=brand.get("country"),
        created_at=brand["created_at"],
        prompts=[Prompt(**p) for p in prompts],
    )


async def _run_simulation(brand: dict, prompts: list[dict],
                          user_location: dict | None,
                          run_date: date,
                          historical: bool = False) -> RunSummary:
    """Core simulation logic shared by simulate() and backfill().

    Creates a daily_run, runs all conversations (parallelised with Semaphore(5)),
    analyses responses, aggregates competitors, and returns a RunSummary.
    """
    run_date_str = run_date.isoformat()
    run = supabase.table("daily_runs").insert({
        "brand_id": brand["id"],
        "run_date": run_date_str,
        "status": "pending",
        "started_at": datetime.utcnow().isoformat(),
    }).execute().data[0]

    try:
        sem = asyncio.Semaphore(5)

        async def _run_one(i, prompt):
            t0 = time.perf_counter()
            async with sem:
                if historical:
                    result = await run_conversation_historical(
                        run_id=run["id"],
                        prompt_id=prompt["id"],
                        question_text=prompt["question_text"],
                        end_date=run_date_str,
                        user_location=user_location,
                    )
                else:
                    result = await run_conversation(
                        run_id=run["id"],
                        prompt_id=prompt["id"],
                        question_text=prompt["question_text"],
                        user_location=user_location,
                    )
                print(f"[{run_date_str} conversation {i+1}/{len(prompts)}] done in {time.perf_counter() - t0:.1f}s")
                return result

        t_conv = time.perf_counter()
        all_responses = await asyncio.gather(*[_run_one(i, p) for i, p in enumerate(prompts)])
        print(f"[{run_date_str}] all {len(all_responses)} conversations done in {time.perf_counter() - t_conv:.1f}s")

        t_analysis = time.perf_counter()
        all_mentions = await analyze_all_messages(
            all_responses, brand["name"], run["id"]
        )
        print(f"[{run_date_str}] all {len(all_responses)} analyses done in {time.perf_counter() - t_analysis:.1f}s")

        aggregate_competitor_appearances(run["id"])
        print(f"[{run_date_str}] total wall time: {time.perf_counter() - t_conv:.1f}s")

        supabase.table("daily_runs").update({
            "status": "completed",
            "completed_at": datetime.utcnow().isoformat(),
        }).eq("id", run["id"]).execute()

        target_mentions = [m for m in all_mentions if m.get("is_target_brand")]

        return RunSummary(
            run_id=run["id"],
            run_date=run_date_str,
            status="completed",
            total_messages_analyzed=len(all_responses),
            total_mentions=len(all_mentions),
            target_brand_mentions=len(target_mentions),
        )

    except Exception as e:
        supabase.table("daily_runs").update({
            "status": "failed",
            "completed_at": datetime.utcnow().isoformat(),
            "error_message": str(e),
        }).eq("id", run["id"]).execute()
        raise


@router.post("/api/simulate", response_model=SimulateResponse)
async def simulate():
    """Run a daily simulation: one question/answer per prompt."""
    brands = supabase.table("brand").select("*").execute().data
    if not brands:
        raise HTTPException(status_code=404, detail="No brand configured. POST /api/setup first.")
    brand = brands[0]

    prompts = (
        supabase.table("prompts")
        .select("*")
        .eq("brand_id", brand["id"])
        .eq("is_active", True)
        .execute()
        .data
    )
    if not prompts:
        raise HTTPException(status_code=400, detail="No active prompts.")

    user_location = None
    if brand.get("country"):
        user_location = {"type": "approximate", "country": brand["country"]}

    try:
        summary = await _run_simulation(brand, prompts, user_location, date.today())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Simulation failed: {e}")

    return SimulateResponse(
        run=summary,
        message=f"Simulation complete: {summary.total_messages_analyzed} responses analyzed, {summary.target_brand_mentions} target brand mentions found.",
    )


@router.post("/api/simulate/backfill", response_model=BackfillResponse)
async def simulate_backfill():
    """Run simulations for the last 7 days using historical web search."""
    brands = supabase.table("brand").select("*").execute().data
    if not brands:
        raise HTTPException(status_code=404, detail="No brand configured. POST /api/setup first.")
    brand = brands[0]

    prompts = (
        supabase.table("prompts")
        .select("*")
        .eq("brand_id", brand["id"])
        .eq("is_active", True)
        .execute()
        .data
    )
    if not prompts:
        raise HTTPException(status_code=400, detail="No active prompts.")

    user_location = None
    if brand.get("country"):
        user_location = {"type": "approximate", "country": brand["country"]}

    today = date.today()
    summaries: list[RunSummary] = []

    try:
        for days_ago in range(7, 0, -1):
            run_date = today - timedelta(days=days_ago)
            print(f"\n=== Backfill: starting simulation for {run_date} ===")
            summary = await _run_simulation(
                brand, prompts, user_location, run_date, historical=True,
            )
            summaries.append(summary)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Backfill failed on day {run_date}: {e}. {len(summaries)} days completed before failure.",
        )

    return BackfillResponse(
        runs=summaries,
        message=f"Backfill complete: {len(summaries)} daily simulations created.",
    )


@router.get("/api/conversations", response_model=ConversationsResponse)
async def conversations():
    """Get conversations from the latest completed run."""
    brands = supabase.table("brand").select("id").execute().data
    if not brands:
        raise HTTPException(status_code=404, detail="No brand configured.")

    # Get latest completed run
    runs = (
        supabase.table("daily_runs")
        .select("id, run_date")
        .eq("brand_id", brands[0]["id"])
        .eq("status", "completed")
        .order("run_date", desc=True)
        .limit(1)
        .execute()
        .data
    )
    if not runs:
        return ConversationsResponse(threads=[])

    run = runs[0]

    # Get all responses for this run
    responses = (
        supabase.table("responses")
        .select("id, prompt_id, content")
        .eq("run_id", run["id"])
        .order("created_at")
        .execute()
        .data
    )

    # Get prompt texts
    prompt_ids = list({r["prompt_id"] for r in responses})
    prompt_rows = (
        supabase.table("prompts")
        .select("id, question_text")
        .in_("id", prompt_ids)
        .execute()
        .data
    )
    prompt_text = {p["id"]: p["question_text"] for p in prompt_rows}

    # Get all mentions for this run, keyed by response_id
    mentions = (
        supabase.table("brand_mentions")
        .select("response_id, brand_name, is_target_brand, sentiment, recommendation_strength, context_snippet")
        .eq("run_id", run["id"])
        .execute()
        .data
    )
    mentions_by_resp: dict[str, list] = {}
    for m in mentions:
        mentions_by_resp.setdefault(m["response_id"], []).append(m)

    # Build threads (one per response)
    strength_rank = {
        "strong_recommend": 4,
        "recommend": 3,
        "mentioned": 2,
        "compared_unfavorably": 1,
        "not_mentioned": 0,
    }

    result_threads = []
    for r in responses:
        resp_mentions = [
            MentionInMessage(
                brand_name=m["brand_name"],
                is_target_brand=m["is_target_brand"],
                sentiment=m["sentiment"],
                recommendation_strength=m["recommendation_strength"],
                context_snippet=m.get("context_snippet"),
            )
            for m in mentions_by_resp.get(r["id"], [])
        ]

        target = [m for m in resp_mentions if m.is_target_brand]
        mention_count = 1 if target else 0
        sentiments = [m.sentiment for m in target]
        dominant_sentiment = max(set(sentiments), key=sentiments.count) if sentiments else None
        best_strength_val = 0
        best_strength_name: str | None = None
        for m in target:
            rank = strength_rank.get(m.recommendation_strength, 0)
            if rank > best_strength_val:
                best_strength_val = rank
                best_strength_name = m.recommendation_strength

        result_threads.append(ConversationThread(
            seed_question=prompt_text.get(r["prompt_id"], "Unknown"),
            response_content=r["content"],
            mentions=resp_mentions,
            mention_count=mention_count,
            dominant_sentiment=dominant_sentiment,
            best_strength=best_strength_name,
        ))

    return ConversationsResponse(run_date=run["run_date"], threads=result_threads)


@router.delete("/api/reset")
async def reset():
    """Delete the brand and all associated data (cascades)."""
    brands = supabase.table("brand").select("id").execute().data
    if not brands:
        raise HTTPException(status_code=404, detail="No brand configured.")

    supabase.table("brand").delete().eq("id", brands[0]["id"]).execute()
    return {"message": "All data cleared."}


@router.get("/api/dashboard", response_model=DashboardResponse)
async def dashboard():
    """Full dashboard: visibility score, competitors, trends, latest run."""
    brands = supabase.table("brand").select("id").execute().data
    if not brands:
        raise HTTPException(status_code=404, detail="No brand configured. POST /api/setup first.")

    try:
        return get_dashboard(brands[0]["id"])
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
