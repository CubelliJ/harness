# Harness

Harness is a lightweight CLI coding agent that can inspect, edit, and test files
in your workspace using [OpenRouter](https://openrouter.ai/).

## Quick start

Requirements: Python 3.9+ and an OpenRouter API key.

```bash
git clone https://github.com/CubelliJ/harness.git
cd harness
make install
```

Run the `source` command printed by the installer, then start Harness:

```bash
harness
```

On first launch, Harness prompts for your API key and lets you save it globally
or for the current project. You can also set `OPENROUTER_API_KEY` in your
environment.

## Usage

Harness works in the directory where it is launched. Describe the task you want
completed, and it can read files, make edits, search the workspace, and run
commands.

Useful commands:

- `/help` — show available commands
- `/model` — list available OpenRouter models with context windows
- `/model <number|provider/model-id>` — switch models for the session
- `/context` — show model context usage
- `/compact` — manually compact older conversation turns
- `/clear` — start a fresh conversation while preserving the workspace
- `/auto-accept` — approve future file edits automatically
- `/voice` — use voice input on macOS
- `/quit` — exit Harness

Shell commands always require confirmation. Session transcripts are saved in
`~/harness_logs/`.

## More documentation

- [Tools](docs/TOOLS.md) — available file, search, command, and skill tools
- [Skills](docs/SKILLS.md) — workspace-specific instructions and lazy loading
- [Configuration](docs/CONFIGURATION.md) — environment variables and saved keys
- [Voice mode](docs/VOICE.md) — macOS speech input setup and usage
- [Evaluation](docs/EVALUATION.md) — scenario generation and transcript evaluation

## Development

Run the tests with:

```bash
python -m unittest discover -s tests -v
```

See [SECURITY.md](SECURITY.md) for security guidance and
[CHANGELOG.md](CHANGELOG.md) for release history.

## License

This project is licensed under the [MIT License](LICENSE). Copyright (c) 2026
Joaquin Cubelli.
