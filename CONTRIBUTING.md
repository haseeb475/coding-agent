# Contributing

Thanks for your interest in improving Coding Agent! Bug reports, documentation fixes, new provider adapters and agent improvements are all welcome.

## Development setup

```bash
git clone https://github.com/haseeb475/coding-agent.git
cd coding-agent
python -m venv venv && source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                 # only needed to talk to a real LLM

# Frontend (optional)
cd ui/frontend && npm ci && npm run build
```

## Checks to run before opening a pull request

```bash
ruff check .                 # lint (config in pyproject.toml)
pytest                       # test suite, no API key or network needed
cd ui/frontend && npm run build   # type-check and build the web UI, if you touched it
```

The tests run the real `openai` SDK against a local fake OpenAI-compatible server ([tests/fake_openai_server.py](tests/fake_openai_server.py)), so they need no credentials. If you change behaviour, add or update a test for it.

## Guidelines

- **Keep changes focused.** One logical change per pull request. Avoid drive-by reformatting of unrelated code.
- **Code style.** Follow the existing style. Code must pass `ruff check` (rules E, F, W, I), and lines should stay under about 120 characters where practical.
- **Provider adapters** go in `agent/providers/`. Subclass `Provider`, register the adapter in `_register_builtins()`, add any new configuration to `agent/providers/config.py` and `.env.example`, and add tests. Only document a provider as supported if it has been tested.
- **Agent behaviour changes** (prompts, FSM transitions, tool semantics) can change benchmark results. Describe the expected effect in the pull request, and include before/after numbers if you have them, naming the model and benchmark subset.
- **Security-sensitive areas:** path validation, `run_command`, subprocess environments and the web UI request guard. Changes there need tests. Report vulnerabilities privately, as described in [SECURITY.md](SECURITY.md).
- **No secrets** in code, tests, fixtures or logs.
- **Changelog.** Add an entry under "Unreleased" in [CHANGELOG.md](CHANGELOG.md) for user-visible changes.

## Reporting bugs and requesting features

Use the issue templates. For bugs, include:
- your OS and Python version
- the provider and model (but never your API key)
- the command you ran
- the full error output

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
