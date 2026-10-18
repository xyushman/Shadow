# Feature Backlog

Ideas and potential improvements, roughly grouped. Not a committed roadmap.

## Answer assistance

- Real-time question detection and extraction (OCR from screen), combined with vision and STT
- Answer generation with context (session type, job profile, coding vs MCQ)
- Multi-model fallback (Gemini, Cerebras, Groq, OpenRouter)
- Code completion and explanation (syntax, complexity)
- Step-by-step solutions for DSA problems
- MCQ elimination and reasoning
- Aptitude and reasoning helpers
- System design explanations
- Behavioral answer templates

## Stealth and control

- Invisible window (`WDA_EXCLUDEFROMCAPTURE`) — implemented
- Click-through peek (`Alt+Z`) and ghost mode — implemented
- Hide from taskbar and title scrubbing — implemented
- Auto-hide when the interview starts
- Minimal hotkeys
- No visible overlays
- Avoid UI blur issues

## Input and automation

- Screenshot queue and auto-capture (`Alt+S` exists; consider auto-trigger on change)
- Clipboard read (paste question) — implemented
- Text injection (not safe in many OAs)
- Key remapping (avoid)
- Quick reply snippets
- Predefined templates per company or session type

## Session and OA-specific

- Tab monitoring (detect OA platform URLs)
- Timer awareness
- Multiple question handling
- Auto-save context and resume session — implemented
- Per-session memory
- Answer comparison
- Remote code runner (risky)
- Originality hints for answers

## UX improvements

- Minimal floating panel (draggable, hideable)
- Answer view: clean markdown with a copy button
- Concise vs detailed answer toggle — implemented
- Voice commands (`Alt+M` mute, etc.)
- Dark and light themes
- Monospace/code theme
- Collapsible sections
- Progress indicators

## Footprint and detection considerations

- Limit CPU and network spikes
- Throttle updates
- Avoid window focus changes
- Zero UI flashes
- Disable devtools logging in production
- Consider a system tray icon
- Keep the footprint small

## Quick wins

- Auto-start audio and screen share when the interview starts (no manual prompts) — main gap
- Backend audio capture (no browser audio-share badge) — implemented
- Auto-capture screenshots on question change (interval or vision trigger)
- Auto-answer mode with review before paste
- Answer history — implemented
- One-click copy answer
- Compact UI for small screen areas
