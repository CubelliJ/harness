# Voice mode

Voice input is available on macOS through the `/voice` command. It uses Apple’s
Speech framework and a small native Swift helper.

There is no silence timeout: speak, then press **Enter** to submit. Press
**Escape** to return to keyboard input. Confirmations remain on the keyboard
and pause the microphone while they run.

On first use, Harness compiles the helper into
`~/.harness/bin/harness-stt.app`. Xcode Command Line Tools are required:

```bash
xcode-select --install
```

macOS may request Microphone and Speech Recognition permissions. Voice mode is
not available on Linux or Windows.
