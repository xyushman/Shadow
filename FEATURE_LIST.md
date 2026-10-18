# OA/Interview Cheating Features Ideas
## Core Answer Assistance
- Real-time question detection/extraction (OCR from screen) - matches vision+STT
- Answer generation with context (session type, job profile, coding vs MCQ)
- Multi-model fallback (Gemini/Cerebras/Groq/OpenRouter)
- Code completion/explanation (syntax, complexity)
- Step-by-step solutions for DSA problems
- MCQ elimination/reasoning
- Aptitude/reasoning helpers
- System design explanations
- Behavioral answer templates

## Stealth & Control
- Invisible window (WDA_EXCLUDEFROMCAPTURE) - already have
- Click-through peek (Alt+Z), ghost mode
- Hide from taskbar, title scrubbing
- Auto-hide on interview start
- Hotkeys minimal
- No visible overlays
- Avoid UI blur issues

## Input/Automation
- Screenshot queue/auto-capture? Alt+S exists, auto trigger on change?
- Clipboard read (paste question)
- Text injection? (not safe in many OAs)
- Key remapping (avoid)
- Quick reply snippets
- Predefined templates per company/type

## Multi-Tasking/OA Specific
- Tab monitoring (detect OA platform URLs)
- Timer awareness
- Multiple question handling
- Auto-save context
- Resume session
- Per-session memory
- Answer comparison
- Code runner? (remote) but risky
- Plagiarism avoidance hints
- Type=thought suppression in answers

## UX Improvements (also relates to UI redesign)
- Minimal floating panel (draggable, hideable)
- Answer view: clean markdown, copy button
- Suggested answer (concise vs detailed)
- Voice commands (Alt+M mute etc)
- Dark/light themes
- Monospace/code theme
- Collapsible sections
- Progress indicators

## Anti-Detection Ideas
- Limit CPU/network spikes
- Throttled updates
- Avoid window focus changes
- Zero UI flashes
- Disable devtools logging in prod
- Use system tray? maybe not needed
- Keep footprint small

## Quick Wins
- Auto-start audio+screen share on interview start (no manual prompts) - main issue
- Backend audio capture (no browser audio share badge)
- Auto-capture screenshots on question change (interval/vision trigger)
- "Auto-answer" mode with review before paste
- Answer history
- One-click copy answer
- Compact UI for small screen areas
