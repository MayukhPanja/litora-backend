import time

from openai import AsyncOpenAI

from app.config import settings
from app.database import supabase

client = AsyncOpenAI(api_key=settings.openai_api_key)


async def _chat(messages: list[dict], temperature: float = 0.7,
                response_format: dict | None = None,
                web_search: bool = False,
                user_location: dict | None = None) -> dict:
    """Send messages to OpenAI and return content + usage metadata.

    When web_search=True, uses the Responses API with web_search_preview
    so the model can fetch current information from the web.
    """
    start = time.perf_counter()

    if web_search:
        search_tool: dict = {"type": "web_search_preview"}
        if user_location:
            search_tool["user_location"] = user_location
        print(f"_chat: web_search=True, search_tool={search_tool}")
        response = await client.responses.create(
            model=settings.openai_model,
            input=messages,
            tools=[search_tool],
            temperature=temperature,
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        tokens = response.usage.total_tokens if response.usage else None
        print(f"_chat: done in {latency_ms}ms, model={response.model}, tokens={tokens}")
        return {
            "content": response.output_text,
            "model_used": response.model,
            "tokens_used": tokens,
            "latency_ms": latency_ms,
        }

    print(f"_chat: regular chat completion (no web search)")
    kwargs: dict = {
        "model": settings.openai_model,
        "messages": messages,
        "temperature": temperature,
    }
    if response_format:
        kwargs["response_format"] = response_format
    response = await client.chat.completions.create(**kwargs)
    latency_ms = int((time.perf_counter() - start) * 1000)
    choice = response.choices[0]
    tokens = response.usage.total_tokens if response.usage else None
    print(f"_chat: done in {latency_ms}ms, model={response.model}, tokens={tokens}")
    return {
        "content": choice.message.content,
        "model_used": response.model,
        "tokens_used": tokens,
        "latency_ms": latency_ms,
    }


async def _chat_historical(messages: list[dict], end_date: str,
                           temperature: float = 0.7,
                           user_location: dict | None = None) -> dict:
    """Like _chat with web search, but restricts results to before end_date.

    Uses the Responses API web_search_preview with a date filter so the model
    only sees web content published on or before the given date.

    Args:
        end_date: ISO date string, e.g. "2022-03-01".
    """
    system_msg = {
        "role": "system",
        "content": (
            f"Assume today's date is {end_date}. "
            "Do not reference or use any information published after this date."
        ),
    }
    search_tool: dict = {
        "type": "web_search_preview",
        "search_context_size": "medium",
        "filters": {"end_date": end_date},
    }
    if user_location:
        search_tool["user_location"] = user_location
    print(f"_chat_historical: end_date={end_date}, search_tool={search_tool}")
    start = time.perf_counter()
    response = await client.responses.create(
        model=settings.openai_model,
        input=[system_msg] + messages,
        tools=[search_tool],
        temperature=temperature,
    )
    latency_ms = int((time.perf_counter() - start) * 1000)
    tokens = response.usage.total_tokens if response.usage else None
    print(f"_chat_historical: done in {latency_ms}ms, model={response.model}, tokens={tokens}")
    return {
        "content": response.output_text,
        "model_used": response.model,
        "tokens_used": tokens,
        "latency_ms": latency_ms,
    }


async def run_conversation(run_id: str, prompt_id: str, question_text: str,
                           user_location: dict | None = None) -> dict:
    """Run a single prompt, store the response, and return the responses row."""
    print(f"\n--- run_conversation ---")
    print(f"question: {question_text[:80]}...")
    print(f"user_location: {user_location}")

    result = await _chat(
        [{"role": "user", "content": question_text}],
        web_search=True,
        user_location=user_location,
    )

    row = {
        "run_id": run_id,
        "prompt_id": prompt_id,
        "content": result["content"],
    }
    if result.get("model_used"):
        row["model_used"] = result["model_used"]
    if result.get("tokens_used") is not None:
        row["tokens_used"] = result["tokens_used"]
    if result.get("latency_ms") is not None:
        row["latency_ms"] = result["latency_ms"]

    response_row = supabase.table("responses").insert(row).execute().data[0]
    print(f"done\n")
    return response_row
