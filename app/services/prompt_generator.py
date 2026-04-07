import json

import httpx
from openai import AsyncOpenAI

from app.config import settings
from app.database import supabase

client = AsyncOpenAI(api_key=settings.openai_api_key)


async def fetch_website_text(url: str) -> str:
    """Fetch the homepage text content of a website."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as http:
        resp = await http.get(url)
        resp.raise_for_status()
    # Return raw HTML — the LLM is good enough to extract meaning from it.
    # Truncate to ~12k chars to stay within prompt limits.
    return resp.text[:12000]


COUNTRY_NAMES = {"IN": "India", "DE": "Germany", "US": "United States"}


async def analyze_brand_and_generate_prompts(website: str, country: str | None = None) -> dict:
    """Analyze a brand website and return brand info + 5 prompts.

    Returns dict with keys: name, description, category, prompts
    """
    html_snippet = await fetch_website_text(website)

    prompt = f"""You are analyzing a brand's website to understand what they sell and generate search queries.

Website URL: {website}

Here is a snippet of the website's HTML content:
---
{html_snippet}
---

Based on this website, return a JSON object with:
1. "name": the brand name
2. "description": a 1-2 sentence description of what they sell/do
3. "category": the product/service category (e.g., "laptops", "running shoes", "project management software")
4. "prompts": an array of exactly 5 detailed buyer questions that someone would type into ChatGPT when seriously researching a purchase in this category. These questions should:
   - NOT mention the brand name at all
   - Be specific and detailed enough that an AI assistant would naturally respond with brand names, product recommendations, and comparisons
   - Explicitly ask for brand recommendations, top picks, or head-to-head comparisons — vague questions like "what are the best dresses?" are useless because they don't elicit brand names
   - Each question should be 1-2 sentences long and include context about the buyer's needs, budget, or use case
   - Cover these 5 angles (one question per angle):
     1. "top_picks": Ask for the top 5-10 brands/products for a specific use case (e.g., "What are the top 5 laptop brands for video editing under $1500, and what makes each one stand out?")
     2. "budget": Ask for affordable brand recommendations with a price constraint (e.g., "Which running shoe brands offer the best value under $100 for someone training for their first marathon?")
     3. "comparison": Ask for a direct comparison between types/categories of products (e.g., "How do ultrabook laptops compare to gaming laptops for a computer science student who also games on weekends?")
     4. "specific_need": Ask about brands that solve a very specific problem (e.g., "I have flat feet and need running shoes with strong arch support — which brands should I look at and why?")
     5. "switching": Ask from the perspective of someone considering switching from a competitor or upgrading (e.g., "I've been using budget running shoes but want to upgrade to something more serious — what brands should I consider and what's the difference?")
   - Each question should have a "question_text" and a "category_context" matching the angle name above
"""

    if country and country != "US":
        country_name = COUNTRY_NAMES.get(country, country)
        prompt += f"""
The buyer is located in {country_name}. Add "in {country_name}" to every question UNLESS it truly makes no sense (e.g., a question purely about fabric properties or technical specs). When in doubt, include the country.
"""

    prompt += "\nReturn ONLY valid JSON."

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        response_format={"type": "json_object"},
    )

    return json.loads(response.choices[0].message.content)


async def setup_brand(website: str, country: str | None = None) -> dict:
    """One-shot setup: create brand + generate seed questions. Returns brand with seeds."""
    # Check if a brand already exists
    existing = supabase.table("brand").select("*").execute().data
    if existing:
        # Delete existing brand (cascades to everything)
        supabase.table("brand").delete().eq("id", existing[0]["id"]).execute()

    # Analyze website and generate prompts
    result = await analyze_brand_and_generate_prompts(website, country=country)

    # Insert brand
    brand_row = supabase.table("brand").insert({
        "name": result["name"],
        "website": website,
        "description": result.get("description"),
        "category": result.get("category"),
        "country": country,
    }).execute().data[0]

    # Insert prompts
    prompts = []
    for p in result.get("prompts", []):
        row = supabase.table("prompts").insert({
            "brand_id": brand_row["id"],
            "question_text": p["question_text"],
            "category_context": p.get("category_context"),
        }).execute().data[0]
        prompts.append(row)

    brand_row["prompts"] = prompts
    return brand_row
