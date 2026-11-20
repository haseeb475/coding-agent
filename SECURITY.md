# Security Policy

## Threat model

Coding Agent is a **local developer tool that executes code written by an LLM**. Before you use it, understand what it does and doesn't protect against.

**By design, the agent can:**
- read and modify files inside the workspace you open
- run Python files, pytest, and allowlisted shell commands (`python`, `pip`, `git`, `npm`, `make`, …) through `run_code`, `run_tests`, `generate_test` and `run_command`
- commit to git, in `work` mode

**`run_command` is not a security boundary.**
- Commands run through the system shell, and allowed programs such as `python`, `node`, `pip` and `make` can run arbitrary code.
- The allowlist only stops the model from reaching for unrelated programs by accident.
- `execution/sandbox.py` applies timeouts and nothing else: no container, no seccomp, no resource or network limits. Code runs as your user.

**What is protected:**
- Tool file paths are confined to the workspace, and `.git/` is off-limits.
- LLM credentials (`LLM_API_KEY`, `OPENAI_API_KEY`, `AZURE_OPENAI_API_KEY`) are removed from the environment of every subprocess the agent starts, including git.
- `env` and `printenv` are not allowlisted.

**Prompt injection** is possible. Files, issues or tool output in the workspace can contain instructions that the model follows. Treat any repository you don't trust as hostile.

**Recommendation:** run the agent in a disposable container or VM when working on code you don't trust, and use `ask` mode, which is read-only, when you only need answers.

## Web UI

The web UI (`python -m ui.app`) has **no authentication** and includes an **interactive shell** (`/ws/terminal`). Mitigations:

- It binds to `127.0.0.1` by default. Binding to any other address is refused unless `CODING_AGENT_ALLOW_REMOTE=1` is set.
- Requests whose `Host` header is not a loopback name, or a name listed in `CODING_AGENT_ALLOWED_HOSTS`, are rejected. This blocks DNS-rebinding attacks.
- WebSocket handshakes and state-changing requests from foreign `Origin`s are rejected. POST bodies must be `application/json`, so a web page you visit can't drive the agent or the terminal.
- Model output is rendered as Markdown with raw HTML escaped, and only safe link and image URLs are kept.
- `ALLOWED_WORKSPACE_ROOTS` restricts which folders can be opened. The terminal itself is still an unrestricted shell.

These mitigations don't replace authentication. Anyone who can connect to the port directly gets a shell, for example other users on a shared machine, or anyone on the network if you enable remote binding. Never expose the UI to an untrusted network. To use it remotely, tunnel the loopback port over SSH (`ssh -L 8000:127.0.0.1:8000 host`).

## Secrets

- Put API keys in `.env`, which is git-ignored, or in your shell environment. Never put them in source files or issues.
- The agent never prints or logs your API key. `python main.py --smoke` shows the provider, model and base URL only.

## Supported versions

Security fixes are made on the latest release on the default branch.

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Report them privately through GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability), using **Security → Report a vulnerability** on the repository page. Include:
- steps to reproduce
- the affected version or commit
- the impact you expect

We aim to acknowledge reports within 7 days.
