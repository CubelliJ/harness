# Configuration

Harness prompts for an OpenRouter API key when one is not configured. It can
save the key globally in `~/.harness/config.env` or for the current project in
`./.env`. Configuration files use restricted permissions. Environment variables
take precedence over saved configuration.

To configure or change the key interactively:

```bash
python -m harness configure
```

## Environment variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `OPENROUTER_API_KEY` | — | Required API key |
| `OPENROUTER_MODEL` | `openai/gpt-5.6-luna` | OpenRouter model id |
| `HARNESS_WORKSPACE` | current directory | Workspace root |
| `HARNESS_LOGS_DIR` | `~/harness_logs` | Session history directory |
| `HARNESS_HISTORY_FILE` | generated path | Specific history path |
| `HARNESS_LOG_LEVEL` | `INFO` | Logging level |
| `HARNESS_NO_COLOR` | — | Disable terminal colors |
| `HARNESS_COLOR` | — | Force terminal colors |
| `HARNESS_STT_BIN` | `~/.harness/bin/harness-stt.app` | Speech helper path |
