import subprocess
import sys

cmds = [
    ".venv\\Scripts\\python -m data_readiness report --symbols eligible_alts",
    ".venv\\Scripts\\python -m research_features generate --symbols eligible_alts --start 2024-09-01T00:00:00Z --end 2025-09-01T00:00:00Z",
    ".venv\\Scripts\\python -m indicators generate --symbols eligible_alts --indicator rsi --period 14 --start 2024-09-01T00:00:00Z --end 2025-09-01T00:00:00Z",
    ".venv\\Scripts\\python experiment_rsi.py"
]

for cmd in cmds:
    print(f"Running: {cmd}")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print(f"FAILED: {cmd}")
        sys.exit(result.returncode)
print("ALL DONE")
