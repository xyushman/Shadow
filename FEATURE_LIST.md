# Feature Backlog

Ideas and potential improvements. Not a committed roadmap.

## Priority order

Highest priority first, weighted for customer ease (setup friction, daily friction,
reliability).

| # | Feature | Effort | Why |
|---|---|---|---|
| 1 | Remember window state (position, size, opacity, theme) | S | Every session starts wrong otherwise; trivial to build, felt daily |
| 2 | Rebindable hotkeys + conflict detection | M | Global `Alt+...` clashes with other apps; biggest daily friction |
| 3 | One-click installer + auto-update | L | Python/venv is the #1 setup barrier for non-technical users |
| 4 | Onboarding "Test key" per provider (live call) | S | Kills the most common "it doesn't work" support case |
| 5 | Clipboard capture hotkey (auto-detect question) | S | Core ease workflow; `/api/clipboard` already exists |
| 6 | Copy answer + per-code-block copy buttons | S | Immediate, cheap, high-value |
| 7 | Provider health dashboard (latency/status) | M | Explains slow or failed answers without guesswork |
| 8 | Audio device picker + input level meter (+ echo cancellation) | M | "No audio" is the second-biggest support driver |
| 9 | Resume/JD import (PDF/DOCX parse) | M | Removes tedious copy-paste setup |
| 10 | Answer actions (regenerate, shorten/expand, ELI5) | M | Improves answer quality without re-asking |
| 11 | Transcript export + post-session summary | M | Clear post-session value; review and study |
| 12 | History search + pin/favorite | S | Scales once history grows |
| 13 | Mock/preview mode before a real session | M | Builds confidence; catches misconfig early |
| 14 | Profile save/load (multiple personas) | M | Repeat users reuse contexts |
| 15 | Token/cost meter per session | S | Keeps users inside free-tier limits |
| 16 | Templates per company/round | M | Faster, more relevant answers |
| 17 | Auto-save/resume session | M | Reliability after a crash or restart |
| 18 | Themes + font size/zoom | S | Accessibility and comfort |
| 19 | System tray icon (show/hide/quit) | S | Conventional, low-cost polish |
| 20 | Uncertainty indicator | M | Guards against reading a bad answer aloud |
| 21 | Session recording | M | Nice-to-have; overlaps with export |
| 22 | Opt-in crash/error reporting | S | Cuts support load long-term |

Effort: S = small, M = medium, L = large.

## Reference by area

The same ideas grouped by theme, including items already shipped.

### Answer assistance

- Real-time question detection and extraction (OCR from screen), combined with vision and STT
- Answer generation with context (session type, job profile, coding vs MCQ)
- Multi-model fallback (Gemini, Cerebras, Groq, OpenRouter) — implemented
- Code completion and explanation (syntax, complexity)
- Step-by-step solutions for DSA problems
- MCQ elimination and reasoning
- Aptitude and reasoning helpers
- System design explanations
- Behavioral answer templates

### Stealth and control

- Invisible window (`WDA_EXCLUDEFROMCAPTURE`) — implemented
- Click-through peek (`Alt+Z`) and ghost mode — implemented
- Hide from taskbar and title scrubbing — implemented
- Auto-hide when the interview starts
- Minimal hotkeys
- No visible overlays
- Avoid UI blur issues

### Input and automation

- Screenshot queue and auto-capture (`Alt+S` exists; consider auto-trigger on change)
- Clipboard read (paste question) — implemented
- Text injection (not safe in many OAs)
- Key remapping (avoid)
- Quick reply snippets
- Predefined templates per company or session type

### Session and OA-specific

- Tab monitoring (detect OA platform URLs)
- Timer awareness
- Multiple question handling
- Auto-save context and resume session — implemented
- Per-session memory
- Answer comparison
- Remote code runner (risky)
- Originality hints for answers

### UX improvements

- Minimal floating panel (draggable, hideable)
- Answer view: clean markdown with a copy button — partially implemented
- Concise vs detailed answer toggle — implemented
- Voice commands (`Alt+M` mute, etc.)
- Dark and light themes
- Monospace/code theme
- Collapsible sections
- Progress indicators

### Footprint and detection considerations

- Limit CPU and network spikes
- Throttle updates
- Avoid window focus changes
- Zero UI flashes
- Disable devtools logging in production
- Keep the footprint small

### Quick wins

- Auto-start audio and screen share when the interview starts (no manual prompts) — main gap
- Backend audio capture (no browser audio-share badge) — implemented
- Auto-capture screenshots on question change (interval or vision trigger)
- Auto-answer mode with review before paste
- Answer history — implemented
- One-click copy answer
- Compact UI for small screen areas
