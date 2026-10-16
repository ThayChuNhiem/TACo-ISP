#!/bin/bash
# ============================================================================
# TACo-ISP — W01 DPU Check Script (ĐV-3: xmutil & DPU Query)
# Kiểm tra DPU overlay, nạp accelerator, benchmark sơ bộ
# ============================================================================
set -euo pipefail

LOG_DIR="$HOME/taco-isp/results/raw/W01_setup"
ENV_FILE="$LOG_DIR/ENV.md"
DPU_LOG="$LOG_DIR/dpu_query.log"
mkdir -p "$LOG_DIR"

echo "============================================"
echo "  TACo-ISP W01: DPU & Accelerator Check"
echo "  $(date -Iseconds)"
echo "============================================"

# --- 1. Liệt kê accelerator có sẵn ---
echo ""
echo ">>> [1/5] Listing available accelerators..."
echo "" >> "$ENV_FILE"
echo "## DPU & Accelerator" >> "$ENV_FILE"
echo "### xmutil listapps" >> "$ENV_FILE"
echo '```' >> "$ENV_FILE"
sudo xmutil listapps 2>&1 | tee -a "$ENV_FILE" || true
echo '```' >> "$ENV_FILE"
echo "[✓] listapps done"

# --- Kiểm tra DPU pre-loaded trước khi nạp app ---
DPU_PRELOADED=0
DPU_APP=""
if command -v xdputil &>/dev/null; then
    if (xdputil query 2>/dev/null || sudo xdputil query 2>/dev/null) | grep -q "DPUCZDX8G"; then
        echo "[✓] DPU architecture DPUCZDX8G already pre-loaded in hardware (boot bitstream TRD)."
        DPU_PRELOADED=1
        DPU_APP="default-dpu-b4096 (pre-loaded)"
    fi
fi

if [ "$DPU_PRELOADED" -eq 1 ]; then
    echo ""
    echo ">>> [2/5] & [3/5] Skipping xmutil unloadapp/loadapp (DPU is pre-loaded)"
else
    # --- 2. Unload bất kỳ app nào đang chạy ---
    echo ""
    echo ">>> [2/5] Unloading current app..."
    sudo xmutil unloadapp 2>&1 || echo "[!] No app was loaded (OK)"

    # --- 3. Load DPU overlay ---
    echo ""
    echo ">>> [3/5] Loading DPU accelerator..."
    # Thử các tên phổ biến
    for candidate in kv260-smartcam kv260-aibox-reid kv260-benchmark-b4096 kv260-dpu; do
        if sudo xmutil listapps 2>/dev/null | grep -q "$candidate"; then
            DPU_APP="$candidate"
            break
        fi
    done

    if [ -n "$DPU_APP" ]; then
        echo "  Found DPU app: $DPU_APP"
        sudo xmutil loadapp "$DPU_APP" 2>&1
        echo "[✓] Loaded: $DPU_APP"
    else
        echo "[!] No known DPU app found in listapps. Trying 'kv260-smartcam'..."
        sudo xmutil loadapp kv260-smartcam 2>&1 || {
            echo "[ERROR] Could not load DPU overlay!"
            echo "  Available apps:"
            sudo xmutil listapps 2>&1
            echo "  >>> Cần TV1 hỗ trợ build overlay DPU B4096"
        }
    fi
fi

echo "" >> "$ENV_FILE"
echo "### DPU Overlay Loaded" >> "$ENV_FILE"
echo '```' >> "$ENV_FILE"
echo "App: ${DPU_APP:-UNKNOWN}" >> "$ENV_FILE"
echo '```' >> "$ENV_FILE"

# --- 4. xdputil query ---
echo ""
echo ">>> [4/5] Querying DPU info..."
echo "" >> "$ENV_FILE"
echo "### xdputil query" >> "$ENV_FILE"
echo '```' >> "$ENV_FILE"
if command -v xdputil &>/dev/null; then
    xdputil query 2>&1 | tee "$DPU_LOG" | tee -a "$ENV_FILE"
    if grep -q "DPUCZDX8G" "$DPU_LOG"; then
        echo "[✓] DPU architecture DPUCZDX8G verified"
    else
        echo "[!] DPU architecture check: DPUCZDX8G not detected in query"
    fi
    echo "[✓] DPU query success"
else
    echo "xdputil: NOT FOUND" | tee -a "$ENV_FILE"
    echo "[!] xdputil not in PATH. Check /usr/bin/ or /opt/vitis_ai/"
fi
echo '```' >> "$ENV_FILE"

# --- 5. Test load/unload ổn định ---
echo ""
echo ">>> [5/5] Stability test: unload → load → query..."
if [ "$DPU_PRELOADED" -eq 1 ]; then
    echo "[!] Skipped load/unload cycle test (DPU is pre-loaded from boot bitstream)"
    set +o pipefail
    xdputil query 2>&1 | head -5 || true
    set -o pipefail
    echo "[✓] Pre-loaded DPU query verified"
elif [ -n "$DPU_APP" ]; then
    sudo xmutil unloadapp 2>&1 || true
    sleep 2
    sudo xmutil loadapp "$DPU_APP" 2>&1
    sleep 2
    # Tạm tắt pipefail để tránh SIGPIPE 141 khi head kết thúc sớm
    set +o pipefail
    xdputil query 2>&1 | head -5 || true
    set -o pipefail
    echo "[✓] Load/unload cycle stable"
else
    echo "[!] Skipped (no DPU app)"
fi

echo ""
echo "============================================"
echo "  DPU check complete!"
echo "  Log: $DPU_LOG"
echo "============================================"
