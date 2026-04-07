import json

from openai import AsyncOpenAI

from app.config import settings
from app.database import supabase

client = AsyncOpenAI(api_key=settings.openai_api_key)


async def analyze_message(response_row: dict, target_brand: str, run_id: str) -> list[dict]:
    """Analyze a response for brand mentions, sentiment, and recommendation strength.

    Returns list of brand_mentions records inserted.
    """
    prompt = f"""Analyze this AI assistant response for brand/product/company mentions.
The target brand we are tracking is: "{target_brand}"

Response to analyze:
---
{response_row["content"]}
---

For EVERY brand, product, or company mentioned, return a JSON object with a "mentions" array.
Each mention should have:
- brand_name: exact brand/product name
- is_target_brand: true if this matches "{target_brand}" (case-insensitive, including sub-brands and abbreviations)
- mention_position: integer position (1 = first mentioned, 2 = second, etc.)
- sentiment: "positive", "neutral", or "negative"
- recommendation_strength: one of "strong_recommend", "recommend", "mentioned", "compared_unfavorably"
- context_snippet: the exact sentence where this brand appears

If no brands/products/companies are mentioned, return {{"mentions": []}}
Return ONLY valid JSON."""

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        response_format={"type": "json_object"},
    )

    parsed = json.loads(response.choices[0].message.content)
    mentions = parsed.get("mentions", [])

    records = []
    for m in mentions:
        row = supabase.table("brand_mentions").insert({
            "response_id": response_row["id"],
            "run_id": run_id,
            "brand_name": m.get("brand_name", ""),
            "is_target_brand": m.get("is_target_brand", False),
            "mention_position": m.get("mention_position"),
            "sentiment": m.get("sentiment", "neutral"),
            "recommendation_strength": m.get("recommendation_strength", "mentioned"),
            "context_snippet": m.get("context_snippet"),
        }).execute().data[0]
        records.append(row)

    return records


async def analyze_all_messages(responses: list[dict], target_brand: str, run_id: str) -> list[dict]:
    """Analyze a batch of responses and return all mention records."""
    all_mentions = []
    for resp in responses:
        mentions = await analyze_message(resp, target_brand, run_id)
        all_mentions.extend(mentions)
    return all_mentions


def aggregate_competitor_appearances(run_id: str) -> list[dict]:
    """Aggregate brand_mentions into competitor_appearances for a run.

    Groups non-target-brand mentions by competitor name and computes averages.
    """
    SENTIMENT_MAP = {"positive": 1.0, "neutral": 0.0, "negative": -1.0}

    mentions = (
        supabase.table("brand_mentions")
        .select("*")
        .eq("run_id", run_id)
        .eq("is_target_brand", False)
        .execute()
        .data
    )

    # Group by competitor name
    by_competitor: dict[str, list] = {}
    for m in mentions:
        name = m["brand_name"]
        by_competitor.setdefault(name, []).append(m)

    records = []
    for name, items in by_competitor.items():
        positions = [i["mention_position"] for i in items if i.get("mention_position")]
        sentiments = [SENTIMENT_MAP.get(i["sentiment"], 0.0) for i in items]

        row = supabase.table("competitor_appearances").insert({
            "run_id": run_id,
            "competitor_name": name,
            "appearance_count": len(items),
            "avg_position": round(sum(positions) / len(positions), 2) if positions else None,
            "avg_sentiment": round(sum(sentiments) / len(sentiments), 2) if sentiments else None,
        }).execute().data[0]
        records.append(row)

    return records
