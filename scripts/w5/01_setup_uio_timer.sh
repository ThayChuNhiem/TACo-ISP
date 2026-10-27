#!/bin/bash
# ============================================================================
# TACo-ISP — W05 Setup Script: UIO Drivers & AXI Timer/GPIO on AMD Kria KV260
# ============================================================================
# Mục tiêu:
#   1. Nạp driver generic-uio (uio_pdrv_genirq) cho axi_timer và axi_gpio
#   2. Cấp quyền truy cập /dev/uio* cho userspace
#   3. Khởi tạo GPIO pin (338) làm trigger LED đo độ trễ & cờ đo công suất
# ============================================================================
set -euo pipefail

OUT_DIR="${1:-$HOME/taco-isp/results/raw/W05_measurement}"
mkdir -p "$OUT_DIR"
SETUP_LOG="$OUT_DIR/uio_setup.log"

echo "============================================================" | tee "$SETUP_LOG"
echo "  TACo-ISP W05: Setup UIO Drivers & AXI Timer/GPIO" | tee -a "$SETUP_LOG"
echo "  Thời gian: $(date -Iseconds)" | tee -a "$SETUP_LOG"
echo "============================================================" | tee -a "$SETUP_LOG"

# 1. Nạp driver generic-uio cho Device Tree Overlay
echo ">>> [1/3] Kiểm tra kernel driver uio_pdrv_genirq..." | tee -a "$SETUP_LOG"
if ! lsmod | grep -q "uio_pdrv_genirq"; then
    echo "  [i] Đang nạp module uio_pdrv_genirq of_id=\"generic-uio\"..." | tee -a "$SETUP_LOG"
    if command -v modprobe >/dev/null 2>&1; then
        sudo modprobe uio_pdrv_genirq of_id="generic-uio" || true
    fi
fi

# 2. Cấp quyền truy cập /dev/uio*
echo ">>> [2/3] Kiểm tra thiết bị /dev/uio*..." | tee -a "$SETUP_LOG"
UIO_FOUND=0
for uio in /dev/uio*; do
    if [ -e "$uio" ]; then
        echo "  [✓] Tìm thấy thiết bị UIO: $uio" | tee -a "$SETUP_LOG"
        if [ -w "$uio" ]; then
            echo "      Quyền ghi: ĐẠT" | tee -a "$SETUP_LOG"
        else
            echo "      Cấp quyền ghi chmod 666 $uio..." | tee -a "$SETUP_LOG"
            sudo chmod 666 "$uio" || true
        fi
        UIO_FOUND=1
    fi
done

if [ "$UIO_FOUND" -eq 0 ]; then
    echo "  [i] Chưa có thiết bị /dev/uio* vật lý (chạy mô phỏng / host mode)." | tee -a "$SETUP_LOG"
fi

# 3. Cấu hình GPIO trigger (Mặc định pin 338 trên SOM K26)
echo ">>> [3/3] Cấu hình GPIO latency trigger..." | tee -a "$SETUP_LOG"
GPIO_PIN=338
if [ -d "/sys/class/gpio" ]; then
    if [ ! -d "/sys/class/gpio/gpio${GPIO_PIN}" ]; then
        echo "$GPIO_PIN" | sudo tee /sys/class/gpio/export >/dev/null 2>&1 || true
    fi
    if [ -d "/sys/class/gpio/gpio${GPIO_PIN}" ]; then
        echo "out" | sudo tee "/sys/class/gpio/gpio${GPIO_PIN}/direction" >/dev/null 2>&1 || true
        echo "0" | sudo tee "/sys/class/gpio/gpio${GPIO_PIN}/value" >/dev/null 2>&1 || true
        echo "  [✓] GPIO $GPIO_PIN: Đã export và đặt chế độ OUTPUT (mức 0)" | tee -a "$SETUP_LOG"
    else
        echo "  [i] GPIO sysfs không khả dụng trên hệ thống này." | tee -a "$SETUP_LOG"
    fi
else
    echo "  [i] Thư mục /sys/class/gpio không tồn tại." | tee -a "$SETUP_LOG"
fi

echo "" | tee -a "$SETUP_LOG"
echo "  [✓] Hoàn tất thiết lập UIO & GPIO cho Tuần 5." | tee -a "$SETUP_LOG"
