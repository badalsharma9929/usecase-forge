"""Vercel Queues consumer: runs one agent step per message, then enqueues the next.

Registered in pyproject.toml under [[tool.vercel.subscribers]]. Vercel builds it into a
private, queue-triggered function with no public URL.
"""

from __future__ import annotations

import asyncio

from vercel.queue import Message, RetryAfter, send, subscribe

from usecase_forge.runs import TransientError
from usecase_forge.web import TOPIC, get_service


@subscribe(topic=TOPIC)
async def process_step(message: Message[dict[str, object]]) -> None:
    service = get_service()
    try:
        follow = await asyncio.to_thread(service.execute, message.payload, message.metadata.delivery_count)
    except TransientError as exc:
        raise RetryAfter(exc.delay) from exc
    if follow:
        await send(TOPIC, follow)
