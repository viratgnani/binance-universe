import subprocess
import sys

def run_cmd(cmd, retry=1, proceed_on_fail=False):
    for attempt in range(retry):
        print(f"Running: {cmd} (Attempt {attempt+1})")
        result = subprocess.run(cmd, shell=True)
        if result.returncode == 0:
            return True
        print(f"Command failed with exit code {result.returncode}")
    if proceed_on_fail:
        print("Proceeding despite failure.")
        return False
    sys.exit(result.returncode)

# Try backfill up to 3 times due to intermittent network errors
run_cmd(".venv\\Scripts\\python -m data_readiness acquire --symbols eligible_alts --start 2024-09-01 --end 2025-09-01", retry=3, proceed_on_fail=True)

# Generate report
run_cmd(".venv\\Scripts\\python -m data_readiness report --symbols eligible_alts")

# Generate RSI
run_cmd(".venv\\Scripts\\python -m indicators generate --symbols eligible_alts --indicator rsi --period 14 --start 2024-09-01T00:00:00Z --end 2025-09-01T00:00:00Z")

# Run Experiment
run_cmd(".venv\\Scripts\\python experiment_rsi.py")
print("ALL DONE!")
