#!/bin/bash
# ============================================================================
# TACo-ISP — W04 Execution Script: Milestone G0 Live Pipeline Run
# ============================================================================
# Cổng kiểm tra G0: Pipeline camera -> DPU chạy thông suốt trên KV260
#   1. Đảm bảo overlay DPU (kv260-smartcam) đã được nạp
#   2. Cấu hình pipeline camera Sony IMX219 (1080p RAW10 RGGB qua J9)
#   3. Dò tìm xmodel YOLOX-nano (hoặc chạy dummy emulation chuẩn thời gian)
#   4. Khởi chạy luồng suy luận liên tục và đo đạc thông lượng (FPS)
#   5. Ghi nhận kết quả vào g0_pipeline.csv và log chi tiết g0_run.log
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

SW_DIR="${SW_DIR:-$HOME/taco-isp/sw}"
if [ ! -d "$SW_DIR" ] && [ -d "$REPO_DIR/sw" ]; then
    SW_DIR="$REPO_DIR/sw"
fi
BIN_PATH="$SW_DIR/build/baseline_ba"
OUT_DIR="${3:-$HOME/taco-isp/results/raw/W04_g0}"
RUN_LOG="$OUT_DIR/g0_run.log"
CSV_PATH="$OUT_DIR/g0_pipeline.csv"
FRAMES="${1:-200}"
MODE="${2:-ba1}"

mkdir -p "$OUT_DIR"

echo "============================================================"
echo "  TACo-ISP W04: CỔNG KIỂM TRA G0 (Camera IMX219 -> DPU)"
echo "  Chế độ: $MODE | Số khung hình đo: $FRAMES"
echo "  Thời gian: $(date -Iseconds)"
echo "============================================================" | tee "$RUN_LOG"

# --- 1. Kiểm tra binary ---
if [ ! -f "$BIN_PATH" ] || [ ! -x "$BIN_PATH" ]; then
    echo "  [!] Binary chưa tồn tại: $BIN_PATH. Đang tiến hành biên dịch..." | tee -a "$RUN_LOG"
    if [ -f "$SCRIPT_DIR/01_build_w04.sh" ]; then
        bash "$SCRIPT_DIR/01_build_w04.sh" "$SW_DIR" "$OUT_DIR"
    else
        bash "$HOME/taco-isp/scripts/w4/01_build_w04.sh"
    fi
fi

# --- 2. Nạp Overlay DPU (kv260-smartcam) ---
echo "" | tee -a "$RUN_LOG"
echo ">>> [1/4] Kiểm tra và nạp overlay DPU (kv260-smartcam)..." | tee -a "$RUN_LOG"

# Kiểm tra DPU đã có sẵn trong phần cứng chưa (Base TRD Boot)
DPU_PRELOADED=0
if (command -v xdputil >/dev/null 2>&1 && (xdputil query 2>/dev/null || sudo -n xdputil query 2>/dev/null) | grep -q "DPUCZDX8G"); then
    echo "  [✓] DPU DPUCZDX8G đã nạp sẵn trong phần cứng (Base TRD Boot)." | tee -a "$RUN_LOG"
    DPU_PRELOADED=1
fi

set +o pipefail
CURRENT_APP=$( (xmutil listapps 2>/dev/null || sudo -n xmutil listapps 2>/dev/null) | awk '$NF != "-1" && $NF ~ /^[0-9]/ {print $1}' | head -n 1 || echo "")
set -o pipefail

if [ "$DPU_PRELOADED" -eq 1 ]; then
    echo "  [i] Bỏ qua xmutil loadapp vì DPU phần cứng đã sẵn sàng." | tee -a "$RUN_LOG"
elif [ "$CURRENT_APP" != "kv260-smartcam" ]; then
    if [ -n "$CURRENT_APP" ]; then
        echo "  Unload app hiện tại ($CURRENT_APP)..." | tee -a "$RUN_LOG"
        (sudo -n xmutil unloadapp 2>/dev/null || sudo xmutil unloadapp 2>/dev/null) || true
        sleep 1
    fi
    echo "  Load overlay DPU: kv260-smartcam" | tee -a "$RUN_LOG"
    if (xmutil listapps 2>/dev/null || sudo -n xmutil listapps 2>/dev/null) | grep -q "kv260-smartcam"; then
        sudo -n xmutil loadapp kv260-smartcam 2>&1 | tee -a "$RUN_LOG" || sudo xmutil loadapp kv260-smartcam 2>&1 | tee -a "$RUN_LOG"
    else
        set +o pipefail
        ALT_APP=$( (xmutil listapps 2>/dev/null || sudo -n xmutil listapps 2>/dev/null) | grep -E 'smartcam|aibox|benchmark|dpu|nlp' | awk '{print $1}' | head -n 1 || echo "")
        set -o pipefail
        if [ -n "$ALT_APP" ]; then
            echo "  [i] kv260-smartcam không có, nạp app DPU thay thế: $ALT_APP" | tee -a "$RUN_LOG"
            sudo -n xmutil loadapp "$ALT_APP" 2>&1 | tee -a "$RUN_LOG" || sudo xmutil loadapp "$ALT_APP" 2>&1 | tee -a "$RUN_LOG"
        else
            echo "  [!] Không tìm thấy overlay DPU trong xmutil listapps." | tee -a "$RUN_LOG"
        fi
    fi
    sleep 2
else
    echo "  [✓] Overlay kv260-smartcam đã nạp sẵn." | tee -a "$RUN_LOG"
fi

# --- 3. Dò tìm camera và cấu hình Media Controller ---
echo "" | tee -a "$RUN_LOG"
echo ">>> [2/4] Kiểm tra phần cứng camera IMX219 và pipeline Media Controller..." | tee -a "$RUN_LOG"

VIDEO_DEV=""
MEDIA_DEV=""
for m in /dev/media*; do
    if [ -e "$m" ] && (media-ctl -d "$m" -p 2>/dev/null || sudo -n media-ctl -d "$m" -p 2>/dev/null) | grep -i "imx219" > /dev/null; then
        MEDIA_DEV="$m"
        break
    fi
done

if [ -n "$MEDIA_DEV" ]; then
    echo "  [✓] Tìm thấy Media Device cảm biến IMX219: $MEDIA_DEV" | tee -a "$RUN_LOG"
    set +o pipefail
    IMX_ENTITY=$(media-ctl -d "$MEDIA_DEV" -p 2>/dev/null | grep -iE 'entity [0-9]+:.*imx219' | grep -v 'vcap' | sed -E 's/.*entity [0-9]+: ([^(]+) \(.*$/\1/' | head -n 1 | xargs || echo "")
    if [ -z "$IMX_ENTITY" ]; then
        IMX_ENTITY="imx219 2-0010"
    fi
    CSI_ENTITY=$(media-ctl -d "$MEDIA_DEV" -p 2>/dev/null | grep -iE 'entity [0-9]+:.*mipi_csi2_rx' | grep -v 'vcap' | sed -E 's/.*entity [0-9]+: ([^(]+) \(.*$/\1/' | head -n 1 | xargs || echo "")
    
    # Thiết lập độ phân giải 1080p RAW10 cho IMX219
    media-ctl -d "$MEDIA_DEV" -V "\"$IMX_ENTITY\":0 [fmt:SRGGB10_1X10/1920x1080 field:none]" 2>/dev/null || \
    sudo -n media-ctl -d "$MEDIA_DEV" -V "\"$IMX_ENTITY\":0 [fmt:SRGGB10_1X10/1920x1080 field:none]" 2>/dev/null || true
    if [ -n "$CSI_ENTITY" ]; then
        media-ctl -d "$MEDIA_DEV" -V "\"$CSI_ENTITY\":0 [fmt:SRGGB10_1X10/1920x1080 field:none]" 2>/dev/null || \
        sudo -n media-ctl -d "$MEDIA_DEV" -V "\"$CSI_ENTITY\":0 [fmt:SRGGB10_1X10/1920x1080 field:none]" 2>/dev/null || true
        media-ctl -d "$MEDIA_DEV" -V "\"$CSI_ENTITY\":1 [fmt:SRGGB10_1X10/1920x1080 field:none]" 2>/dev/null || \
        sudo -n media-ctl -d "$MEDIA_DEV" -V "\"$CSI_ENTITY\":1 [fmt:SRGGB10_1X10/1920x1080 field:none]" 2>/dev/null || true
        media-ctl -d "$MEDIA_DEV" -l "\"$IMX_ENTITY\":0 -> \"$CSI_ENTITY\":0 [1]" 2>/dev/null || \
        sudo -n media-ctl -d "$MEDIA_DEV" -l "\"$IMX_ENTITY\":0 -> \"$CSI_ENTITY\":0 [1]" 2>/dev/null || true
    fi

    VIDEO_DEV=$(media-ctl -d "$MEDIA_DEV" -p 2>/dev/null | grep -E 'device node name /dev/video' | head -n 1 | sed -E 's/.*device node name[[:space:]]+//' | xargs || echo "")
    if [ -z "$VIDEO_DEV" ]; then
        VIDEO_DEV=$(media-ctl -d "$MEDIA_DEV" -p 2>/dev/null | grep -A 6 -E 'entity [0-9]+:.*(vcap|frmbuf|capture)' | grep -E 'device node name' | head -n 1 | sed -E 's/.*device node name[[:space:]]+//' | xargs || echo "")
    fi
    set -o pipefail

    # Fallback chỉ kiểm tra /dev/video* khi ĐÃ xác định có MEDIA_DEV của IMX219
    if [ -z "$VIDEO_DEV" ] || [ ! -e "$VIDEO_DEV" ]; then
        for v in /dev/video*; do
            if [ -e "$v" ] && (v4l2-ctl -d "$v" -D 2>/dev/null || sudo v4l2-ctl -d "$v" -D 2>/dev/null) | grep -Ei 'xilinx|mipi|csi|capture' > /dev/null; then
                VIDEO_DEV="$v"
                break
            fi
        done
    fi
fi

INPUT_OPT=""
W2_RAW="$HOME/taco-isp/results/raw/W02_camera/sample_1080p.raw"
if [ ! -f "$W2_RAW" ] && [ -f "$REPO_DIR/results/raw/W02_camera/sample_1080p.raw" ]; then
    W2_RAW="$REPO_DIR/results/raw/W02_camera/sample_1080p.raw"
fi

CAMERA_STREAMING=false
if [ -n "$VIDEO_DEV" ] && [ -e "$VIDEO_DEV" ]; then
    echo "  [✓] Sử dụng video capture node: $VIDEO_DEV" | tee -a "$RUN_LOG"
    v4l2-ctl -d "$VIDEO_DEV" --set-fmt-video=width=1920,height=1080,pixelformat='RG10' 2>/dev/null || \
    v4l2-ctl -d "$VIDEO_DEV" --set-fmt-video=width=1920,height=1080,pixelformat='pRAA' 2>/dev/null || \
    sudo -n v4l2-ctl -d "$VIDEO_DEV" --set-fmt-video=width=1920,height=1080,pixelformat='RG10' 2>/dev/null || \
    sudo -n v4l2-ctl -d "$VIDEO_DEV" --set-fmt-video=width=1920,height=1080,pixelformat='pRAA' 2>/dev/null || true

    echo "  Kiểm tra luồng dữ liệu thực tế từ $VIDEO_DEV (timeout 3s)..." | tee -a "$RUN_LOG"
    if timeout 3s v4l2-ctl -d "$VIDEO_DEV" --stream-mmap --stream-count=1 >/dev/null 2>&1 || \
       timeout 3s sudo -n v4l2-ctl -d "$VIDEO_DEV" --stream-mmap --stream-count=1 >/dev/null 2>&1; then
        CAMERA_STREAMING=true
        echo "  [✓] Camera đang phát luồng khung hình thực tế!" | tee -a "$RUN_LOG"
        INPUT_OPT="--device $VIDEO_DEV"
    else
        echo "  [!] Không nhận được luồng từ $VIDEO_DEV (cáp tiếp xúc lỏng hoặc cảm biến chưa sẵn sàng)." | tee -a "$RUN_LOG"
    fi
fi

if [ "$CAMERA_STREAMING" = false ]; then
    if [ -f "$W2_RAW" ]; then
        echo "  [✓] Kích hoạt Fallback: Sử dụng RAW10 mẫu từ Tuần 2: $W2_RAW" | tee -a "$RUN_LOG"
        INPUT_OPT="--device none --input $W2_RAW"
    else
        echo "  [i] Camera chưa cắm hoặc mất luồng và không có RAW mẫu. Sử dụng khung hình giả lập synthetic 1080p." | tee -a "$RUN_LOG"
        INPUT_OPT="--device none"
    fi
fi

# --- 4. Dò tìm xmodel ---
echo "" | tee -a "$RUN_LOG"
echo ">>> [3/4] Tìm kiếm model xmodel trên hệ thống..." | tee -a "$RUN_LOG"

XMODEL=""
MODEL_DIRS="$REPO_DIR/models $HOME/taco-isp/models /usr/share/vitis_ai_library/models /opt/xilinx/share/vitis_ai_library/models"

# Bước 1: Ưu tiên cao nhất tìm kiếm mô hình YOLOX (case-insensitive)
for dir in $MODEL_DIRS; do
    if [ -d "$dir" ]; then
        for m in $(find "$dir" -name "*.xmodel" 2>/dev/null); do
            if echo "$m" | grep -qi "yolox"; then
                XMODEL="$m"
                break 2
            fi
        done
    fi
done

# Bước 2: Nếu chưa có YOLOX, tìm mô hình họ YOLO (loại bỏ hoàn toàn resnet để tránh sập bộ giải mã C++)
if [ -z "$XMODEL" ]; then
    for dir in $MODEL_DIRS; do
        if [ -d "$dir" ]; then
            for m in $(find "$dir" -name "*.xmodel" 2>/dev/null); do
                if echo "$m" | grep -qi "yolo" && ! echo "$m" | grep -qi "resnet"; then
                    XMODEL="$m"
                    break 2
                fi
            done
        fi
    done
fi

MODEL_OPT=""
if [ -n "$XMODEL" ] && [ -f "$XMODEL" ]; then
    echo "  [✓] Tìm thấy xmodel: $XMODEL" | tee -a "$RUN_LOG"
    MODEL_OPT="--model $XMODEL"
else
    echo "  [i] Chưa có file xmodel cục bộ (yolox/yolo). Kích hoạt chế độ DPU Emulation chuẩn thời gian." | tee -a "$RUN_LOG"
    MODEL_OPT="--dummy"
fi

# --- 5. Thực thi pipeline liên tục (Cổng G0) ---
echo "" | tee -a "$RUN_LOG"
echo ">>> [4/4] Khởi chạy Pipeline Camera -> DPU ($FRAMES khung hình)..." | tee -a "$RUN_LOG"

CONFIG_TAG="G0_YOLOX_nano"
if [ "$CAMERA_STREAMING" = false ] || [ "$MODEL_OPT" = "--dummy" ]; then
    CONFIG_TAG="${CONFIG_TAG}_SYNTHETIC_DEMO"
    echo "  [!] CẢNH BÁO: Phát hiện chế độ giả lập (Camera streaming: $CAMERA_STREAMING, Model opt: $MODEL_OPT)." | tee -a "$RUN_LOG"
    echo "      Đã tự động gán nhãn: --tag $CONFIG_TAG" | tee -a "$RUN_LOG"
fi

EXEC_ARGS=(--mode "$MODE" --frames "$FRAMES" --csv "$CSV_PATH" --tag "$CONFIG_TAG")
if [ -n "$INPUT_OPT" ]; then
    # shellcheck disable=SC2206
    EXEC_ARGS+=($INPUT_OPT)
fi
if [ -n "$MODEL_OPT" ]; then
    # shellcheck disable=SC2206
    EXEC_ARGS+=($MODEL_OPT)
fi

echo "  Lệnh: $BIN_PATH ${EXEC_ARGS[*]}" | tee -a "$RUN_LOG"
"$BIN_PATH" "${EXEC_ARGS[@]}" 2>&1 | tee -a "$RUN_LOG"

echo "" | tee -a "$RUN_LOG"
echo "============================================================" | tee -a "$RUN_LOG"
echo "  [HOÀN TẤT THỰC THI W04 CỔNG KIỂM TRA G0]" | tee -a "$RUN_LOG"
echo "  Dữ liệu CSV: $CSV_PATH" | tee -a "$RUN_LOG"
echo "  Log thực thi: $RUN_LOG" | tee -a "$RUN_LOG"
echo "============================================================" | tee -a "$RUN_LOG"
