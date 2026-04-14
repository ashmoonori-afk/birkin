# Birkin Development Environment Setup

This guide verifies and sets up a complete development environment for the Birkin repository.

**Status:** Development environment verification for Birkin (forked from Birkin)

---

## Quick Status Check

Run this to verify your environment:

```bash
./scripts/verify_dev_env.sh
```

Or manually check:

```bash
python3 --version  # Need 3.11+
node --version     # Have: v25.8.1 ✓
npm --version      # For web apps
git --version      # Need: with --recurse-submodules
uv --version       # Fast Python package manager (optional but recommended)
```

---

## Requirements

### Required

| Tool | Minimum | Recommended | Why |
|------|---------|-------------|-----|
| **Python** | 3.11 | 3.13 | Core agent runtime |
| **Node.js** | 18+ | 20+ | Browser tools, web apps |
| **Git** | 2.28 | latest | Submodule support |

### Optional but Recommended

| Tool | Why |
|------|-----|
| **uv** | 10x faster dependency management than pip |
| **direnv** | Auto-loads .envrc for environment vars |
| **Docker** | Containerized development, testing |

---

## Installation Steps

### 1. Install Python 3.11+ (if needed)

**macOS (using Homebrew):**
```bash
brew install python@3.11
# Verify
python3.11 --version
```

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install python3.11 python3.11-venv python3.11-dev
```

**Windows (PowerShell):**
```powershell
# Download from https://www.python.org/downloads/
# OR use winget:
winget install Python.Python.3.11
```

### 2. Clone Repository with Submodules

```bash
git clone --recurse-submodules https://github.com/MoonGwanghoon/birkin.git
cd birkin
```

If you already cloned without `--recurse-submodules`:
```bash
git submodule update --init --recursive
```

### 3. Create Virtual Environment

**Using uv (recommended):**
```bash
# Install uv first: https://docs.astral.sh/uv/
uv venv venv --python 3.11
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

**Using Python's stdlib:**
```bash
python3.11 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 4. Install Dependencies

**Option A: Full development setup (recommended)**
```bash
pip install -e ".[dev]"
```

**Option B: All extras (for testing all features)**
```bash
pip install -e ".[all,dev]"
```

**Option C: Minimal setup (core only)**
```bash
pip install -e "."
```

For web apps (TypeScript, React):
```bash
npm install
```

### 5. Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit .env and add your API keys
# Required at minimum:
# - OPENROUTER_API_KEY or ANTHROPIC_API_KEY
# - OPENAI_API_KEY (if using OpenAI models)
# - Other optional: EXA_API_KEY, FAL_API_KEY, etc.

nano .env  # or your preferred editor
```

### 6. Setup Configuration Directory

```bash
mkdir -p ~/.birkin/{cron,sessions,logs,memories,skills}
mkdir -p ~/.birkin/tmp

# Create config (if not using global .env)
cp cli-config.yaml.example ~/.birkin/config.yaml
```

### 7. Verify Installation

```bash
# Test Python agent
birkin-agent --help

# Test legacy CLI (if needed)
birkin --help

# Run doctor to check setup
python -c "from agent.tools.terminal import Terminal; print('✓ Agent imports work')"

# Check pytest
pytest --version

# Check linter
ruff --version
```

---

## Troubleshooting

### Python 3.11+ not found

**Problem:** "python3.11: command not found" or "Python 3.11+ is required"

**Solutions:**

1. **Check installed versions:**
   ```bash
   python3 --version
   python3.11 --version
   ls /usr/bin/python*  # Linux/macOS
   ```

2. **Install missing version:**
   - macOS: `brew install python@3.11`
   - Ubuntu: `sudo apt install python3.11`
   - Windows: Download from python.org or use winget

3. **Use uv to install Python:**
   ```bash
   uv venv venv --python 3.11  # uv installs Python automatically
   ```

### Virtual environment not activating

**Problem:** Commands still use system Python instead of venv

**Solution:**
```bash
# Make sure you've activated the venv
source venv/bin/activate  # macOS/Linux
# OR
venv\Scripts\activate  # Windows PowerShell

# Verify venv is active (should show venv in prompt)
which python  # Should show path/to/birkin/venv/bin/python
```

### Submodules not initialized

**Problem:** Empty directories in `environments/`, `tinker/`, etc.

**Solution:**
```bash
git submodule update --init --recursive
git submodule update --remote  # Update to latest
```

### Import errors after installing dependencies

**Problem:** `ModuleNotFoundError` when running agent

**Solution:**
```bash
# Make sure venv is activated
source venv/bin/activate

# Reinstall in editable mode
pip install -e ".[dev]"

# Or clear and reinstall
pip uninstall birkin-agent -y
pip install -e ".[dev]"
```

### Tests fail after setup

**Problem:** `pytest` fails to import modules

**Check:**
```bash
# Ensure venv is active
which pytest

# Run tests with verbose output
pytest tests/ -v --tb=short

# If import issues:
python -m pytest tests/ -v
```

---

## Development Commands

### Running the Agent

```bash
# Interactive CLI
birkin

# Single query
birkin-agent -q "What is 2+2?"

# With specific model
birkin-agent -q "Hello" -m anthropic/claude-opus-4.6
```

### Running Tests

```bash
# All tests
pytest

# Specific test file
pytest tests/test_terminal.py -v

# With coverage
pytest --cov=agent tests/

# Exclude integration tests (requires API keys)
pytest -m "not integration"
```

### Code Quality

```bash
# Lint
ruff check .

# Format
ruff format .

# Type check (if mypy is installed)
mypy agent/
```

### Web Apps

```bash
# Install Node dependencies
npm install

# Dev server (if configured)
npm run dev

# Build (if configured)
npm run build

# Type check TypeScript
npm run type-check
```

---

## Enabling direnv (Optional)

Direnv automatically loads `.envrc` when entering the directory:

```bash
# Install direnv: https://direnv.net/

# Enable in this repo
direnv allow

# The venv will auto-activate when you cd into birkin/
```

The `.envrc` currently contains:
```
use flake
```

You can extend it to auto-activate the venv:
```bash
cat >> .envrc << 'EOF'

# Auto-activate venv
if [ -d "venv" ]; then
  source venv/bin/activate
fi
EOF

direnv allow
```

---

## Project Structure

```
birkin/
├── agent/                  # Core agent implementation
├── tools/                  # Tool implementations (terminal, browser, etc.)
├── birkin_cli/             # CLI command implementations
├── environments/           # RL training environments (Atropos integration)
├── web/                    # Web UI (TypeScript/React)
├── website/                # Marketing website
├── tests/                  # Test suite
├── pyproject.toml          # Python dependencies & config
├── package.json            # Node.js dependencies (if web enabled)
├── .env.example            # Environment template
├── .envrc                  # direnv configuration
├── setup-birkin.sh         # Automated setup script
└── CONTRIBUTING.md         # Detailed contribution guide
```

---

## Next Steps

1. **Read CONTRIBUTING.md** — Architecture overview and contribution guidelines
2. **Run the agent** — `birkin-agent -q "Hello"`
3. **Explore tools** — Check `tools/` for available capabilities
4. **Read AGENTS.md** — Agent concepts and configuration
5. **Write your first skill** — See `skills/` directory

---

## Getting Help

- **Setup issues:** Check [Troubleshooting](#troubleshooting) above
- **Architecture questions:** See [CONTRIBUTING.md](CONTRIBUTING.md)
- **Agent concepts:** See [AGENTS.md](AGENTS.md)
- **Tool documentation:** See `tools/README.md`
- **Community:** Nous Research Discord

---

## Verification Checklist

Before claiming your setup is complete:

- [ ] Python 3.11+ installed and in PATH
- [ ] Virtual environment created and activated
- [ ] Dependencies installed (`pip install -e ".[dev]"`)
- [ ] `.env` file exists with API keys
- [ ] `birkin-agent --help` works
- [ ] `pytest --version` works
- [ ] `ruff --version` works
- [ ] Can import agent: `python -c "from agent.tools.terminal import Terminal"`
- [ ] Tests pass: `pytest tests/ -m "not integration"`

---

**Last Updated:** 2026-04-15
**Birkin Version:** 0.1.0 (forked from Birkin)
