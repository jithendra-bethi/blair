# Optional TTS licenses

This notice separates BLAIR's Apache-2.0 core from software and model assets that
can be installed for the optional Kokoro voice. It is informational, not legal
advice; redistributors should review the exact artifacts they ship.

## Core release

`BLAIR-0.1.0-windows-core.zip` contains the BLAIR bootstrap, BLAIR wheel, scripts,
and documentation. BLAIR-authored core code is licensed under Apache-2.0. The
default `-Kokoro Skip` installation uses Windows SAPI and does **not** bundle the
Kokoro Python environment, eSpeak NG, or Kokoro model/voice assets.

Windows SAPI and the installed Microsoft voices are operating-system components;
their terms come from Microsoft and are not relicensed by BLAIR.

## Optional Kokoro installation

`scripts\install.ps1 -Kokoro Install` is an explicit, separate action. It obtains
third-party Python packages and approximately 354 MB of model/voice data. BLAIR
prefers `bf_emma` after that local stack is ready.

The important direct and transitive components for the pinned
`kokoro-onnx==0.6.1` stack include:

| Component | Role | Upstream license |
| --- | --- | --- |
| [kokoro-onnx 0.6.1](https://github.com/thewh1teagle/kokoro-onnx) | ONNX TTS API | MIT |
| [Kokoro model assets](https://github.com/thewh1teagle/kokoro-onnx#license) | Neural model and voices consumed at runtime | Upstream describes the Kokoro model as Apache-2.0 |
| [phonemizer 3.4+](https://github.com/bootphon/phonemizer) | Grapheme-to-phoneme processing | GPL-3.0-or-later |
| [espeakng-loader](https://pypi.org/project/espeakng-loader/) | Supplies/loads the native eSpeak NG runtime | Loader metadata should be inspected; the bundled eSpeak NG runtime is GPL-3.0-or-later |
| [eSpeak NG](https://github.com/espeak-ng/espeak-ng) | Phonemization engine | GPL-3.0-or-later |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) | Model inference | MIT |
| [NumPy](https://github.com/numpy/numpy) | Numeric arrays | BSD-3-Clause |

Package managers can add platform-specific dependencies. The installed package
metadata and license files are authoritative for a particular environment.

The release helper writes PCM WAV through Python's standard `wave` module and
NumPy; SoundFile/libsndfile is not a BLAIR dependency.

## Distribution boundary

Installing GPL software for local use and redistributing a bundle that contains
it are different activities. BLAIR's core archive deliberately does not relabel,
vendor, or redistribute the optional Kokoro dependency environment under Apache-2.0.

If you redistribute BLAIR together with phonemizer, eSpeak NG, an
`espeakng-loader` wheel containing eSpeak NG, or another optional dependency, you
are responsible for the corresponding license texts, notices, source-code offers,
and other obligations. Running GPL components in a helper process does not by
itself remove redistribution obligations.

Likewise, verify the license and provenance of the exact model and voice files
you redistribute rather than assuming the BLAIR license applies to them.

## Release audit

Before publishing a bundle that includes optional voice software:

1. Capture the exact resolved dependency list and hashes.
2. Extract and review every wheel's `METADATA`, `LICENSE`, `COPYING`, and bundled
   native libraries.
3. Include all required third-party notices and license texts.
4. Confirm whether source or a written source offer is required for bundled GPL
   components.
5. Keep the Apache-only core artifact independently installable with
   `-Kokoro Skip`.

The links above are convenience references. Upstream package artifacts, not this
summary, control their licensing terms.
