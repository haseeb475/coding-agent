"""End-to-end: the conversational agent loop against the fake OpenAI-compatible server."""

from agent.agent import handle_message_streaming, init_conversation


def _run(messages, workspace, mode="debug"):
    return list(handle_message_streaming(
        user_message="What files are here?", messages=messages, workspace=workspace,
        composer_mode=mode, stream=False,
    ))


def test_tool_round_then_answer(server, tmp_path):
    (tmp_path / "hello.py").write_text("print('hi')\n")
    server.script.extend([
        {"content": None, "tool_calls": [{"name": "list_files", "arguments": {}}]},
        {"content": "There is one file: hello.py"},
    ])
    messages = init_conversation(tmp_path, build_rag=False)
    events = _run(messages, tmp_path)

    tool_events = [e for e in events if e["type"] == "tool_call"]
    assert tool_events and tool_events[0]["tool"] == "list_files"
    assert "hello.py" in tool_events[0]["result"]
    assert events[-1]["type"] == "response"
    assert events[-1]["content"] == "There is one file: hello.py"
    roles = [m["role"] for m in messages]
    assert roles[-3:] == ["assistant", "tool", "assistant"]
    # The tool result was sent back to the model with the right tool_call_id.
    second_request = server.requests[1]["body"]["messages"]
    assert second_request[-1]["role"] == "tool"
    assert second_request[-1]["tool_call_id"] == "call_0"


def test_streaming_mode(server, tmp_path):
    server.script.append({"content": "streamed answer"})
    messages = init_conversation(tmp_path, build_rag=False)
    events = list(handle_message_streaming(
        user_message="hi", messages=messages, workspace=tmp_path, composer_mode="ask", stream=True,
    ))
    tokens = "".join(e["content"] for e in events if e["type"] == "token")
    assert tokens == "streamed answer"
    assert events[-1]["type"] == "response_end"


def test_history_kept_in_callers_list_after_trimming(server, tmp_path):
    """Regression: trimming used to rebind the list, so long chats stopped being saved."""
    server.script.append({"content": "final answer"})
    messages = init_conversation(tmp_path, build_rag=False)
    for i in range(30):
        messages.append({"role": "user", "content": f"q{i} " + "x" * 6000})
        messages.append({"role": "assistant", "content": f"a{i}"})
    caller_ref = messages
    _run(messages, tmp_path, mode="ask")
    assert caller_ref[-1] == {"role": "assistant", "content": "final answer"}
    assert any("[CONTEXT TRIMMED]" in m.get("content", "") for m in caller_ref if m["role"] == "system")


def test_ask_mode_exposes_only_read_tools(server, tmp_path):
    server.script.append({"content": "ok"})
    messages = init_conversation(tmp_path, build_rag=False)
    _run(messages, tmp_path, mode="ask")
    names = {t["function"]["name"] for t in server.requests[-1]["body"]["tools"]}
    assert "read_file" in names
    assert not names & {"write_file", "run_command", "git_commit"}
