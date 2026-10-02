---
trigger: always_on
description: TV2 role and project rules for TACo-ISP KV260 co-design project
---

# TACo-ISP Project Rules for TV2

1. **User Identity:** The user is **TV2** (Team Member 2), responsible for PS Software (Linux, VART zero-copy, C++17) and Measurement (Glass-to-decision latency, INA228 12V power logging, DDR APM, Paper A experiments).
2. **Hardware Environment:** AMD Kria KV260, IMX219 J9 CSI-2 camera, DPUCZDX8G v4.1 (Vitis AI 3.0), Linux Ubuntu 22.04 / PetaLinux 2022.2 on Cortex-A53.
3. **Core Mandates:**
   - Zero-copy VART handshake: `TensorBuffer::data_phy()` -> AXI4-Lite `dst` of `s2t_top` -> `ap_done` -> `execute_async`.
   - Never fabricate or hardcode numbers: all published data must come from real KV260 hardware execution via `analysis/make_tables.py`.
   - Never edit register values by hand: always generate using `twin/params.py` or `tools/make_default_regs.py`.
   - TV2 board time slot: Afternoon session.
   - Refer to [AGENTS.md](file:///d:/2026/TACo-ISP/AGENTS.md) for complete 65-week schedule, milestones G0-G6, and source tree mappings.
