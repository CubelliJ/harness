# Configuration

Harness uses a configurable OpenAI-compatible API. OpenRouter is the existing
compatibility/default preset. Configuration files use restricted permissions.
The precedence is: shell environment, workspace `<workspace>/.harness/config.env`,
project `.env`, user/machine `~/.harness/config.env`, then the OpenRouter defaults.
Files are loaded from least-specific to most-specific with `setdefault`, so shell
variables always win and workspace values override machine values.

`~/.harness/config.env` is user/machine-level configuration shared across
workspaces. `<workspace>/.harness/config.env` applies only to that workspace.

For a generic gateway, neutral settings could look like:

```dotenv
HARNESS_BASE_URL=https://gateway.example.com/v1
HARNESS_MODEL=example-model
HARNESS_AUTH_MODE=bearer
HARNESS_BACKEND_NAME=Example Gateway
```

To configure or change the key interactively:

```bash
python -m harness configure
```

## Environment variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `HARNESS_BASE_URL` | OpenRouter compatibility base | Base URL; trailing slashes are removed |
| `HARNESS_CHAT_URL` | `<base>/chat/completions` | Chat completion URL override |
| `HARNESS_MODELS_URL` | `<base>/models` | Model catalogue URL override |
| `HARNESS_API_KEY` | legacy key fallback | API key for bearer authentication |
| `HARNESS_MODEL` | OpenRouter compatibility model | Active model; saved selections use this variable |
| `HARNESS_AUTH_MODE` | `bearer` | `none` or `bearer`; bearer requires a key |
| `HARNESS_REQUEST_TIMEOUT_S` | `600` | Request timeout in seconds |
| `HARNESS_BACKEND_NAME` | `OpenRouter` | Display name used in CLI and errors |
| `HARNESS_REASONING_EFFORT` | unset | Optional request field; omitted when unset |
| `OPENROUTER_API_KEY` | — | Legacy compatibility key |
| `OPENROUTER_MODEL` | compatibility model | Legacy compatibility model |
| `HARNESS_WORKSPACE` | current directory | Workspace root |
| `HARNESS_LOGS_DIR` | `~/harness_logs` | Session history directory |
| `HARNESS_HISTORY_FILE` | generated path | Specific history path |
| `HARNESS_LOG_LEVEL` | `INFO` | Logging level |
| `HARNESS_NO_COLOR` | — | Disable terminal colors |
| `HARNESS_COLOR` | — | Force terminal colors |
| `HARNESS_STT_BIN` | `~/.harness/bin/harness-stt.app` | Speech helper path |
