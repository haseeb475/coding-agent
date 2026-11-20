from agent.llm import consolidate_system_messages, count_tokens, set_system_section, trim_context
from agent.tools import parse_tool_call_fallback


def test_consolidate_system_messages():
    msgs = [{"role": "system", "content": "a"}, {"role": "user", "content": "u"},
            {"role": "system", "content": "b"}]
    out = consolidate_system_messages(msgs)
    assert out[0] == {"role": "system", "content": "a\n\nb"}
    assert out[1:] == [{"role": "user", "content": "u"}]


def test_set_system_section_replaces_existing_section():
    msgs = [{"role": "system", "content": "base"}]
    msgs = set_system_section(msgs, "## Notes", "## Notes\nfirst")
    msgs = set_system_section(msgs, "## Notes", "## Notes\nsecond")
    content = msgs[0]["content"]
    assert content.count("## Notes") == 1
    assert "second" in content and "first" not in content


def test_trim_context_under_budget_returns_same_list():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    assert trim_context(msgs) is msgs


def test_trim_context_summarizes_dropped_messages():
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "task"}]
    for i in range(40):
        msgs.append({
            "role": "assistant", "content": "x" * 2000,
            "tool_calls": [{"function": {"name": "read_file", "arguments": f'{{"filepath": "f{i}.py"}}'}}],
        })
        msgs.append({"role": "tool", "content": "Error: boom" if i == 0 else "ok"})
    trimmed = trim_context(msgs, max_tokens=5000, keep_recent=6)
    assert count_tokens(trimmed) <= 5000 or len(trimmed) <= 4
    assert trimmed[1]["content"] == "task"
    assert "[CONTEXT TRIMMED]" in trimmed[0]["content"]
    assert "f0.py" in trimmed[0]["content"]


def test_trim_context_tolerates_non_dict_arguments():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "t"}]
    msgs += [{"role": "assistant", "content": "y" * 4000,
              "tool_calls": [{"function": {"name": "read_file", "arguments": "[1, 2]"}}]}] * 30
    trim_context(msgs, max_tokens=1000, keep_recent=4)  # must not raise


def test_parse_tool_call_fallback_from_text():
    text = 'I will read it.\n```json\n{"name": "read_file", "arguments": {"filepath": "a.py"}}\n```'
    calls = parse_tool_call_fallback(text)
    assert calls and calls[0]["name"] == "read_file"
    assert parse_tool_call_fallback("just text") in ([], None)
