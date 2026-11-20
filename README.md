# Coding Agent

An autonomous Python coding agent that explores codebases, fixes bugs, writes code and checks its work by running tests. A finite state machine drives it, it searches code with RAG, and it works with any OpenAI-compatible LLM API. You can use it from the terminal, from a browser-based IDE, or as a benchmark harness for HumanEval and SWE-bench Verified.

Most LLM coding helpers let the model call any tool at any time. This agent splits each task into explicit phases (plan → explore → implement → verify → fix). In each phase the model only sees the tools that make sense for that phase. A task counts as finished when its tests pass, not when the model says it is done.

## Key features

- **FSM-controlled workflow.** Six states (`PLAN`, `EXPLORE`, `IMPLEMENT`, `VERIFY`, `FIX`, `DONE`). Each API call sends only the tool schemas allowed in the current state.
- **33 tools** for navigation, reading, searching, editing, batch edits, code and test execution, git, and agent bookkeeping.
- **Two-step RAG** over the codebase with ChromaDB and `sentence-transformers`. Files are chunked with the AST, so whole functions and classes are indexed.
- **Provider-configurable LLM layer.** It supports any OpenAI Chat Completions-compatible endpoint and Azure OpenAI, and you can plug in other adapters (see [API provider support](#api-provider-support)).
- **Works with models that lack native tool calling.** When the model doesn't use native tool calls, tool calls written as JSON in the reply text are parsed instead.
- **Three interfaces:** a terminal chat, a web IDE (file tree, chat with streaming, Xterm.js terminal) and benchmark runners.
- **Robustness features:**
  - A scratchpad memory that survives context trimming.
  - Loop detection.
  - Whitespace-tolerant edits with closest-match hints.
  - Broken-environment detection.
  - Per-task token budgets.
  - Retries with backoff for transient API errors.
  - Reflexion notes from failed tasks.
  - Trajectory logs.

## Results

All SWE-bench numbers come from the **official SWE-bench Docker evaluator**, not from the agent's own test runs. The models were open-weight models served through an OpenAI-compatible endpoint. Your results will vary with the model, the provider and the settings.

| Benchmark                    | Model / config                  | Patches | Resolved | Score                          |
| ---------------------------- | ------------------------------- | ------- | -------- | ------------------------------ |
| **HumanEval** (164)          | Gemma 4 31B (`gemma4-31b-it`)   | —       | 158/164  | **96.3%** (avg 2.0 iterations) |
| **SWE-bench Verified** (500) | Gemma 4 31B, before guard set   | 344     | 161/500  | 32.2% (precision 46.8%)        |
| **SWE-bench Verified** (500) | Gemma 4 31B, final              | 403     | 185/500  | **37.0%** (precision 45.9%)    |
| **SWE-bench Verified** (500) | Qwen3.6-35B-A3B, final          | 313     | 173/500  | 34.6% (precision **55.3%**)    |

- Precision is resolved ÷ non-empty patches.
- All runs used the same tasks, budgets (`--max-iterations 30`) and evaluator, with one model per run (no light-model routing).
- Total token use across the full SWE-bench runs: 168M for Gemma before the guard set, 88M for Gemma with it, and 115M for Qwen.
- The SWE-bench runs gave the agent the issue's `hints_text`.
- [docs/failure_analysis.md](docs/failure_analysis.md) analyses the HumanEval failures.

## How it works

```
                 ┌────────────── interfaces ──────────────┐
                 │  agent/cli.py   ui/app.py   main.py    │
                 └──────────┬─────────────────────────────┘
                            ▼
   agent/agent.py ── run_task()  (benchmarks, FSM-driven)
                 └─ handle_message_streaming()  (chat: ask / debug / work modes)
        │                │                   │
        ▼                ▼                   ▼
   agent/fsm.py     agent/tools.py      agent/llm.py ──► agent/providers/
   states and       33 tools, path      context trim,     openai_compatible.py
   transitions      checks, run_command token counter     azure_openai.py
                         │                                (your adapter here)
                         ▼
          agent/filesystem.py, agent/rag.py, execution/sandbox.py
```

1. **Entry state detection.** `detect_initial_state()` inspects the workspace once:
   - More than 10 Python files → `PLAN`.
   - A small workspace → `EXPLORE`.
   - An existing `solution.py` → `IMPLEMENT` if it is only a stub, `VERIFY` if it already contains code.
2. **Each iteration:**
   1. The context is trimmed to the token budget, and the scratchpad notes are re-injected.
   2. The LLM is called with only the tools allowed in the current state.
   3. The tool calls run: reads can run in parallel, but there is at most one write per turn.
3. **Transitions happen in two ways:**
   - **Driven by events in code.** A `[TEST_RESULT:PASS]` result moves the agent to `DONE`, a failing run moves it to `FIX`, a completed edit forces re-verification, and sustained searching pushes it towards `IMPLEMENT`.
   - **Requested by the model** with `request_transition`. The request is checked against the allowed transition map; an invalid one returns an error and the state stays the same.
4. **Chat mode** (CLI and web UI) uses the same tools without the FSM. A *mode* limits what the model can do:

   | Mode | Tools available |
   |------|-----------------|
   | `ask` | Read-only: explore, read, search, git status/diff/log |
   | `debug` | Adds editing, running code and tests, and `run_command` |
   | `work` | All tools, including `git_commit` |

### Tools (33)

| Category       | Tools                                                                             |
| -------------- | --------------------------------------------------------------------------------- |
| **Navigation** | `list_files`, `view_directory`, `find_files`, `explore_repo`                      |
| **Reading**    | `read_file`, `read_files`, `view_file_range`, `file_outline`, `get_function`      |
| **Searching**  | `search_code`, `search_codebase` (two-step RAG), `search_and_read`                |
| **Editing**    | `write_file`, `str_replace`, `insert_at_line`, `delete_lines`, `create_directory` |
| **Batch**      | `edit_and_verify`, `edit_files`, `search_and_replace_all`                         |
| **Execution**  | `run_code`, `run_tests`, `run_command` (allowlisted), `generate_test`             |
| **Git**        | `git_status`, `git_diff`, `git_commit`, `git_log`, `git_checkout_file`            |
| **Agent**      | `write_scratchpad`, `read_scratchpad`, `request_transition`, `report_confidence`  |

**Implementation details:**
- File paths are resolved and must stay inside the workspace. The `.git` directory is off-limits.
- Repository listing uses `git ls-files` and respects `.gitignore`. Folders that aren't git repositories are walked directly, skipping a fixed list of directories.
- The RAG index is built in memory per task when the workspace has **more than 3** Python files. It uses the `all-MiniLM-L6-v2` embedding model, which is downloaded from the Hugging Face Hub on first use.

## Prerequisites

- **Python 3.10+.** CI tests 3.10–3.12.
- **git.**
- **An LLM API** that speaks the OpenAI Chat Completions format, or Azure OpenAI. The model should support function/tool calling. Without it, the agent falls back to parsing JSON tool calls from the reply text, which works less reliably.
- **Node.js 18+ and npm**, only to build the web UI.
- **Disk and network:** `sentence-transformers` installs PyTorch (about 1–2 GB), and the first RAG run downloads the embedding model (about 90 MB).
- *Optional, for the official SWE-bench evaluation:* Docker on Linux or WSL2, and plenty of free disk space.

## Installation

```bash
git clone https://github.com/haseeb475/coding-agent.git
cd coding-agent

python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                # Windows: copy .env.example .env
# then edit .env (see Configuration)

python main.py --smoke              # checks your LLM configuration
```

Other requirement files:

```bash
pip install -r requirements-bench.txt   # HumanEval / SWE-bench runners
pip install -r requirements-dev.txt     # ruff and the project's test-suite dependencies
```

To build the web UI:

```bash
cd ui/frontend && npm ci && npm run build && cd ../..
```

## Configuration

Settings come from environment variables. A `.env` file is loaded automatically from the current directory (or a parent directory) and from the repository root. Variables already set in your shell take precedence. [.env.example](.env.example) lists every option, with ready-made blocks for common providers.

### LLM

| Variable | Default | Description |
| --- | --- | --- |
| `LLM_PROVIDER` | `openai` | `openai` (any OpenAI-compatible API) or `azure` |
| `LLM_API_KEY` | **required** | API key. Falls back to `OPENAI_API_KEY` (openai) or `AZURE_OPENAI_API_KEY` (azure). Local servers accept any placeholder value. |
| `LLM_MODEL` | **required** | Model name. For Azure, the deployment name. |
| `LLM_BASE_URL` | provider default | API base URL, e.g. `http://localhost:11434/v1`. For Azure, the resource endpoint (or set `AZURE_OPENAI_ENDPOINT`). |
| `LLM_MODEL_LIGHT` | unset | Optional cheaper model for the `PLAN`/`EXPLORE` states and for `ask`-mode chats |
| `LLM_TIMEOUT` | `600` | Request timeout in seconds |
| `LLM_MAX_ATTEMPTS` | `3` | Total attempts per request. Transient errors (429, 5xx, timeouts, connection errors) are retried after 5 s, 10 s, … |
| `LLM_EXTRA_HEADERS` | unset | JSON object of extra HTTP headers |
| `AZURE_OPENAI_API_VERSION` | **required for `azure`** | e.g. `2024-10-21` |

If something is missing or invalid, every entry point stops before the first request with a message naming the variable, for example `Configuration error: LLM_MODEL is not set …`.

### Web UI

| Variable | Default | Description |
| --- | --- | --- |
| `CODING_AGENT_HOST` | `127.0.0.1` | Bind address. Non-loopback addresses are refused unless `CODING_AGENT_ALLOW_REMOTE=1` is set. |
| `CODING_AGENT_PORT` | `8000` | Port |
| `CODING_AGENT_ALLOW_REMOTE` | unset | Set to `1` to allow binding to a non-loopback address. Read [SECURITY.md](SECURITY.md) first. |
| `CODING_AGENT_ALLOWED_HOSTS` | unset | Extra hostnames accepted in `Host`/`Origin` headers, comma-separated |
| `ALLOWED_WORKSPACE_ROOTS` | unset (any folder) | Comma-separated folders that may be opened as workspaces |
| `CODING_AGENT_RELOAD` | unset | Set to `1` to auto-reload the backend on code changes (development) |

## API provider support

| Provider | `LLM_PROVIDER` | How it was tested |
| --- | --- | --- |
| OpenAI-compatible Chat Completions API | `openai` | Automated tests through the real `openai` SDK against a local fake server: blocking and streaming calls, tool-call deltas, Bearer auth, retries, 401 handling. The published benchmarks used a self-hosted OpenAI-compatible endpoint. |
| Azure OpenAI Service | `azure` | Automated tests against a fake server using Azure's URL layout (`/openai/deployments/<name>/chat/completions?api-version=…`) and `api-key` auth. Not yet run against a live Azure resource. |

The `openai` provider should work with services that implement the Chat Completions API: OpenAI itself, OpenRouter, Groq, Together, DeepSeek, Ollama (`/v1`), vLLM and LM Studio, for example. These were **not** each tested individually. Compatibility depends on how faithfully each one implements the API, especially tool calling and streaming. `.env.example` has example settings.

**Not supported natively:** APIs with a different wire format, such as the Anthropic Messages API or the Google Gemini API. You can still use them through an OpenAI-compatible gateway, such as the vendor's own compatibility endpoint or a proxy like LiteLLM, or by writing an adapter.

### Adding a provider

Adapters live in [agent/providers/](agent/providers/). The agent keeps its conversation in OpenAI chat format. An adapter takes those messages and tool schemas and returns a normalized message (`content` plus `tool_calls[].function.{name, arguments}`), so it can translate both ways for any API:

```python
from agent.providers import register_provider
from agent.providers.base import LLMResponse, Provider, Usage, make_message, with_retries

class MyProvider(Provider):
    name = "myprovider"

    def complete(self, messages, *, model, tools=None, temperature=None):
        def call():
            # self.config has api_key, base_url, timeout, extra_headers, ...
            text, tool_calls = ...  # call your API and translate the response
            return LLMResponse(message=make_message(text, tool_calls), usage=Usage(0, 0, 0))
        return with_retries(call, self.config.max_attempts)

    def stream(self, messages, *, model, tools=None, temperature=None):
        response = self.complete(messages, model=model, tools=tools, temperature=temperature)
        if response.message.content:
            yield ("token", response.message.content)
        yield ("done", response)

register_provider("myprovider", MyProvider)   # then set LLM_PROVIDER=myprovider
```

- `register_provider` must run before the first LLM call, for example in your own entry point.
- To ship an adapter with the project, register it in `_register_builtins()` in [agent/providers/\_\_init\_\_.py](agent/providers/__init__.py), and add a test modelled on [tests/test_providers.py](tests/test_providers.py).

## Usage

### Smoke test

```bash
python main.py --smoke
# Testing LLM connection (provider=openai, model=gpt-4o-mini, base_url=(provider default))...
# Response: connection ok
```

### Terminal chat

```bash
python -m agent.cli                              # current directory, read-only "ask" mode
python -m agent.cli /path/to/project --mode work # allow edits, test runs and commits
```

Commands at the prompt: `exit`, `new`, `delete`, `chats`, `switch <n>`. Conversations are saved in `<project>/.agent_history/`.

### Web IDE

```bash
cd ui/frontend && npm ci && npm run build && cd ../..
python -m ui.app
# open http://127.0.0.1:8000
```

- The UI opens the directory the server was started from.
- To switch, enter another path or use **Browse…**. A folder that doesn't exist yet is created when you open it.
- Choose *Ask*, *Debug* or *Work* mode in the chat composer.

For frontend development with hot reload, run two terminals:

```bash
# terminal 1
python -m ui.app
# terminal 2: Vite dev server on :5173, proxies /api and /ws to :8000
cd ui/frontend && npm run dev
```

### Benchmarks

These need `pip install -r requirements-bench.txt`.

```bash
# Custom tasks in evaluation/tasks/benchmark.json
python main.py --task 001
python main.py --benchmark --limit 5

# HumanEval (downloads nothing; the dataset ships with the human-eval package)
python main.py --humaneval --limit 5
python main.py --humaneval-task HumanEval/0
python main.py --humaneval                         # all 164

# SWE-bench Verified: patch generation only (no Docker)
python main.py --swebench --limit 1 --no-eval
python main.py --swebench --no-eval --max-iterations 30

# Generation plus official evaluation (Linux/WSL2 with Docker running)
python main.py --swebench --max-iterations 30
```

**How the runs behave:**
- The default for `--max-iterations` is 20.
- HumanEval runs accept `--offset N` to skip the first N tasks.
- SWE-bench results are saved after every task under the fixed run id `swebench_run`, so re-running resumes and skips finished instances.
- `--instance-ids <id> …` runs specific instances.

**SWE-bench output files:**
- `results/swebench_predictions_swebench_run.jsonl`: patches in the evaluator's format.
- `results/swebench_agent_swebench_run.json`: per-task statistics.
- `swebench_run.coding-agent-fsm.json`: the evaluator report, written to the current directory.

To evaluate an existing predictions file, call `run_official_evaluation()` from [evaluation/swebench_runner.py](evaluation/swebench_runner.py).

## Project structure

```
main.py                 Smoke test and benchmark CLI
agent/
  agent.py              Agent loops: run_task (FSM, benchmarks), handle_message_streaming (chat)
  fsm.py                States, per-state tool sets, transitions, entry-state detection
  tools.py              The 33 tools: schemas and implementations, run_command allowlist
  llm.py                Provider-independent chat()/chat_stream(), context trimming, token counter
  providers/            LLM adapters: config.py, base.py, openai_compatible.py, azure_openai.py
  rag.py                ChromaDB + sentence-transformers code index
  filesystem.py         Workspace-confined file access and git helpers
  prompts.py            System prompts
  history.py            Conversation persistence (CLI and UI)
  failure.py, reflexion.py, trajectory.py   Failure classification, reflection notes, run logs
  cli.py                Terminal chat
execution/
  sandbox.py            Runs Python/pytest in subprocesses (timeouts and credential scrubbing; NOT a sandbox)
  output_format.py      Formats test output
evaluation/
  runner.py             Custom JSON benchmark (tasks/benchmark.json)
  humaneval_runner.py   HumanEval
  swebench_runner.py    SWE-bench Verified generation and official evaluation
  metrics.py            Aggregate metrics
ui/
  app.py                FastAPI backend: REST, SSE chat, terminal WebSocket, static files
  security.py           Host/Origin/Content-Type guard for the local UI
  session.py            Workspace sessions, path validation, folder browser
  chat_runs.py          Resumable chat runs behind the SSE stream
  terminal.py           PTY manager for Xterm.js
  frontend/             Vite + TypeScript frontend (npm run build → frontend/dist)
tests/                  pytest suite (uses a local fake OpenAI-compatible server)
docs/failure_analysis.md
```

Created at runtime and git-ignored:

| Path | Contents |
| --- | --- |
| `logs/` | Trajectory logs, one JSON per `run_task` |
| `reflections/` | Failure notes; the 3 most recent are injected into later tasks |
| `results/` | Benchmark metrics and SWE-bench predictions |
| `workspace/` | Scratch checkouts for benchmark tasks |
| `<project>/.agent_history/` | Saved conversations, inside each opened project |

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `Configuration error: No API key configured` | Set `LLM_API_KEY` in `.env`, or export it. Run commands from the repository root so `.env` is found. |
| `AuthenticationError: Error code: 401` | The key is wrong for this provider or `LLM_BASE_URL`. Check that the key matches the endpoint. |
| `NotFoundError: 404` / "model not found" | `LLM_MODEL` is not available on this endpoint (for Azure: use the *deployment* name). Also check that `LLM_BASE_URL` ends in `/v1` where the provider expects it. |
| `The model request timed out` | Increase `LLM_TIMEOUT`. Large repositories make large prompts, and local models can be slow. |
| The agent describes tool calls instead of running them | The model or server doesn't support tool calling. Use a model with function-calling support. The JSON fallback parser handles only simple cases. |
| The first chat in a large repo is slow | The RAG index is being built, and the first run downloads `all-MiniLM-L6-v2` from Hugging Face. That download needs network access. |
| `ModuleNotFoundError: human_eval` / `datasets` / `swebench` | `pip install -r requirements-bench.txt` |
| HumanEval reports 100% suspiciously | You installed `human-eval` from its GitHub source, which ships with the `exec(...)` line in `human_eval/execution.py` commented out. The PyPI package in `requirements-bench.txt` has it enabled. |
| SWE-bench evaluation fails | The official evaluator needs Docker on Linux or WSL2. Use `--no-eval` to generate patches only. Free disk space between batches with `docker system prune`. |
| `Refusing to bind to '0.0.0.0'` | This is intentional. See [SECURITY.md](SECURITY.md). Set `CODING_AGENT_ALLOW_REMOTE=1` and `CODING_AGENT_ALLOWED_HOSTS` only on a trusted network. |
| The web UI shows a blank page | Build the frontend first: `cd ui/frontend && npm ci && npm run build`. |

## Security

The agent runs code that the LLM writes, as your user, with your permissions. `execution/sandbox.py` is **not** an isolation boundary; it applies only timeouts and keeps LLM credentials out of subprocesses. The web UI has no authentication and includes a shell. It binds to localhost by default and rejects cross-site and DNS-rebinding requests. Run the agent in a container or VM when working on untrusted repositories. Details and reporting instructions are in [SECURITY.md](SECURITY.md).

## Known limitations

- The scratchpad, the RAG index and the token counter are process-wide. Several simultaneous web UI sessions on different projects share them.
- Reflections from failed tasks are reused across later benchmark tasks; delete `reflections/` for independent runs.
- `run_tests` runs pytest with the agent's own Python interpreter, not the target project's virtual environment.
- When a SWE-bench run resumes, earlier tasks are re-recorded with empty statistics in `swebench_agent_*.json`. The predictions themselves are kept.
- The Windows terminal (via `pywinpty`) and native Windows support in general are not covered by CI.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, tests and the pull request process.

## License

Released under the [MIT License](LICENSE).

## Acknowledgements

- [HumanEval](https://github.com/openai/human-eval) and [SWE-bench](https://www.swebench.com/) for the benchmarks
- [ChromaDB](https://www.trychroma.com/) and [sentence-transformers](https://www.sbert.net/) for code search
- [FastAPI](https://fastapi.tiangolo.com/), [Xterm.js](https://xtermjs.org/), [marked](https://marked.js.org/) and [Vite](https://vitejs.dev/) for the interfaces
