#!/bin/bash
# ============================================================================
# TACo-ISP — W05 Execution Script: Stage Latency & AXI Timer Verification
# ============================================================================
# Thực thi pipeline và xuất dữ liệu phân tầng độ trễ ra CSV:
#   - raw_timestamps.csv: Dấu thời gian từng stage (t_sof, t_pre_done, t_dpu_start, ...)
#   - ba1_latency.csv: Bảng tổng kết p50/p95/p99 theo đúng schema SCHEMAS.md
# ============================================================================
set -euo pipefail

SW_DIR="${1:-$HOME/taco-isp/sw}"
BIN="$SW_DIR/build/baseline_ba"
OUT_DIR="${2:-$HOME/taco-isp/results/raw/W05_measurement}"
RAW_CSV="$OUT_DIR/raw_timestamps.csv"
SUMMARY_CSV="$OUT_DIR/ba1_latency.csv"
RUN_LOG="$OUT_DIR/run_w05.log"

mkdir -p "$OUT_DIR"

echo "============================================================" | tee "$RUN_LOG"
echo "  TACo-ISP W05: Test Hardware Clock & Stage Timestamps" | tee -a "$RUN_LOG"
echo "  Thời gian: $(date -Iseconds)" | tee -a "$RUN_LOG"
echo "============================================================" | tee -a "$RUN_LOG"

if [ ! -f "$BIN" ]; then
    echo "  [✗] Không tìm thấy binary $BIN. Vui lòng build trước." | tee -a "$RUN_LOG"
    exit 1
fi

INPUT_OPT=""
SAMPLE_RAW="results/raw/W02_camera/sample_1080p.raw"
if [ -f "$SAMPLE_RAW" ]; then
    INPUT_OPT="--input $SAMPLE_RAW"
elif [ -f "$HOME/taco-isp/$SAMPLE_RAW" ]; then
    INPUT_OPT="--input $HOME/taco-isp/$SAMPLE_RAW"
fi

echo ">>> Chạy benchmark baseline_ba với HwClock và --raw-csv..." | tee -a "$RUN_LOG"
"$BIN" \
    --mode ba1 \
    --frames 50 \
    --warmup 5 \
    --dummy \
    --led \
    --timer-freq 100000000 \
    --uio-timer "/dev/uio0" \
    --uio-gpio "/dev/uio1" \
    --raw-csv "$RAW_CSV" \
    --csv "$SUMMARY_CSV" \
    $INPUT_OPT 2>&1 | tee -a "$RUN_LOG"

if [ -f "$RAW_CSV" ] && [ -s "$RAW_CSV" ]; then
    LINES=$(wc -l < "$RAW_CSV")
    echo "  [✓] Đã tạo thành công raw timestamps CSV ($LINES dòng): $RAW_CSV" | tee -a "$RUN_LOG"
else
    echo "  [✗] Lỗi: Không sinh được file $RAW_CSV" | tee -a "$RUN_LOG"
    exit 1
fi

echo "" | tee -a "$RUN_LOG"
echo "  [✓] Hoàn tất kiểm thử HwClock & Stage Timestamps Tuần 5." | tee -a "$RUN_LOG"
