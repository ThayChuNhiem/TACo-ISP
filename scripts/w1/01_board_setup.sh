#!/bin/bash
# ============================================================================
# TACo-ISP — W01 Board Setup Script (ĐV-2: SSH & System Info)
# Chạy trên KV260 qua SSH lần đầu tiên
# AI Agent sẽ SCP file này lên board rồi chạy tự động
# ============================================================================
set -euo pipefail

LOG_DIR="$HOME/taco-isp/results/raw/W01_setup"
ENV_FILE="$LOG_DIR/ENV.md"
mkdir -p "$LOG_DIR"

echo "============================================"
echo "  TACo-ISP W01: Board Setup & System Info"
echo "  $(date -Iseconds)"
echo "============================================"

# --- 1. Thu thập thông tin hệ thống ---
cat > "$ENV_FILE" <<'HEADER'
# ENV.md — W01 Board Setup
> Tự động sinh bởi `01_board_setup.sh`

## Thông tin Hệ thống
HEADER

echo '```' >> "$ENV_FILE"
echo "Ngày giờ:      $(date -Iseconds)" >> "$ENV_FILE"
echo "Hostname:      $(hostname)" >> "$ENV_FILE"
echo "Kernel:        $(uname -r)" >> "$ENV_FILE"
echo "Architecture:  $(uname -m)" >> "$ENV_FILE"
echo "OS:" >> "$ENV_FILE"
cat /etc/os-release >> "$ENV_FILE" 2>/dev/null || echo "  (không đọc được /etc/os-release)" >> "$ENV_FILE"
echo "" >> "$ENV_FILE"

echo "--- CPU ---" >> "$ENV_FILE"
grep -c ^processor /proc/cpuinfo >> "$ENV_FILE" 2>/dev/null && echo " cores" >> "$ENV_FILE"
head -20 /proc/cpuinfo >> "$ENV_FILE" 2>/dev/null || true
echo "" >> "$ENV_FILE"

echo "--- Memory ---" >> "$ENV_FILE"
free -h >> "$ENV_FILE" 2>/dev/null || true
echo "" >> "$ENV_FILE"

echo "--- Disk ---" >> "$ENV_FILE"
df -h >> "$ENV_FILE" 2>/dev/null || true
echo '```' >> "$ENV_FILE"

echo "[✓] System info collected"

# --- 2. Kiểm tra network ---
echo "" >> "$ENV_FILE"
echo "## Network" >> "$ENV_FILE"
echo '```' >> "$ENV_FILE"
ip addr show 2>/dev/null | grep -E 'inet |link/ether' >> "$ENV_FILE" || \
    ifconfig 2>/dev/null | grep -E 'inet |ether' >> "$ENV_FILE" || \
    echo "  (không đọc được network info)" >> "$ENV_FILE"
echo '```' >> "$ENV_FILE"

echo "[✓] Network info collected"

# --- 3. Kiểm tra SSH daemon ---
if systemctl is-active --quiet sshd 2>/dev/null || systemctl is-active --quiet ssh 2>/dev/null; then
    echo "[✓] SSH daemon is running"
else
    echo "[!] SSH daemon not running, attempting to start..."
    sudo systemctl enable --now sshd 2>/dev/null || sudo systemctl enable --now ssh 2>/dev/null || true
fi

# --- 4. Kiểm tra phần mềm cơ bản ---
echo "" >> "$ENV_FILE"
echo "## Phần mềm đã cài" >> "$ENV_FILE"
echo '```' >> "$ENV_FILE"

for pkg in python3 gcc g++ cmake make git v4l2-ctl media-ctl; do
    if command -v "$pkg" >/dev/null 2>&1; then
        if [ "$pkg" = "media-ctl" ]; then
            ver="INSTALLED ($(command -v media-ctl))"
        else
            ver=$("$pkg" --version 2>&1 | head -1 || echo "INSTALLED")
        fi
    else
        ver="NOT FOUND"
    fi
    echo "$pkg: $ver" >> "$ENV_FILE"
done

# Kiểm tra Python packages
echo "" >> "$ENV_FILE"
echo "--- Python3 packages (VART/XIR) ---" >> "$ENV_FILE"
python3 -c "import vart; print('vart: OK (module loaded)')" >> "$ENV_FILE" 2>&1 || echo "vart: NOT INSTALLED" >> "$ENV_FILE"
python3 -c "import xir; print('xir: OK (module loaded)')" >> "$ENV_FILE" 2>&1 || echo "xir: NOT INSTALLED" >> "$ENV_FILE"
echo '```' >> "$ENV_FILE"

echo "[✓] Software check done"

echo ""
echo "============================================"
echo "  ENV.md saved to: $ENV_FILE"
echo "  Board setup complete!"
echo "============================================"
