"""Day 1 spike: proves durable steps, parallel fan-out and a Token Factory call.

Trigger from the Inngest dev UI or:
    curl -X POST http://localhost:8288/e/dev -d '{"name":"bridge/smoke.requested","data":{}}'
"""

import inngest

from app.core.config import get_settings
from app.providers.base import get_llm_provider
from app.schemas.chat import ChatMessage
from app.workflows.client import inngest_client


async def _ask(prompt: str) -> str:
    provider = get_llm_provider(get_settings())
    message, _model = await provider.complete([ChatMessage(role="user", content=prompt)])
    return message.content.strip()


@inngest_client.create_function(
    fn_id="smoke-run",
    trigger=inngest.TriggerEvent(event="bridge/smoke.requested"),
)
async def smoke_run(ctx: inngest.Context) -> dict[str, str]:
    topic = str(ctx.event.data.get("topic", "bank reconciliation"))

    async def plan() -> str:
        return await _ask(f"In one sentence, plan how to check '{topic}'.")

    async def agent_a() -> str:
        return await _ask("Reply with exactly: agent-a-ok")

    async def agent_b() -> str:
        return await _ask("Reply with exactly: agent-b-ok")

    plan_out = await ctx.step.run("plan", plan)
    a_out, b_out = await ctx.group.parallel(
        (
            lambda: ctx.step.run("agent-a", agent_a),
            lambda: ctx.step.run("agent-b", agent_b),
        )
    )

    async def synthesize() -> str:
        return await _ask(f"Summarize in one line: {plan_out} | {a_out} | {b_out}")

    summary = await ctx.step.run("synthesize", synthesize)
    return {"plan": plan_out, "a": a_out, "b": b_out, "summary": summary}
