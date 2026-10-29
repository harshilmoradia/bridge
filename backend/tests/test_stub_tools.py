from app.providers.base import Completion, ToolCall
from app.providers.stub import StubProvider
from app.schemas.chat import ChatMessage

MSGS = [ChatMessage(role="user", content="resolve BANK019")]
TOOLS = [{"type": "function", "function": {"name": "find_rules", "parameters": {}}}]


async def test_stub_records_tools_and_scripts_tool_calls() -> None:
    call = ToolCall(id="c1", name="find_rules", arguments='{"description": "FEE"}')
    stub = StubProvider(
        responder=lambda *_: Completion(content="", model="m-super", tool_calls=(call,))
    )
    result = await stub.generate(MSGS, "m-super", tools=TOOLS)
    assert result.tool_calls == (call,)
    assert result.model == "m-super"
    assert stub.tools_seen == [TOOLS]
    assert stub.calls == [("m-super", False)]


async def test_stub_text_reply_has_no_tool_calls() -> None:
    stub = StubProvider()
    result = await stub.generate(MSGS)
    assert result.content == "Stub response to: resolve BANK019"
    assert result.tool_calls == ()
    assert stub.tools_seen == [None]
