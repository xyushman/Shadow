# Nyx

Nyx is a desktop AI assistant that runs as a small always-on-top overlay. It
transcribes system and microphone audio in real time, generates answers to
questions it hears, and analyzes screenshots of your screen. The window can be
excluded from screen capture and hidden from the taskbar, so it stays out of the
way of whatever you are doing.

The primary target is **Windows 10/11**. A macOS port is in progress on the
[`macos`](https://github.com/Rkcr7/Aura-AI/tree/macos) branch.

[![Windows 10/11](https://img.shields.io/badge/Windows-10%2F11-0078D6?style=flat&logo=windows&logoColor=white)](#requirements)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](#license)

## Features

- **Real-time transcription.** Deepgram speech-to-text with continuous streaming,
  capturing both the interviewer's questions and your own responses.
- **Answer generation.** Multi-provider LLM support (Cerebras, Groq, Gemini,
  OpenRouter) with primary/secondary models, automatic failover, and per-provider
  API key rotation.
- **Vision analysis.** Capture up to four screenshots, queue them, and process
  them in a batch. Content type (code, diagram, math, schema, plain text) is
  detected automatically and the analysis strategy adapts.
- **Overlay window.** Transparent, always-on-top, adjustable opacity, and
  optional click-through "ghost" mode.
- **Screen-capture exclusion.** On Windows the window uses
  `WDA_EXCLUDEFROMCAPTURE`, so it does not appear in screen recordings or shared
  screens. While hidden it is removed from the desktop entirely.
- **Taskbar/Alt+Tab immunity.** The window uses `WS_EX_TOOLWINDOW`, keeping it
  out of the taskbar and the Alt+Tab switcher.
- **Global hotkeys.** Every action can be triggered with a system-wide hotkey, so
  the overlay never needs focus.
- **Bring your own keys.** All supported providers offer free tiers. The project
  has no subscriptions or paid tiers.

## Requirements

| Requirement | Details |
|---|---|
| Operating system | Windows 10 or 11 (fully supported). macOS is a work-in-progress port on the [`macos`](https://github.com/Rkcr7/Aura-AI/tree/macos) branch. |
| Python | 3.8 or newer. On Windows, enable **Add Python to PATH** during installation. |
| Microphone | Any input device (built-in, headset, or USB). |
| Internet | Required for speech-to-text and LLM provider calls. |
| API keys | Deepgram plus at least one LLM provider. All free. |

## Installation

### Option A: Automated launcher (recommended)

Double-click `run.bat`. It checks for Python, creates the virtual environment,
installs/updates dependencies, and starts the app.

### Option B: Manual setup

```bash
git clone https://github.com/Rkcr7/Aura-AI
cd Aura-AI

python -m venv venv
venv\Scripts\activate

pip install -r requirements.txt
```

### Option C: Silent launch

Double-click `silent_run.vbs` to start the app with no visible terminal window.

## Configuration

### Environment (`.env`)

Copy `.env.example` to `.env` and fill in your values. At minimum, set the
Deepgram key. `run.bat` warns if `.env` is missing.

```env
# API keys
DEEPGRAM_API_KEY="your_deepgram_api_key"

# Logging
LOG_LEVEL=INFO                 # DEBUG, INFO, WARNING, ERROR
DEV_MODE=false                 # Verbose logging and developer shortcuts

# AI behaviour
TRACK_CANDIDATE_RESPONSES=true # Track what the candidate says
INCLUDE_CONVERSATION_HISTORY=true
MAX_CONVERSATION_HISTORY=24    # Past exchanges to include
GENERATE_FULL_ANSWERS=true     # Full answers vs. brief hints
PERSONALIZE_ANSWERS=true       # Tailor answers to your resume/JD

# Stealth
STEALTH_MODE=invisible         # invisible (hide-by-default) | blackout
STEALTH_PEEK_SECONDS=10        # Seconds an Alt+Z peek stays visible (0 = never hide)
SCREEN_SHARE_SCAN_INTERVAL_S=1.0

# Scrolling (Alt+Up / Alt+Down)
SCROLL_SPEED_PX=200            # Pixels per tick
SCROLL_INTERVAL_MS=50          # Milliseconds between ticks
```

Scroll speed presets:

| Feel | `SCROLL_SPEED_PX` | `SCROLL_INTERVAL_MS` |
|---|---|---|
| Slow and precise | `100` | `80` |
| Default | `200` | `50` |
| Fast scanning | `400` | `30` |

### AI providers (`ai_providers.json`)

Copy `ai_providers.example.json` to `ai_providers.json` and add your keys. This
file is git-ignored. The file is an array of provider objects, each with this
shape:

```jsonc
{
  "name": "Cerebras",
  "baseURL": "https://api.cerebras.ai/v1",
  "apiKey": "YOUR_KEY",                    // Single key (minimum)
  "apiKeys": ["KEY_1", "KEY_2"],           // Multiple keys for rotation
  "models": [
    { "modelName": "gpt-oss-120b", "description": "GPT-OSS 120B" }
  ],
  "visionModels": [
    { "modelName": "qwen-3.8-27b", "description": "Qwen 3.8 27B" }
  ],
  "supportsVision": true,
  "defaultModel": "gpt-oss-120b",
  "maxImages": 2
}
```

A single provider with one key is enough; additional keys per provider improve
resilience against rate limits. Providers marked `defaultPrimary` and
`defaultSecondary` are used first.

Pre-configured providers:

| Provider | Default role | Text models | Vision models | Notes |
|---|---|---|---|---|
| Gemini | Primary | Gemini 3.8 Flash, Gemini 4 Argon, 3.6 Flash, 3.5/3.1 Flash Lite | All Gemini models (up to 8 images) | Best vision accuracy |
| Cerebras | Secondary | GPT-OSS 120B, Qwen 3.8 27B | Qwen 3.8 27B (up to 2 images) | Fastest text and vision |
| Groq | Optional | GPT-OSS 120B, GPT-OSS 20B, Qwen 3.6 27B | Qwen 3.6 27B (paid tier) | Independent rate limits |
| OpenRouter | Optional | GPT-OSS 120B and Qwen 3.8 27B, routed to Cerebras/Groq | Routed to Cerebras | Gateway to additional models |

## Usage

1. Run the app (`run.bat`, `python main.py`, or `silent_run.vbs`).
2. Complete onboarding: profile, resume, job description, and AI models.
3. The pre-flight check validates microphone access, the backend, Deepgram, and
   each configured provider. Resolve any failures, then start the session.
4. During the session, use the global hotkeys below to control the overlay.

### Hotkeys

| Category | Hotkey | Action |
|---|---|---|
| Stealth and window | `Alt + Shift + S` | Activate proctoring stealth mode |
| | `Alt + Z` | Toggle window visibility |
| | `Alt + X` | Toggle ghost mode (click-through) |
| | `Alt + 1 / 2 / 3` | Set opacity to 40% / 70% / 100% |
| Window movement | `Alt + I` / `Alt + J` | Move window up / down |
| | `Alt + Left` / `Alt + Right` | Move window left / right |
| Scrolling | `Alt + Up` / `Alt + Down` | Scroll up / down (hold for continuous) |
| | `Home` / `End` | Jump to top / bottom |
| | `Escape` | Toggle reading mode (pause auto-scroll) |
| Vision | `Alt + V` | Toggle vision mode |
| | `Alt + S` | Capture screenshot (up to 4) |
| | `Alt + P` | Process the screenshot queue |
| | `Alt + R` | Clear the screenshot queue |
| | `Alt + T` | Cycle the vision model |
| AI and audio | `Alt + Q` | Switch to the primary model |
| | `Alt + W` | Switch to the secondary model |
| | `Alt + E` | Auto-select the fastest healthy provider |
| | `Alt + M` | Toggle microphone mute |
| | `Alt + U` | Universal pause/resume of AI processing |
| | `Alt + O` | Reset the session |

Scroll speed is configured with `SCROLL_SPEED_PX` and `SCROLL_INTERVAL_MS`.

## Architecture

Nyx runs a FastAPI server in a background thread and renders the UI in a
pywebview window. Window control, hotkeys, and screen-capture exclusion use the
Win32 API through `ctypes`.

| Component | Path | Role |
|---|---|---|
| Entry point | `main.py` | FastAPI + Uvicorn server, pywebview window, asyncio orchestration |
| Window manager | `window_manager.py` | Win32 stealth, global hotkeys, transparency, scrolling |
| WebSocket API | `api/websocket.py` | Real-time client/server event streaming |
| Config API | `api/config_api.py` | REST endpoints for settings, providers, transparency |
| Session manager | `api/session_manager.py` | Session lifecycle and state |
| LLM service | `services/llm_service.py` | Multi-provider AI with key rotation, failover, health checks |
| STT service | `services/stt_service.py` | Deepgram real-time transcription with auto-reconnect |
| Vision service | `services/vision_service.py` | Screenshot analysis with content-type detection |
| Context manager | `services/context_manager.py` | Profile, resume, JD, conversation history |
| Prompts | `core/prompts.py` | System prompts and coaching instructions |
| Config | `core/config.py` | Settings loaded from `.env` |
| Frontend | `web/` | HTML/CSS/JS with WebSocket streaming |

## Tech stack

| Layer | Technology |
|---|---|
| Runtime | Python 3.8+, asyncio |
| Web framework | FastAPI + Uvicorn |
| Desktop shell | pywebview |
| Speech-to-text | Deepgram SDK v3 |
| LLM clients | OpenAI-compatible SDK (Groq, Cerebras, Gemini, OpenRouter) |
| Global hotkeys | Win32 `RegisterHotKey` via ctypes |
| Win32 integration | ctypes (window management, screen-share detection) |
| Frontend | Vanilla HTML/CSS/JS |
| Config | pydantic-settings + python-dotenv |

## Obtaining API keys

All supported providers have free tiers. No credit card is required.

### Deepgram (required, speech-to-text)

| | |
|---|---|
| Sign up | [console.deepgram.com](https://console.deepgram.com/) |
| Free tier | $200 in credits (roughly 100+ hours of transcription) |

### Cerebras (recommended, fastest text)

| | |
|---|---|
| Sign up | [cloud.cerebras.ai](https://cloud.cerebras.ai/) |
| Free tier | Free API access, no credit card |
| Models | `gpt-oss-120b` (fastest text, default), `qwen-3.8-27b` (vision) |

### Groq (recommended, fast text and vision)

| | |
|---|---|
| Sign up | [console.groq.com](https://console.groq.com/) |
| Free tier | Generous rate limits, no credit card |
| Text models | `openai/gpt-oss-120b`, `openai/gpt-oss-20b` |
| Vision models | `qwen/qwen3.6-27b` (paid tier) |

### Gemini (recommended, best vision accuracy)

| | |
|---|---|
| Sign up | [aistudio.google.com](https://aistudio.google.com/) |
| Free tier | 15 requests/minute, no credit card |
| Vision models | `gemini-3.8-flash`, `gemini-4-argon`, `gemini-3.6-flash` |

### OpenRouter (optional gateway)

| | |
|---|---|
| Sign up | [openrouter.ai](https://openrouter.ai/) |
| Free tier | Many free models available |

### Multiple API keys

Multiple keys per provider are supported through the `apiKeys` array. Free tiers
apply per key, so adding two or three keys per provider raises the effective rate
limit and reduces interruptions. Nyx rotates between keys and fails over between
providers automatically.

## Troubleshooting

**Microphone not working**

1. Check Windows privacy settings: Settings, Privacy, Microphone.
2. Verify `DEEPGRAM_API_KEY` in `.env`.
3. Close other apps that hold the microphone (Zoom, Teams, and so on).
4. With `DEV_MODE=true`, check the browser console (F12) for errors.

**AI responses failing or slow**

1. Confirm the keys in `ai_providers.json` are not placeholders.
2. Press `Alt + E` to auto-select the best available model.
3. Add more keys to the `apiKeys` array; you may be hitting rate limits.
4. Check the terminal for error output.

**Vision analysis not working**

1. Configure a vision-capable provider (Gemini or Groq).
2. Enter vision mode (`Alt + V`) before capturing (`Alt + S`).
3. Process the queue with `Alt + P`.
4. Ensure `supportsVision: true` in the provider config.

**Window not visible**

1. Press `Alt + Z` to toggle visibility.
2. Press `Alt + 3` for full opacity.
3. Some fullscreen apps override always-on-top; use windowed mode.
4. Re-enable stealth with `Alt + Shift + S`.

**App will not start**

1. Use `run.bat`, which handles the virtual environment and dependencies.
2. Verify Python 3.8+ is installed and on `PATH`.
3. Recreate the environment: remove `venv`, then `python -m venv venv`.
4. Run `pip install -r requirements.txt` manually.

## Limitations and responsible use

- Stealth Mode relies on Windows APIs. Its behavior differs on other platforms
  and may be affected by fullscreen or hardware-accelerated capture.
- Transcription and answers depend on third-party services and network access.
  Validate generated answers before relying on them.
- You are responsible for complying with the laws, regulations, company policies,
  and exam rules that apply to you. Review your target company's or exam
  provider's policies before using Nyx. Nyx is intended to assist and augment
  your own knowledge, not to misrepresent your abilities.

## Documentation

| Document | Description |
|---|---|
| [PROCTORING_STEALTH_GUIDE.md](PROCTORING_STEALTH_GUIDE.md) | Detailed stealth-mode notes: capture protection and detection considerations |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. See [LICENSE](LICENSE).
