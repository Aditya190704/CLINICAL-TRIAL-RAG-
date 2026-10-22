"""Small, request-scoped ADK runner with bounded time and no persistence."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import TypeVar

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google import genai
from google.genai import types
from pydantic import BaseModel

from app.config import settings

T = TypeVar("T", bound=BaseModel)

# ADK and model SDK debug output may include prompts, tool payloads, or responses.
logging.getLogger("google.adk").setLevel(logging.CRITICAL)
logging.getLogger("google.genai").setLevel(logging.CRITICAL)
logging.getLogger("google.cloud").setLevel(logging.CRITICAL)
logging.getLogger("google.api_core").setLevel(logging.CRITICAL)


async def run_structured_agent(
    *,
    name: str,
    instruction: str,
    data: dict[str, object],
    output_schema: type[T],
) -> T:
    """Run one stateless task agent; delete its in-memory session on all paths."""
    client = genai.Client(
        enterprise=True,
        project=settings.gcp_project,
        location=settings.gemini_location,
        http_options=types.HttpOptions(
            timeout=max(1, round(settings.adk_timeout_seconds * 1000))
        ),
    )
    app_name = settings.adk_app_name
    user_id = "request"
    session_id = str(uuid.uuid4())
    session_created = False
    service: InMemorySessionService | None = None
    try:
        service = InMemorySessionService()
        model = Gemini(model=settings.gemini_model, client=client)
        agent = LlmAgent(
            name=name,
            model=model,
            instruction=instruction,
            output_schema=output_schema,
            timeout=settings.adk_timeout_seconds,
            include_contents="default",
        )
        await service.create_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
        )
        session_created = True
        runner = Runner(
            app_name=app_name,
            agent=agent,
            session_service=service,
        )

        # The user payload is JSON data, never instruction text. It cannot
        # alter the system instruction or grant the agent tools.
        message = types.Content(
            role="user",
            parts=[types.Part(text="UNTRUSTED INPUT JSON:\n" + json.dumps(data, ensure_ascii=False))],
        )

        async def collect() -> str:
            final_text = ""
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=message,
            ):
                if event.is_final_response() and event.content:
                    final_text = "".join(
                        part.text or ""
                        for part in event.content.parts or []
                        if part.text is not None
                    )
            if not final_text:
                raise ValueError("Structured agent response was empty.")
            return final_text

        raw = await asyncio.wait_for(
            collect(),
            timeout=settings.adk_timeout_seconds,
        )
        return output_schema.model_validate_json(raw)
    finally:
        try:
            if session_created and service is not None:
                await service.delete_session(
                    app_name=app_name,
                    user_id=user_id,
                    session_id=session_id,
                )
        finally:
            try:
                await client.aio.aclose()
            finally:
                client.close()

