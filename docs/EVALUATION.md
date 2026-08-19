# Evaluation

The repository includes evaluation scenarios and transcript tooling.

Create scenario workspaces and their manifest:

```bash
python make_eval_scenarios.py
```

Run a scenario unattended:

```bash
HARNESS_WORKSPACE="$PWD/eval_scenarios/word_count" \
HARNESS_HISTORY_FILE="$PWD/eval_scenarios/word_count/history.txt" \
python -m harness --yes --scenario word_count
```

Evaluate transcripts:

```bash
python eval_chat.py
python eval_chat.py --scenario word_count
```

The evaluator uses `EVAL_API_KEY`, falling back to `OPENROUTER_API_KEY` from
`.env`. `EVAL_MODEL` and `EVAL_URL` can also be set. Keep the `HARNESS_*`
assignments on the same command, or export them first.
