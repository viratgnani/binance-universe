"""Fast data audit using file sizes and sampled candle parsing."""
from pathlib import Path
import json

ohlcv_dir = Path("data/ohlcv")
files = sorted(ohlcv_dir.glob("*/1m/*.jsonl"))
print(f"Total JSONL files: {len(files)}")

# Sample first file structure
f0 = files[0]
lines0 = f0.read_text(encoding="utf-8").strip().split("\n")
c0 = json.loads(lines0[0])
print(f"Candle keys: {list(c0.keys())}")
print(f"Sample: {lines0[0][:180]}")

# Use file size to estimate candle count (much faster than reading all lines)
# Measure bytes/candle ratio on a sample of 10 files
sample_files = files[::len(files)//10][:10]
total_sample_bytes = 0
total_sample_lines = 0
for sf in sample_files:
    content = sf.read_text(encoding="utf-8")
    lines = [l for l in content.strip().split("\n") if l.strip()]
    total_sample_bytes += sf.stat().st_size
    total_sample_lines += len(lines)

bytes_per_candle = total_sample_bytes / total_sample_lines if total_sample_lines else 250
print(f"\nEstimated bytes/candle: {bytes_per_candle:.1f}")

# Total storage
total_bytes = sum(f.stat().st_size for f in files)
print(f"Total storage (GB): {total_bytes / 1e9:.2f}")

estimated_candles = int(total_bytes / bytes_per_candle)
print(f"Estimated total candles: {estimated_candles:,}")

# Per-symbol file counts and sizes
sym_files: dict[str, list] = {}
for f in files:
    sym = f.parts[-3]
    sym_files.setdefault(sym, []).append(f)

print(f"\nUnique symbols: {len(sym_files)}")

# Per-symbol estimated candle count
sym_estimated = {}
for sym, flist in sym_files.items():
    sym_bytes = sum(f.stat().st_size for f in flist)
    sym_estimated[sym] = int(sym_bytes / bytes_per_candle)

# Distribution
counts = sorted(sym_estimated.values())
print(f"Min est candles/symbol: {counts[0]:,}")
print(f"Max est candles/symbol: {counts[-1]:,}")
print(f"Median est candles/symbol: {counts[len(counts)//2]:,}")
print(f"Symbols >= 500k est candles: {sum(1 for c in counts if c >= 500000)}")
print(f"Symbols < 50k est candles: {sum(1 for c in counts if c < 50000)}")

# Sample timestamps from first/last file per symbol (fast)
print("\nChecking timestamp range from sampled symbols...")
first_ts = None
last_ts = None
for sym, flist in list(sym_files.items())[:50]:  # sample 50 symbols
    f_first = flist[0]
    f_last = flist[-1]
    try:
        line0 = f_first.read_text(encoding="utf-8").strip().split("\n")[0]
        t0 = json.loads(line0).get("open_time", "")
        lines_last = f_last.read_text(encoding="utf-8").strip().split("\n")
        t1 = json.loads(lines_last[-1]).get("open_time", "")
        if t0 and (first_ts is None or t0 < first_ts): first_ts = t0
        if t1 and (last_ts is None or t1 > last_ts): last_ts = t1
    except: pass

print(f"Earliest open_time (sample): {first_ts}")
print(f"Latest open_time (sample):   {last_ts}")
print("\nAudit complete.")
