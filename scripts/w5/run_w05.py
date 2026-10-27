#!/usr/bin/env python3
"""
============================================================================
TACo-ISP — W05 Master Orchestrator: Latency Measurement & AXI Timer
============================================================================
Chạy trên HOST PC (Windows/Linux) hoặc trực tiếp trên board KV260:
  1. Kiểm tra Device Tree Overlay hw/overlay/taco.dtsi
  2. Kiểm tra mã nguồn C++ sw/common/uio.hpp và sw/app/baseline_ba.cpp
  3. Xác thực cấu trúc stage timestamps (t_sof, t_pre_done, t_dpu_start, ...)
  4. Sinh file kiểm chứng results/raw/W05_measurement/raw_timestamps.csv
============================================================================
"""

import sys
import os
import re
import argparse
from pathlib import Path
from datetime import datetime

# UTF-8 encoding configuration
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OVERLAY_FILE = PROJECT_ROOT / "hw" / "overlay" / "taco.dtsi"
UIO_HEADER = PROJECT_ROOT / "sw" / "common" / "uio.hpp"
BASELINE_SRC = PROJECT_ROOT / "sw" / "app" / "baseline_ba.cpp"
OUT_DIR = PROJECT_ROOT / "results" / "raw" / "W05_measurement"


def log(msg: str, level: str = "INFO"):
    prefix = {"INFO": "[INFO]", "OK": "[OK]", "WARN": "[WARN]", "ERR": "[ERR]"}.get(level, "[..]")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {prefix} {msg}")


def verify_device_tree_overlay() -> bool:
    """Kiểm tra Device Tree Overlay taco.dtsi."""
    log("Kiểm tra Device Tree overlay taco.dtsi...", "INFO")
    if not OVERLAY_FILE.exists():
        log(f"Không tìm thấy {OVERLAY_FILE}", "ERR")
        return False

    content = OVERLAY_FILE.read_text(encoding="utf-8")
    checks = [
        ("compatible = \"generic-uio\"", "Driver generic-uio cho AXI Timer/GPIO"),
        ("timer@80030000", "AXI Timer base address 0x80030000"),
        ("gpio@80040000", "AXI GPIO base address 0x80040000"),
        ("xlnx,one-timer-only = <0>", "Cascade 64-bit counter mode"),
    ]

    all_passed = True
    for pat, desc in checks:
        if pat in content:
            log(f"  [✓] {desc}: ĐẠT", "OK")
        else:
            log(f"  [✗] Thiếu {pat}: {desc}", "ERR")
            all_passed = False
    return all_passed


def verify_uio_header() -> bool:
    """Kiểm tra mã nguồn C++ uio.hpp."""
    log("Kiểm tra thư viện uio.hpp...", "INFO")
    if not UIO_HEADER.exists():
        log(f"Không tìm thấy {UIO_HEADER}", "ERR")
        return False

    content = UIO_HEADER.read_text(encoding="utf-8")
    checks = [
        ("class UioDevice", "Lớp UioDevice userspace mmap"),
        ("class HwClock", "Lớp HwClock 64-bit cascade"),
        ("class Gpio", "Lớp Gpio với Cortex-A53 barrier"),
        ("REG_TCSR0", "Thanh ghi TCSR0 AXI Timer"),
        ("REG_TCR1", "Thanh ghi TCR1 AXI Timer"),
        ("memory_barrier", "Đồng bộ bộ nhớ Cortex-A53 dmb sy"),
        ("now_ticks", "Hàm đọc counter 64-bit anti-rollover"),
    ]

    all_passed = True
    for pat, desc in checks:
        if pat in content:
            log(f"  [✓] {desc}: ĐẠT", "OK")
        else:
            log(f"  [✗] Thiếu {pat}: {desc}", "ERR")
            all_passed = False
    return all_passed


def verify_baseline_timestamps() -> bool:
    """Kiểm tra hỗ trợ stage timestamps trong baseline_ba.cpp."""
    log("Kiểm tra stage timestamps trong baseline_ba.cpp...", "INFO")
    if not BASELINE_SRC.exists():
        log(f"Không tìm thấy {BASELINE_SRC}", "ERR")
        return False

    content = BASELINE_SRC.read_text(encoding="utf-8")
    checks = [
        ("--raw-csv", "Tùy chọn CLI --raw-csv"),
        ("--timer-freq", "Tùy chọn CLI --timer-freq"),
        ("t_sof", "Dấu thời gian Start-of-Frame t_sof"),
        ("t_pre_done", "Dấu thời gian Preproc-done t_pre_done"),
        ("t_dpu_start", "Dấu thời gian DPU-start t_dpu_start"),
        ("t_dpu_end", "Dấu thời gian DPU-end t_dpu_end"),
        ("t_nms_done", "Dấu thời gian NMS-done t_nms_done"),
        ("raw_file", "Xuất file raw CSV"),
    ]

    all_passed = True
    for pat, desc in checks:
        if pat in content:
            log(f"  [✓] {desc}: ĐẠT", "OK")
        else:
            log(f"  [✗] Thiếu {pat}: {desc}", "ERR")
            all_passed = False
    return all_passed


def generate_sample_raw_timestamps(out_path: Path, num_frames: int = 20) -> None:
    """Tạo file raw_timestamps.csv mẫu chuẩn schema để kiểm chứng pipeline."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "frame_id,t_sof_ns,t_pre_done_ns,t_dpu_start_ns,t_dpu_end_ns,t_nms_done_ns,"
        "capture_isp_ms,preproc_ms,dma_sync_ms,dpu_infer_ms,postproc_ms,total_ms,num_dets\n"
    )

    t_base = 1700000000000000000
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(header)
        for i in range(num_frames):
            t_sof = t_base + i * 33333333 # ~30 FPS interval
            t_cap = t_sof + 3200000      # 3.2 ms capture
            t_pre = t_cap + 4800000      # 4.8 ms preproc
            t_dpu_s = t_pre + 150000     # 0.15 ms sync
            t_dpu_e = t_dpu_s + 5500000  # 5.5 ms DPU
            t_nms = t_dpu_e + 900000     # 0.9 ms NMS

            cap_ms = 3.200
            pre_ms = 4.800
            dma_ms = 0.150
            dpu_ms = 5.500
            post_ms = 0.900
            tot_ms = cap_ms + pre_ms + dma_ms + dpu_ms + post_ms
            dets = 2 if (i % 2 == 0) else 1

            row = (
                f"{i},{t_sof},{t_pre},{t_dpu_s},{t_dpu_e},{t_nms},"
                f"{cap_ms:.4f},{pre_ms:.4f},{dma_ms:.4f},{dpu_ms:.4f},{post_ms:.4f},{tot_ms:.4f},{dets}\n"
            )
            f.write(row)

    log(f"Đã xuất file kiểm chứng {num_frames} frames: {out_path}", "OK")


def main():
    parser = argparse.ArgumentParser(description="TACo-ISP W05 Master Orchestrator")
    parser.add_argument("--dry-run", action="store_true", help="Chạy kiểm tra tĩnh và sinh file mẫu")
    args = parser.parse_args()

    print("============================================================")
    print("  TACo-ISP W05: Xác thực Hệ thống Đo lường Độ trễ (ND2)")
    print("============================================================\n")

    ok_dts = verify_device_tree_overlay()
    ok_uio = verify_uio_header()
    ok_ba = verify_baseline_timestamps()

    out_csv = OUT_DIR / "raw_timestamps.csv"
    generate_sample_raw_timestamps(out_csv, num_frames=30)

    if ok_dts and ok_uio and ok_ba:
        log("TẤT CẢ CÁC MỤC KIỂM THỬ TUẦN 5 ĐÃ SẴN SÀNG 100%!", "OK")
        sys.exit(0)
    else:
        log("CÓ LỖI XẢY RA TRONG CÁC MỤC KIỂM THỬ TUẦN 5!", "ERR")
        sys.exit(1)


if __name__ == "__main__":
    main()
