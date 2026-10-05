import os
import json
import shutil
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed

def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"FAILED: {cmd}")
        print(result.stderr)
    return result.returncode

def process_features(symbol: str):
    ohlcv_dir = Path(f"data/ohlcv/{symbol}/1m")
    if not ohlcv_dir.exists():
        return symbol, 0
        
    features_dir = Path(f"data/features/{symbol}")
    features_dir.mkdir(parents=True, exist_ok=True)
    
    total = 0
    for file in ohlcv_dir.glob("*.jsonl"):
        out_file = features_dir / file.name
        if out_file.exists() and out_file.stat().st_size > 0:
            total += 1440
            continue
            
        out_lines = []
        with open(file, "r") as f:
            for line in f:
                if not line.strip(): continue
                c = json.loads(line)
                open_time_str = c["open_time"]
                dt = datetime.fromisoformat(open_time_str.replace("Z", "+00:00"))
                ts = dt + timedelta(minutes=1)
                
                feat = {
                    "symbol": symbol,
                    "timestamp": ts.isoformat().replace("+00:00", "Z"),
                    "feature_version": "v1",
                    "mid_price": float(c["close"])
                }
                out_lines.append(json.dumps(feat) + "\n")
                
        with open(out_file, "w") as f:
            f.writelines(out_lines)
        total += len(out_lines)
        
    return symbol, total

def process_indicators(symbol: str):
    cmd = f".venv\\Scripts\\python -m indicators generate --symbols {symbol} --indicator rsi --period 14 --start 2024-09-01T00:00:00Z --end 2025-09-01T00:00:00Z"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return symbol, result.returncode, result.stderr

if __name__ == "__main__":
    sys.path.append(os.getcwd())
    from market_data.readiness import load_eligible_alt_symbols
    symbols = load_eligible_alt_symbols()
    excluded = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    symbols = [s for s in symbols if s not in excluded]
    
    # 1. Cleanup garbage
    print("Cleaning up garbage ELIGIBLE_ALTS directories...")
    shutil.rmtree("data/features/ELIGIBLE_ALTS", ignore_errors=True)
    shutil.rmtree("data/indicators/ELIGIBLE_ALTS", ignore_errors=True)
    
    # 2. Fast fill features
    print(f"Generating mid_price features for {len(symbols)} symbols...")
    with ProcessPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(process_features, s) for s in symbols]
        for i, f in enumerate(as_completed(futures)):
            sym, count = f.result()
            if i % 50 == 0:
                print(f"Features [{i}/{len(symbols)}]: {sym} -> {count} rows")
                
    # 3. Generate RSI indicators in parallel
    print(f"Generating RSI indicators in parallel...")
    failed = []
    with ProcessPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(process_indicators, s) for s in symbols]
        for i, f in enumerate(as_completed(futures)):
            sym, code, stderr = f.result()
            if code != 0:
                failed.append(sym)
                print(f"FAILED indicators for {sym}: {stderr}")
            if i % 50 == 0:
                print(f"Indicators [{i}/{len(symbols)}]: {sym} done.")
                
    if failed:
        print(f"Failed to generate indicators for: {failed}")
        sys.exit(1)
        
    # 4. Run experiment
    print("Running experiment_rsi.py...")
    ret = run_cmd(".venv\\Scripts\\python experiment_rsi.py")
    if ret == 0:
        print("ALL DONE SUCCESSFULLY.")
