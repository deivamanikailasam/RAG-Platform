# Model serving benchmarks

Machine: MacBook Pro M5 Max, 128 GB · mlx-lm <version> · macOS <version> · date <YYYY-MM-DD>

| Model | Prompt | TTFT (s) | ~tok/s | Peak memory (GB) | Notes |
|---|---|---|---|---|---|
| qwen-quality (27B 8-bit) | short | | | | |
| qwen-quality (27B 8-bit) | ~8k tokens | | | | |
| qwen-fast (35B-A3B 4-bit) | short | | | | |
| qwen-fast (35B-A3B 4-bit) | ~8k tokens | | | | |

Both loaded together: memory pressure = <green/yellow/red>, total used = <GB>.
Conclusion: <does the Step 3 budget hold? is the 24 GB container VM cap still right?>
