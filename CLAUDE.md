# CLAUDE.md - TACo-ISP KV260 Co-Design Project
User: **TV2** (PS Software & Measurement Lead)
See full details in [AGENTS.md](file:///d:/2026/TACo-ISP/AGENTS.md).

## Core Directives for TV2
- Focus: `sw/common/`, `sw/app/`, `sw/controller/`, `measure/`, `experiments/`, `analysis/`
- Hardware: AMD Kria KV260, IMX219, DPU B4096 (Vitis AI 3.0), Linux Cortex-A53
- Key tasks: VART zero-copy pipeline, UIO drivers, LED glass-to-decision latency, INA228 12V 1kHz power logging, Paper A evaluation & tables.
- Board schedule: Afternoon slot.
- Strictly adhere to bit-exact verification, auto-generated register files, and hardware measurement reproducibility.
