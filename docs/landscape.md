# Voice briefings for terminal agents: landscape and costs

Research snapshot: **2026-08-30**. Repository counts, product prices, and vendor features change quickly; recheck linked sources before using them in launch copy or a financial model.

## Executive take

There is a real, observable need here, but BLAIR is entering an active category rather than inventing one.

- Voice **input** is increasingly supplied by the operating system or the agent vendor. Windows has `Win+H`, macOS has Dictation, and Claude Code now has a built-in `/voice` command. Building another microphone stack is not necessary for BLAIR's first release.
- Voice **output** is still fragmented. There are notification scripts, tools that read the entire answer, full two-way voice shells, and a smaller group that speaks a short summary.
- [Aftertone](https://github.com/omarelkhal/aftertone) is the closest direct competitor found. It supports Windows, macOS, and Linux; Cursor, Claude Code, and Codex; local TTS; per-session controls; and a short `<spoken_summary>` supplied by the agent.
- The strongest defensible BLAIR wedge is therefore not “voice for coding agents.” It is: **a Windows-first, microphone-free briefing layer that deterministically reports what changed, whether it worked, and when the screen contains important detail.**
- Observable interest is meaningful but not proof of a large market. A Codex request for a completion sound has 214 reactions and 53 comments, while most purpose-built voice-output repositories have tens of stars rather than thousands. The category looks early, fragmented, and experimentation-heavy.

## Separate the four product layers

Voice products are easy to compare incorrectly because they combine different layers:

1. **Capture:** microphone, push-to-talk, wake word, and privacy indicator.
2. **Transcription:** local or cloud speech-to-text, live transcript, editing, and submit behavior.
3. **Briefing:** select or summarize the agent result into something useful to hear.
4. **Speech:** local or cloud text-to-speech, voice selection, playback, interruption, and queues.

BLAIR v0.1 owns layers 3 and 4. It can document OS/vendor dictation for layers 1 and 2 without ever opening the microphone. That is a product advantage for users who do not want another always-listening process.

## Direct competitors

### Short spoken summaries

| Project | What it does | Where it overlaps | Useful lesson or gap |
| --- | --- | --- | --- |
| [Aftertone](https://github.com/omarelkhal/aftertone) | Hooks Cursor, Claude Code, and Codex; runs local Supertonic ONNX; supports Windows, macOS, and Linux; enables speech per chat. | This is the closest match to BLAIR's short, local, session-scoped briefing. | Its default depends on the agent emitting `<spoken_summary>`; no tag means no speech. BLAIR can differentiate with a deterministic, prompt-independent fallback and a built-in Windows voice requiring no model download. Study its per-session commands, common daemon, doctor command, and safe multi-adapter install. |
| [Voice plugin in `claude-code-tools`](https://pchalasani.github.io/claude-code-tools/plugins-detail/voice/) | Makes Claude add a 1–2 sentence marker, then speaks it with a persistent local Pocket TTS service; a headless Claude call is the fallback. | Concise, conversational completion reports and on/off controls. | Marker extraction is fast and usually free of an extra call; the fallback improves quality but introduces latency, privacy, and provider dependence. Its per-session state and playback lock are worth copying conceptually. It is Claude-specific. |
| [`claude-codex-voice-mlx`](https://github.com/baryhuang/claude-codex-voice-mlx) | Uses the same local daemon for Claude Code and Codex, speaks a short `🔊` line, queues sessions, and cancels only the issuing session on a new prompt. | Multi-agent adapters, spoken summaries, cancellation, and a local voice. | Strong reference for session-aware queue semantics and fast persistent-model synthesis. It requires Apple Silicon and a reference recording, so it does not serve native Windows. |
| [`claude-voice`](https://github.com/jvosloo/claude-voice) | macOS push-to-talk plus a “narrate” mode that summarizes replies locally before TTS; has a hotkey and spoken on/off commands. | End-to-end input plus summarized output. | Demonstrates that users value separate notify and narrate modes. Its macOS-only design and larger microphone stack leave room for a smaller Windows output layer. |
| [`claude-tts`](https://github.com/chendrizzy/claude-tts) | Speaks a curated stream of pivots, errors, and final answers. Supports an Ollama/cloud summarizer and a deterministic no-LLM floor. | Selective status reporting rather than reading every byte. | Good inspiration for event classification, noise suppression, deterministic fallback, and bounded spoken logs. Windows currently requires a manually run daemon or WSL/Docker, and the integration is Claude-specific. |
| [Voxlert](https://github.com/settinghead/voxlert) | Generates short in-character event phrases for Claude Code, Cursor, Codex, pi, and OpenClaw, using a local or cloud LLM and local TTS. | Cross-agent completion/error/approval briefings with personality. | Validates event categories and swappable providers. BLAIR can be simpler, deterministic by default, and avoid character/IP positioning or an LLM dependency. |
| [`claude-code-tts`](https://github.com/ktaletsk/claude-code-tts) | A Claude Stop-hook system using Kokoro, interruption, markdown cleanup, and an optional `TTS_SUMMARY` marker. | Local neural voice and concise completion speech. | Shows the value of interruption and a persistent model. Its summary quality is obtained by modifying Claude's instructions, and its setup is Unix-oriented. |

The product concept is therefore validated by prior art, but not novel by itself. The most important competitive comparison at launch is BLAIR versus Aftertone, not BLAIR versus Windows Narrator.

### Spoken notifications and read-everything tools

These are adjacent rather than exact competitors:

- [agent-notify](https://github.com/paultendo/agent-notify) classifies completion, approval, question, error, and authentication events across Codex, Claude Code, and Gemini CLI. It can use system TTS, but its core job is notification and terminal focus rather than a result gist.
- [Codex CLI hooks](https://github.com/shanraisshan/codex-cli-hooks) and [Claude Code hooks](https://github.com/shanraisshan/claude-code-hooks) play prerecorded event clips. They prove that an audible “done” signal is useful, but do not explain what happened.
- [MatiousCorp/claude-tts](https://github.com/MatiousCorp/claude-tts) supports many cloud and local TTS providers on macOS, Linux, and Windows. It cleans and reads the response rather than producing a compact, status-aware human briefing.
- [ybouhjira/claude-code-tts](https://github.com/ybouhjira/claude-code-tts) is a cross-platform OpenAI TTS plugin with a Stop hook, worker pool, playback mutex, and standalone CLI. It is a useful queue/failure reference but requires a cloud API key.
- [Murmur](https://github.com/ArshiaEcho/murmur) is a polished, local-first Apple Silicon app combining dictation, read-aloud, and a live Claude Code session observatory. It reads replies and provides a dashboard rather than focusing on a short Windows briefing.
- [`kokoro-tts-mcp`](https://github.com/scottschram/kokoro-tts-mcp) exposes local speech as an MCP tool to Claude and Codex on Apple Silicon. Because the agent must decide to call the tool, it is less deterministic than a completion hook.

### Full two-way voice systems

These compete for the broader phrase “voice interface,” but solve a larger problem than BLAIR:

- [VoiceMode](https://github.com/mbailey/voicemode) provides natural voice conversations through MCP and local/cloud speech services.
- [voicebridge](https://github.com/cc-vb/voicebridge) offers hands-free and phone control, local Whisper and Kokoro, barge-in, and multi-agent routing. It is primarily macOS and source-available rather than conventionally open source.
- VoiceTerm's public materials describe a Rust terminal overlay with local Whisper, PTY passthrough, wake phrases, and voice submission for Codex and Claude Code. Its previously indexed repository was unavailable when this snapshot was checked, so it should not be treated as a dependable integration reference.
- [Clara Voice Code](https://marketplace.visualstudio.com/items?itemName=clara-voice.clara-voice-code) is a free Windows VS Code extension using Groq Whisper and Edge TTS. It had 69 Marketplace installs at the snapshot and targets the editor extension rather than arbitrary terminal sessions.

These tools show demand for hands-free operation, accessibility, and remote monitoring. They also show how quickly scope expands into microphone permissions, echo cancellation, focus injection, wake-word false positives, and mobile relays. BLAIR should resist that scope in v0.1.

## Official and commercial product landscape

- [Claude Code voice dictation](https://code.claude.com/docs/en/voice-dictation) provides hold or tap recording, a live transcript, and optional auto-submit in the CLI. Anthropic says audio is sent to its servers, the feature requires a Claude.ai login, and transcription does not consume Claude messages or tokens. The official page documents speech input, not a terminal spoken-summary feature.
- [ChatGPT Voice in Work and Codex](https://help.openai.com/en/articles/20001275) can start and coordinate Codex tasks from the ChatGPT desktop app on macOS and Windows. It is a full vendor experience rather than a lightweight hook for an existing terminal; connected voice time is separately metered where flexible pricing applies.
- [Windows voice typing](https://support.microsoft.com/en-us/accessibility/windows/use-voice-typing-to-talk-instead-of-type-on-your-pc) is available with `Win+H` and uses Microsoft's online speech recognition. [Windows Voice Access](https://support.microsoft.com/en-us/accessibility/windows/voice-access/use-voice-access-to-control-your-pc-author-text-with-your-voice) is a separate on-device, offline-capable accessibility feature.
- [macOS Dictation](https://support.apple.com/en-au/guide/mac-help/mh40584/mac) types wherever text can be entered and lets the user choose a shortcut; Apple tells users to inspect Keyboard settings to see whether a given language is processed on-device.
- [Superwhisper](https://superwhisper.com/docs/get-started/sw-pro) is adjacent paid validation for system-wide dictation, not spoken agent results. Its current listed plans are $8.49/month, $84.99/year, or $249.99 lifetime, with a free dictation tier.
- [Nura Dev](https://nuradev.app/) is a closer commercial signal: $4.99/month for phone-based voice in/out and remote Claude Code approvals. It pays for voice processing and relay infrastructure, whereas BLAIR's local desktop path can remain free.

There is a proven paid category for better dictation and an emerging paid category for remote agent control. The evidence does **not** yet establish willingness to pay specifically for short terminal briefings. Open source is a sensible initial distribution strategy.

## Observable interest signals

These figures are directional snapshots, not market-size estimates:

- OpenAI's open issue [“Play a sound when Codex finishes a prompt / task”](https://github.com/openai/codex/issues/3962) had **214 reactions and 53 comments**. It is the strongest direct signal that users want attention freed while an agent runs. It does not prove they want synthesized summaries specifically.
- The earlier Codex [voice-input request](https://github.com/openai/codex/issues/418) accumulated **30 reactions and 16 comments**. It supports the broader voice workflow, while also reinforcing the decision to let the OS or vendor own transcription.
- An Anthropic request for [native TTS with per-session controls](https://github.com/anthropics/claude-code/issues/45251) explicitly describes the output-direction gap and the need to keep parallel sessions independent. It was closed as not planned and had only **2 reactions and 5 comments**, so it is useful qualitative evidence but weak quantitative evidence.
- At the snapshot, [VoiceMode](https://github.com/mbailey/voicemode) had about **1,341 stars and 188 forks**. The voice plugin lives inside [`claude-code-tools`](https://github.com/pchalasani/claude-code-tools), whose whole toolkit had about **1,987 stars**; those stars cannot be attributed to voice alone.
- The event-sound [Claude hooks](https://github.com/shanraisshan/claude-code-hooks) had about **531 stars**, while the newer [Codex hooks](https://github.com/shanraisshan/codex-cli-hooks) had about **70**.
- Exact or near-exact briefing projects were much smaller: Aftertone and Voxlert each had **13 stars**, ktaletsk's Claude TTS hook had **17**, ybouhjira's plugin had **21**, and MatiousCorp's provider plugin had **28**.

The responsible conclusion is: **the pain is credible and repeated, but product-market fit for a standalone briefing layer remains unproven.** A useful release should measure activation, repeat use, disable rate, replay rate, and support requests rather than quote a speculative market size.

## Cost model

All amounts below are USD list-price approximations before tax, retries, minimum subscriptions, regional uplifts, or free-tier credits.

### Transcription

BLAIR itself does not transcribe in v0.1, so its transcription cost is **$0**. Users can choose one of the following independently.

| Path | Marginal service cost | Privacy and product implication |
| --- | ---: | --- |
| Windows `Win+H` or macOS Dictation | No separately metered fee documented; included with the OS | Windows voice typing is online; Windows Voice Access can be on-device. macOS processing location varies by language/configuration. |
| Claude Code `/voice` | No extra Claude messages or tokens; eligible Claude.ai account still required | Anthropic explicitly says recorded audio is streamed to its servers, not processed locally. |
| Local Whisper/Parakeet | $0 API cost | Model download, CPU/RAM, microphone permissions, and maintenance become the user's cost. |
| OpenAI batch transcription | `gpt-4o-mini-transcribe` **$0.003/min**; `gpt-transcribe` **$0.0045/min** | At 5 hours/month: about **$0.90–$1.35**. Audio leaves the machine. |
| OpenAI live transcription | **$0.017/min** | At 5 hours/month: about **$5.10**. Relevant only if BLAIR later owns live capture. |
| ElevenLabs Scribe | Batch **$0.22/hour**; realtime **$0.39/hour** | At 5 hours/month: about **$1.10** batch or **$1.95** realtime. |

OpenAI rates come from its current [API pricing](https://developers.openai.com/api/docs/pricing); ElevenLabs rates come from its [API pricing](https://elevenlabs.io/pricing/api).

### The summary or briefing step

This part can be essentially free.

| Strategy | Approximate incremental cost | Main trade-off |
| --- | ---: | --- |
| BLAIR deterministic rules | **$0** | Fast, offline, reproducible, and cannot invent facts; wording is less fluid and difficult outputs need careful rules. |
| Agent-supplied marker | No separate model call; usually tens of extra output tokens in the existing turn | Natural and context-aware, but depends on prompt compliance and can be omitted or hallucinated. |
| Local small LLM | **$0 API cost** | Better prose at the cost of model download, RAM, cold start, and another failure surface. |
| Separate cloud LLM | Usually a small fraction of a cent per turn | Best flexible prose, but sends the agent result to another service and adds latency, credentials, and a failure mode. |

For scale, current standard short-context pricing for `gpt-5.6-luna` is $0.10 per million input tokens and $0.60 per million output tokens. If one summary consumes 2,000–5,000 input tokens and returns 60–100 tokens, the calculation is roughly **$0.00024–$0.00056 per result**, or **$0.024–$0.056 for 100 results**. This is an illustration, not a BLAIR dependency. The non-financial costs—privacy, latency, network reliability, and accidental fabrication—matter more than the API bill.

The recommended default is deterministic. An optional, explicitly enabled local or cloud “more conversational” summarizer can be considered later, with a visible privacy warning and deterministic fallback.

### Speech synthesis

Assume 100 briefings per month at 250 characters each: **25,000 synthesized characters**.

| TTS path | Published rate | Approximate cost for 25,000 characters |
| --- | ---: | ---: |
| Windows SAPI | Included with Windows; no metered API | **$0** |
| Local Kokoro | No API charge after model download and local installation | **$0** plus disk/CPU |
| Amazon Polly Standard / Neural / Generative | $4 / $16 / $30 per million characters | **$0.10 / $0.40 / $0.75** |
| Google Standard or WaveNet / Neural2 / Chirp 3 HD | $4 / $16 / $30 per million characters | **$0.10 / $0.40 / $0.75**, often reduced by a free tier |
| ElevenLabs Flash/Turbo / v3 | $0.05 / $0.10 per 1,000 characters | **$1.25 / $2.50** before plan effects |

Sources: [Amazon Polly pricing](https://aws.amazon.com/polly/pricing/), [Google Cloud Text-to-Speech pricing](https://cloud.google.com/text-to-speech/pricing), and [ElevenLabs API pricing](https://elevenlabs.io/pricing/api). Kokoro's [model is Apache-2.0](https://huggingface.co/hexgrad/Kokoro-82M) and the [`kokoro-onnx` wrapper is MIT](https://github.com/thewh1teagle/kokoro-onnx); runtime dependencies still need their own license review.

Cloud TTS is not financially alarming at personal scale, but it adds keys, network latency, content disclosure, quota failures, and commercial voice terms. A local default is still the better fit for BLAIR's trust promise.

## Product direction for BLAIR

### Positioning

Use **“spoken briefings for terminal agents”**, not the broader and crowded **“voice coding assistant.”** A concise promise:

> BLAIR tells you what your coding agent finished, whether it worked, and when the details need your eyes—without listening to your microphone.

Do not market a voice as “FRIDAY” or imitate a specific performer's identity. Ship or select a licensed, original voice described as a calm, polished British English woman.

### Differentiation to prove

1. **Prompt-independent reliability:** a useful report even when the agent was not instructed to emit a summary marker.
2. **Native Windows quality:** safe PowerShell installer, config backups/merging, SAPI fallback, global hotkeys, clean uninstall, and no WSL requirement.
3. **Explicit trust:** one consent question per session, a visible/easy off switch, no microphone access, local processing by default, and logs that do not retain raw prompts.
4. **Session isolation:** parallel Codex and Claude sessions must not mute, cancel, or replay one another accidentally.
5. **Briefing semantics:** preserve success, partial success, blocked/waiting states, tests, and next action; replace code, paths, tables, and diffs with screen-directed phrases.
6. **Fail-open hooks:** audio failures must never block or corrupt the coding agent.
7. **Generic integration:** make the event contract simple enough that another CLI can pipe a completed result to BLAIR without a custom microphone or UI.

### What to learn from competitors

- From Aftertone: per-session commands, adapter parity, one shared daemon, model health checks, and a clean doctor/uninstall story.
- From `claude-codex-voice-mlx`: session-aware cancellation, warm persistent inference, and fast first audio.
- From agent-notify and Voxlert: normalize vendor events into completion, error, approval, waiting, and question categories.
- From `claude-code-tools`: speech markers can be an optional high-quality fast path, but should not be the only path.
- From Murmur and voicebridge: make listening state unmistakable if microphone support is ever added; do not add it silently.

### Release sequence

1. Ship the narrow Windows briefing product with Codex, Claude Code, and generic stdin adapters.
2. Validate that people keep it enabled for real sessions. Collect opt-in feedback rather than default telemetry.
3. Add macOS only after session behavior and briefing quality are stable.
4. Consider optional agent-supplied or local-LLM summaries only if deterministic briefings are repeatedly judged too mechanical.
5. Treat microphone capture, wake words, phone control, and continuous conversation as separate future products, not automatic roadmap items.

The key risk is not synthesis cost. It is whether the briefing is consistently useful enough that users leave it on. BLAIR wins only if it says less than the screen while conveying more than a completion chime.
