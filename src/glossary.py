import os
import sys
import re

DEFAULT_GLOSSARY_TEMPLATE = """# Shockwave Glossary / Custom replacement dictionary
# Format: pattern = replacement (case-insensitive, whole-word matching)
# Edit this file at any time; changes are reloaded automatically without restarting Shockwave.
# Blank lines and lines starting with # are ignored.

# --- 1. Projects and AI tools ---
shock wave = Shockwave
shockwave = Shockwave
tiger trade = Tiger.Trade
gemini = Gemini
whisper = Whisper
vosk = Vosk
py installer = PyInstaller
venv = venv

# --- 2. Development, languages, and infrastructure ---
docker = Docker
kubernetes = Kubernetes
git = Git
git hub = GitHub
git lab = GitLab
python = Python
see sharp = C#
type script = TypeScript
java script = JavaScript
react = React
postgres = PostgreSQL
redis = Redis
linux = Linux
windows = Windows
end point = endpoint
web socket = WebSocket
jason = JSON
pipe line = pipeline
pull request = Pull Request
merge = Merge
deploy = Deploy
backend = Backend
frontend = Frontend
full stack = Fullstack
api = API

# --- 3. Artificial intelligence and LLMs ---
prompt = prompt
llm = LLM
token = token
inference = Inference
embedding = Embedding
fine tuning = Fine-tuning
wake word = Wake Word

# --- 4. Trading, crypto, and market analysis ---
binance = Binance
bybit = Bybit
okx = OKX
tether = USDT
bitcoin = Bitcoin
ethereum = Ethereum
solana = Solana
stop loss = Stop Loss
take profit = Take Profit
limit order = limit order
order book = Order Book
footprint = Footprint
cumulative delta = cumulative delta
time frame = timeframe
liquidation = liquidation
volatility = volatility
"""

class GlossaryManager:
    def __init__(self, glossary_path=None):
        if glossary_path is None:
            if getattr(sys, 'frozen', False):
                exe_dir = os.path.dirname(sys.executable)
                self.glossary_path = os.path.join(exe_dir, "glossary.txt")
            else:
                self.glossary_path = os.path.abspath(
                    os.path.join(os.path.dirname(__file__), "..", "glossary.txt")
                )
        else:
            self.glossary_path = glossary_path

        self._last_mtime = None
        self._rules = []
        self._ensure_file_exists()
        self.reload()

    def _ensure_file_exists(self):
        """Creates a default glossary.txt template if the file doesn't exist yet."""
        if not os.path.exists(self.glossary_path):
            try:
                with open(self.glossary_path, "w", encoding="utf-8") as f:
                    f.write(DEFAULT_GLOSSARY_TEMPLATE)
            except Exception as e:
                print(f"[Glossary] Error creating default glossary file: {e}")

    def reload(self):
        """Parses glossary.txt and compiles regex patterns if the file was modified."""
        if not os.path.exists(self.glossary_path):
            self._rules = []
            return

        try:
            mtime = os.path.getmtime(self.glossary_path)
            if self._last_mtime is not None and mtime == self._last_mtime:
                return

            rules = []

            with open(self.glossary_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        pattern, replacement = line.split("=", 1)
                        pattern = pattern.strip()
                        replacement = replacement.strip()
                        if pattern and replacement:
                            rules.append((pattern, replacement))

            # Sort rules by pattern length descending to replace longer phrases first
            rules.sort(key=lambda r: len(r[0]), reverse=True)

            compiled_rules = []
            for pattern, replacement in rules:
                # Use unicode-safe word boundaries (?<!\w) and (?!\w)
                regex = re.compile(
                    r'(?<!\w)' + re.escape(pattern) + r'(?!\w)',
                    re.IGNORECASE | re.UNICODE
                )
                compiled_rules.append((regex, replacement))

            self._rules = compiled_rules
            self._last_mtime = mtime
            print(f"[Glossary] Loaded {len(self._rules)} rules from {self.glossary_path}")
        except Exception as e:
            print(f"[Glossary] Error reading glossary file: {e}")

    def apply(self, text: str) -> str:
        """Applies glossary substitution rules to text."""
        if not text:
            return text

        self.reload()
        if not self._rules:
            return text

        result = text
        for regex, replacement in self._rules:
            # Callable replacements are literal: backslashes are not regex commands.
            result = regex.sub(lambda match: replacement, result)

        return result
