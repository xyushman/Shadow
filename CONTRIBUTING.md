# Contributing to Nyx

Thanks for your interest in contributing.

## Quick start

```bash
# 1. Fork and clone
git clone https://github.com/YOUR_USERNAME/Shadow.git
cd Shadow

# 2. Create a virtual environment
python -m venv venv
venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy config templates
copy .env.example .env
copy ai_providers.example.json ai_providers.json

# 5. Add your API keys to .env and ai_providers.json

# 6. Run
python main.py
```

## How to contribute

### Reporting a bug

1. Search existing issues first to avoid duplicates.
2. Open an issue with:
   - A descriptive title
   - Steps to reproduce
   - Expected and actual behavior
   - Terminal or console output
   - Your OS and Python version

### Requesting a feature

Open an issue describing the use case, your proposed solution, and any
alternatives you considered.

### Submitting a pull request

1. Fork the repository.
2. Create a branch from `main`:

   ```bash
   git checkout -b feature/your-feature-name
   ```

3. Make your changes with focused, atomic commits.
4. Test your changes locally. For changes to the web UI's markdown or math
   rendering, run the JavaScript tests (Node 20+):

   ```bash
   npm install
   npm test
   ```

   Run the Python tests with:

   ```bash
   venv\Scripts\python.exe -m unittest discover -s tests/python
   ```

5. Push the branch and open a pull request.

## Project structure

```
Shadow/
├── main.py                 # App entry point: FastAPI server + pywebview
├── window_manager.py       # Stealth mode, hotkeys, Win32 integration
├── api/                    # FastAPI route handlers
├── core/                   # Core logic and configuration
├── services/               # AI providers, Deepgram, vision processing
├── web/                    # Frontend: HTML/CSS/JS served by pywebview
├── tests/                  # Python and JavaScript tests
├── .env                    # Environment variables (not committed)
├── ai_providers.json       # AI provider config (not committed)
├── run.bat                 # Automated setup and launch script
└── silent_run.vbs          # Invisible launch (no terminal window)
```

## Areas that need help

| Area | Description |
|---|---|
| Linux support | Port the Win32 stealth APIs to X11/Wayland equivalents |
| macOS support | Port the Win32 stealth APIs to Cocoa/AppKit |
| AI providers | Add support for additional LLM providers |
| UI/UX | Improve the overlay interface and theming |
| Documentation | Setup guides and tutorials |
| Testing | Unit tests, integration tests, CI |
| Localization | Multi-language support for the UI |

## Code style

- **Python**: follow PEP 8.
- **JavaScript**: vanilla JS, no frameworks in the frontend.
- **CSS**: vanilla CSS, no preprocessors.
- **Naming**: snake_case for Python, camelCase for JavaScript.
- **Comments**: explain why, not what.

## Notes

- Never commit secrets. `.env` and `ai_providers.json` are git-ignored.
- Test stealth features on Windows 10/11 before submitting stealth-related PRs.
- Keep pull requests focused: one feature or fix per PR.

## Questions

Open a GitHub issue or start a discussion.
