import asyncio
from datetime import date

from pydantic import ValidationError
import app.services.agent as agent_service

from langchain.agents import create_agent
from app.api.agent import _conversation_title, _stored_context
from app.models import AgentConversation
from app.schemas.agent import AgentChatRequest, AgentMessage
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.tools import tool

from app.services.agent import (
    SYSTEM_PROMPT,
    _build_tools,
    _code_interpreter_middleware,
    _compact_context,
    _message_content,
    _looks_like_unfinished_answer,
    _provider_hints,
    _runtime_system_prompt,
    _tool_complete_event,
    _tool_start_event,
    stream_chat,
)


class ToolCallingFakeModel(FakeMessagesListChatModel):
    def bind_tools(self, _tools, **_kwargs):
        return self


def test_chat_request_requires_user_as_last_message() -> None:
    try:
        AgentChatRequest(messages=[AgentMessage(role="assistant", content="Done")])
    except ValidationError:
        return
    raise AssertionError("assistant-only chat history should be rejected")


def test_chat_request_strips_message_content() -> None:
    request = AgentChatRequest(messages=[AgentMessage(role="user", content="  Hello  ")])

    assert request.messages[0].content == "Hello"


def test_message_replacement_requires_existing_conversation() -> None:
    try:
        AgentChatRequest(
            messages=[AgentMessage(role="user", content="Edited question")],
            replace_message_id=42,
        )
    except ValidationError:
        return
    raise AssertionError("message replacement without a conversation should be rejected")


def test_message_replacement_accepts_conversation_and_message_ids() -> None:
    request = AgentChatRequest(
        messages=[AgentMessage(role="user", content="Edited question")],
        conversation_id=7,
        replace_message_id=42,
    )

    assert request.conversation_id == 7
    assert request.replace_message_id == 42


def test_conversation_title_is_compact_and_word_safe() -> None:
    title = _conversation_title(
        "  Please   summarize my very detailed financial activity for the current month  ",
        max_length=42,
    )

    assert title == "Please summarize my very detailed…"
    assert len(title) <= 42


def test_stored_context_ignores_invalid_entries() -> None:
    from app.services import crypto
    from app.services.secure_repository import sealed_conversation_values

    dek = crypto.new_dek()
    sealed = sealed_conversation_values(
        dek=dek,
        record_id=1,
        title="Test",
        context=[
            {"role": "summary", "content": "Previous context"},
            {"role": "invalid", "content": "Do not use"},
            {"missing": "role"},
        ],
    )
    conversation = AgentConversation(
        id=1,
        encrypted_payload=sealed["encrypted_payload"],
    )

    context = _stored_context(conversation, dek)

    assert context == [AgentMessage(role="summary", content="Previous context")]


def test_extracts_text_from_ollama_content_blocks() -> None:
    class Message:
        content = [
            {"type": "text", "text": "First sentence."},
            {"type": "text", "text": "Second sentence."},
        ]

    assert _message_content(Message()) == "First sentence.\nSecond sentence."


def test_agent_prompt_forbids_claiming_changes() -> None:
    assert "read-only" in SYSTEM_PROMPT
    assert "cannot change" in SYSTEM_PROMPT


def test_agent_prompt_requires_isolated_code_for_derived_numbers() -> None:
    assert "`code_interpreter`" in SYSTEM_PROMPT
    assert "Never calculate in the language model" in SYSTEM_PROMPT
    assert "integer cents with `BigInt`" in SYSTEM_PROMPT
    assert "currency" in SYSTEM_PROMPT
    assert "never mix currencies" in SYSTEM_PROMPT


def test_code_interpreter_has_specific_activity_events() -> None:
    assert _tool_start_event("code_interpreter") == {
        "type": "activity",
        "code": "calculation_running",
    }
    assert _tool_complete_event(
        ToolMessage(
            content="<result>6251.08</result>",
            tool_call_id="calculation-1",
            name="code_interpreter",
        )
    ) == {"type": "activity", "code": "calculation_finished"}


def _invoke_interpreter(code: str) -> str:
    model = ToolCallingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "code_interpreter",
                        "args": {"code": code},
                        "id": "interpreter-test",
                    }
                ],
            ),
            AIMessage(content="Done"),
        ]
    )
    graph = create_agent(model, tools=[], middleware=[_code_interpreter_middleware()])
    result = graph.invoke({"messages": [HumanMessage(content="Calculate this exactly.")]})
    tool_message = next(
        message for message in result["messages"] if isinstance(message, ToolMessage)
    )
    return str(tool_message.content)


def _ainvoke_interpreter_with_tools(code: str, exposed_tools: list) -> str:
    model = ToolCallingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "code_interpreter",
                        "args": {"code": code},
                        "id": "ptc-test",
                    }
                ],
            ),
            AIMessage(content="Done"),
        ]
    )
    graph = create_agent(
        model,
        tools=exposed_tools,
        middleware=[_code_interpreter_middleware(exposed_tools)],
    )
    result = asyncio.run(
        graph.ainvoke({"messages": [HumanMessage(content="Load and calculate exactly.")]})
    )
    tool_message = next(
        message for message in result["messages"] if isinstance(message, ToolMessage)
    )
    return str(tool_message.content)


def test_code_interpreter_calculates_money_in_integer_cents() -> None:
    output = _invoke_interpreter(
        """
        const values = ["302.30", "686.75", "472.74", "1707.48", "578.03",
          "626.05", "311.80", "1565.93"];
        const total = values
          .map(value => BigInt(value.replace(".", "")))
          .reduce((sum, value) => sum + value, 0n);
        (total / 100n).toString() + "." + (total % 100n).toString().padStart(2, "0");
        """
    )

    assert "6251.08" in output


def test_code_interpreter_has_no_ambient_host_capabilities() -> None:
    output = _invoke_interpreter(
        '[typeof process, typeof fetch, typeof require].join(",");'
    )

    assert "undefined,undefined,undefined" in output


def test_programmatic_tool_calling_pages_and_aggregates_inside_quickjs() -> None:
    calls: list[int] = []

    @tool
    def list_transactions(limit: int = 2, offset: int = 0) -> dict:
        """Return a deterministic page of transactions for an integration test."""
        calls.append(offset)
        values = ["302.30", "686.75", "472.74"]
        page = values[offset : offset + limit]
        next_offset = offset + len(page)
        return {
            "results": [{"amount": value, "currency": "EUR"} for value in page],
            "has_more": next_offset < len(values),
            "next_offset": next_offset if next_offset < len(values) else None,
        }

    output = _ainvoke_interpreter_with_tools(
        """
        let offset = 0;
        let count = 0;
        let total = 0n;
        while (true) {
          const page = await tools.listTransactions({limit: 2, offset});
          for (const tx of page.results) {
            total += BigInt(tx.amount.replace('.', ''));
            count += 1;
          }
          if (!page.has_more) break;
          offset = page.next_offset;
        }
        JSON.stringify({count, total: `${total / 100n}.${(total % 100n).toString().padStart(2, '0')}`});
        """,
        [list_transactions],
    )

    assert calls == [0, 2]
    assert '"count":3' in output
    assert '"total":"1461.79"' in output


def test_programmatic_tool_calling_exposes_only_read_only_allowlist() -> None:
    @tool
    def list_accounts() -> str:
        """List accounts."""
        return "[]"

    @tool
    def delete_account() -> str:
        """Delete an account."""
        return "deleted"

    middleware = _code_interpreter_middleware([list_accounts, delete_account])

    assert [item.name for item in middleware._ptc] == ["list_accounts"]


def test_detects_announced_but_unfinished_analysis() -> None:
    unfinished = (
        "I found no matching tag. I will now run the full expense analysis."
    )
    completed = (
        "I am calculating the total. Result: two matching transactions add up to EUR 10.50."
    )

    assert _looks_like_unfinished_answer(unfinished)
    assert not _looks_like_unfinished_answer(completed)


def test_stream_continues_an_announced_analysis_without_persisting_guard_text() -> None:
    unfinished = "I will now run the full expense analysis."

    class FakeAgent:
        calls = 0

        async def astream(self, payload, **_kwargs):
            self.calls += 1
            answer = unfinished if self.calls == 1 else "The analysis is complete: EUR 10.50."
            yield "values", {"messages": [*payload["messages"], AIMessage(content=answer)]}

    fake_agent = FakeAgent()
    original = agent_service._create_agent
    agent_service._create_agent = lambda *_args, **_kwargs: fake_agent
    try:
        async def collect_events():
            return [
                event
                async for event in stream_chat(
                    object(),
                    [AgentMessage(role="user", content="Analyze Portugal")],
                    current_date=date(2026, 8, 23),
                    timezone="Europe/Lisbon",
                )
            ]

        events = asyncio.run(collect_events())
    finally:
        agent_service._create_agent = original

    assert fake_agent.calls == 2
    assert any(event == {"type": "activity", "code": "analysis_continuing"} for event in events)
    result = next(event for event in events if event["type"] == "result")
    assert result["answer"] == "The analysis is complete: EUR 10.50."
    assert [message.role for message in result["context"]] == ["user", "assistant"]
    assert all("continuation instruction" not in message.content for message in result["context"])


def test_agent_prompt_requires_broad_research_after_failed_word_search() -> None:
    assert "Never end a contextual search solely because a literal text search failed" in SYSTEM_PROMPT
    assert "without a search term" in SYSTEM_PROMPT
    assert "`next_offset`" in SYSTEM_PROMPT
    assert "selection calculation tool" in SYSTEM_PROMPT
    assert "category such as Travel" in SYSTEM_PROMPT
    assert "totals alone" in SYSTEM_PROMPT
    assert "`query`, empty `category` and no `tag_id`" in SYSTEM_PROMPT


def test_agent_prompt_documents_programmatic_tool_contract() -> None:
    assert "`listTransactions`" in SYSTEM_PROMPT
    assert "Never use underscores" in SYSTEM_PROMPT
    assert "transaction rows are in `results`" in SYSTEM_PROMPT
    assert "`offset = page.next_offset`" in SYSTEM_PROMPT
    assert "`console.log`" in SYSTEM_PROMPT


def test_agent_exposes_composable_research_tools() -> None:
    tools = _build_tools(object(), date(2026, 8, 23))
    names = {item.name for item in tools}

    assert names == {
        "search_merchant_web",
        "list_accounts",
        "list_asset_positions",
        "get_finance_summary",
        "render_chart",
        "create_tag",
        "list_tags",
        "list_transactions",
        "semantic_search_transactions",
        "hybrid_search_transactions",
        "find_similar_transactions",
        "calculate_transaction_selection",
    }
    descriptions = {item.name: item.description for item in tools}
    assert "public merchant/brand keywords" in descriptions["search_merchant_web"]
    assert "not sufficient" in descriptions["get_finance_summary"]
    assert "category and tag values are evidence" in descriptions["list_transactions"]
    assert "encrypted local embeddings" in descriptions["semantic_search_transactions"]
    assert "literal prefilter" in descriptions["hybrid_search_transactions"]


def test_agent_can_disable_public_web_search_per_request() -> None:
    tools = _build_tools(object(), date(2026, 8, 23), web_search_enabled=False)

    assert "search_merchant_web" not in {item.name for item in tools}
    assert "semantic_search_transactions" in {item.name for item in tools}


def test_provider_hints_extracts_places_without_session_material() -> None:
    hints = _provider_hints(
        {
            "merchant": {
                "name": "Pastéis de Belém",
                "merchantCity": "Lisboa",
                "merchantCountryCode": "PT",
                "mcc": 5812,
            },
            "sessionToken": "must-not-leak",
            "deviceId": "must-not-leak-either",
            "unrelated": "ignored",
        }
    )

    assert hints == {
        "merchant.name": "Pastéis de Belém",
        "merchant.merchantCity": "Lisboa",
        "merchant.merchantCountryCode": "PT",
        "merchant.mcc": "5812",
    }


def test_compact_context_keeps_summary_and_conversation_but_drops_tool_trace() -> None:
    context = _compact_context(
        [
            HumanMessage(
                content="Previous summary",
                additional_kwargs={"lc_source": "summarization"},
            ),
            HumanMessage(content="How much did I spend?"),
            AIMessage(content="", tool_calls=[{"name": "summary", "args": {}, "id": "1"}]),
            ToolMessage(content='{"expenses":"100.00"}', tool_call_id="1"),
            AIMessage(content="Your expenses were EUR 100."),
        ]
    )

    assert [message.role for message in context] == ["summary", "user", "assistant"]
    assert context[-1].content == "Your expenses were EUR 100."


def test_chat_request_allows_more_than_twelve_messages() -> None:
    messages = [
        AgentMessage(
            role="user" if index % 2 == 0 else "assistant",
            content=f"Message {index}",
        )
        for index in range(20)
    ]
    messages.append(AgentMessage(role="user", content="Current question"))

    request = AgentChatRequest(messages=messages)

    assert len(request.messages) == 21


def test_runtime_prompt_resolves_relative_finance_periods() -> None:
    prompt = _runtime_system_prompt(date(2026, 8, 23), "Europe/Lisbon")

    assert "User's local date: 2026-08-23" in prompt
    assert "Month to date: 2026-08-01 to 2026-08-23" in prompt
    assert "Previous month: 2026-07-01 to 2026-07-31" in prompt
    assert "Year to date: 2026-01-01 to 2026-08-23" in prompt
