# CLI and Module Decomposition Plan

## Purpose

`harness/main.py` is a high-risk god-module. It currently combines CLI startup,
REPL/session orchestration, agent/provider turns, raw terminal input, paste and
modified-key handling, confirmations, and voice UI.

The goal is to separate these responsibilities into focused packages while
preserving behavior and keeping normal modules near or below 300–400 lines.

## Branch and workflow

- Branch: `feature/extract-repl-loop`
- Base: latest `origin/develop`
- Integration flow: `feature/*` → `develop` → `main`
- Make one focused extraction at a time.
- Run the full unit suite after every meaningful Python change:

  ```bash
  python -m unittest discover -s tests -v
  ```

- Review status and diff before each commit.
- Use Conventional Commit messages.
- Keep the working tree clean between extractions.

## Completed transitions

### 1. CLI startup extraction

Commit: `def8c63 refactor: extract CLI startup module`

Added:

```text
harness/cli/
├── __init__.py
└── main.py
```

Moved argument parsing, scenario loading, environment setup, configuration
initialization, and non-interactive request handling to `harness/cli/main.py`.

`harness.main:main` remains a compatibility wrapper so these entry points stay
stable:

- `harness.main:main`
- `python -m harness`
- The packaged `harness` console script

### 2. Agent turn extraction

Commit: `3394e29 refactor: extract agent turn loop`

Added:

```text
harness/cli/agent_loop.py
```

Moved provider streaming and tool-call execution out of `run()`. The extracted
loop receives callbacks for persistence, compaction, confirmations,
interruptible calls, context-token updates, and title generation.

Current size after this transition:

```text
harness/main.py          1,045 lines
harness/cli/agent_loop.py  163 lines
```

Validation after the first two transitions: 108 unit tests passed.

### 3. REPL/session orchestration extraction

Commit: `02d4897 refactor: extract REPL orchestration`

Added:

```text
harness/cli/repl.py
```

Moved session loading, persistence, title generation, compaction, conversation
clearing, request processing, and REPL command dispatch out of `harness.main`.
The implementation temporarily imports terminal and confirmation helpers from
`harness.main`; those are intentionally left for the input, confirmations, and
voice UI transitions below.

Current size after this transition:

```text
harness/main.py       847 lines
harness/cli/repl.py   268 lines
```

Validation after all three transitions: 108 unit tests passed.

### 4. Terminal input extraction

Commit: `f71cacf refactor: extract terminal input handling`

Added:

```text
harness/cli/input.py
```

Moved raw terminal input, bracketed-paste handling, modified-key handling,
Escape interruption, interruptible calls, and pending-input draining out of
`harness.main`. `harness.main` and `harness.cli.repl` continue to import
compatibility names from the new module.

The interrupted-tool conversation repair helper remains in
`harness/cli/agent_loop.py`, where it belongs with agent-turn behavior.

Current sizes after this transition:

```text
harness/main.py        576 lines
harness/cli/input.py   258 lines
harness/cli/repl.py    269 lines
harness/cli/agent_loop.py 194 lines
```

Validation after all four transitions: 108 unit tests passed.

## Target structure

```text
harness/
├── cli/
│   ├── __init__.py
│   ├── main.py              # argument parsing and startup
│   ├── repl.py              # session lifecycle and command dispatch
│   ├── agent_loop.py        # provider/tool turns
│   ├── input.py             # raw mode, paste, and key sequences
│   ├── confirmations.py     # command/edit approval prompts
│   └── voice_ui.py          # voice interaction and terminal display
│
├── tools/
│   ├── __init__.py          # public exports and TOOL_REGISTRY
│   ├── filesystem.py        # paths, read/list/search/edit/image
│   ├── shell.py             # run_command
│   └── git.py               # Git inspection tools
│
├── voice/
│   ├── __init__.py
│   ├── session.py            # STT subprocess/session lifecycle
│   └── transcript.py         # transcript assembly and normalization
│
├── terminal/
│   ├── __init__.py
│   └── markdown.py           # Markdown rendering
│
├── config.py
├── conversation.py
├── llm.py
├── registry.py
└── main.py                   # stable compatibility entry point
```

The exact split should follow responsibility and dependency direction, not
line count alone.

## Remaining transitions

### 3. Extract REPL/session orchestration — next

Create `harness/cli/repl.py` and move the session-related logic from `run()`:

- Session loading and resume selection
- Conversation persistence and catalog registration
- Conversation title generation coordination
- Compaction and `/compact`
- `/clear`, `/context`, and `/cost`
- Model selection and context-limit refresh
- Approval mode commands
- Input loop and command dispatch
- Initial request handling

Keep terminal-specific implementations in `main.py` temporarily through
callbacks where necessary. Do not combine this step with raw-mode extraction.

Add focused tests for command dispatch and session state transitions. Preserve
`harness.main.run()` as a compatibility wrapper until callers and tests migrate.

Suggested commit:

```text
refactor: extract REPL orchestration
```

### 4. Extract terminal input

Create `harness/cli/input.py` and move or separate:

- `_read_input`
- `_echo`
- `_drain_pending_input`
- Bracketed-paste markers and state handling
- Shift+Enter handling
- Ctrl+C and escape-sequence handling
- Raw/cbreak terminal setup and restoration

Prefer a small pure key-sequence/state-machine layer so paste and modified-key
behavior can be tested without a real TTY.

Required coverage:

- Bracketed paste preserves embedded newlines
- Paste markers are not returned as content
- Shift+Enter inserts a newline
- Ctrl+C variants interrupt
- Arrow/function sequences are ignored safely
- Backspace works across normal text and pasted text
- CR/LF submission behavior is preserved
- Terminal settings are restored on errors

Suggested commit:

```text
refactor: extract terminal input handling
```

### 5. Extract confirmations

Create `harness/cli/confirmations.py` and move:

- `_read_confirmation`
- `_confirm_command`
- `_confirm_edit`
- Diff colorization used by confirmation output
- Voice pause and pending-input cleanup coordination, if appropriate

Keep the confirmation callback contract used by `agent_loop.py` unchanged.

Suggested commit:

```text
refactor: extract CLI confirmations
```

### 6. Extract voice UI

Create `harness/cli/voice_ui.py` and move:

- `_visible_len`
- `_terminal_width`
- `_rows_for_voice_line`
- `_clear_voice_display`
- `_render_voice_line`
- `_wait_voice_keys`
- `_voice_loop`

Keep `harness.voice` responsible for the STT process and transcript protocol;
keep terminal rendering and keyboard interaction in `voice_ui.py`.

Required coverage:

- ANSI-aware visible-width calculation
- Wrapped transcript row calculation
- Enter submits
- Escape cancels/exits voice mode
- Ctrl+C interrupts
- Voice subprocess failures clean up terminal state
- Voice mode returns to typed REPL correctly

Suggested commit:

```text
refactor: extract voice CLI UI
```

### 7. Split tools into a package

Convert `harness/tools.py` into `harness/tools/`:

- `filesystem.py`: `resolve_abs_path`, `read_file`, `read_image`,
  `list_files`, `search_files`, `edit_preview`, and `edit_file`
- `shell.py`: `run_command`
- `git.py`: Git status, diff, log, and branch tools
- `__init__.py`: re-export existing names and construct `ALL_TOOLS` and
  `TOOL_REGISTRY`

Preserve the current import surface initially:

```python
from harness.tools import TOOL_REGISTRY
```

Migrate tests and patches deliberately. In particular, existing tests patch
`harness.tools.workspace_root`; either preserve that facade or update tests in
the same focused commit.

Suggested commit:

```text
refactor: split tools into focused modules
```

### 8. Optional follow-up package splits

Only split these if their responsibilities or test seams justify it:

- `harness/voice.py` → `voice/session.py` and `voice/transcript.py`
- `harness/terminal.py` → `terminal/markdown.py`
- `harness/llm.py` → provider, streaming, and model-catalog modules
- `harness/conversation.py` → persistence, compaction, and message helpers

Avoid splitting a file solely to satisfy a line-count target.

## Compatibility requirements

- Do not break the packaged `harness` command.
- Do not break `python -m harness`.
- Preserve `harness.main:main` and `harness.main.run` until migration is
  complete.
- Preserve existing tool names and model-facing schemas.
- Preserve conversation JSON/history formats.
- Preserve terminal cleanup in all exception paths.
- Preserve callback behavior for command/edit confirmation and interruption.
- Avoid circular imports by keeping lower-level modules independent of CLI
  modules.

## Size policy

Use these as review guidelines:

- Preferred: under 300 lines
- Review threshold: 400 lines
- Larger files require a clear responsibility-based reason
- Split by cohesion and dependency direction, not arbitrary line ranges
- A package facade may be small even when implementation modules are separate

## Recovery instructions

If context is lost, start with:

1. Read this file.
2. Run `git status --short --branch`.
3. Run `git log --oneline -n5`.
4. Confirm the branch is `feature/extract-repl-loop`.
5. Continue with the first unchecked transition, currently REPL/session
   orchestration.
6. Run the full unit suite before committing.
