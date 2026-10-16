#!/bin/bash
# ============================================================================
# TACo-ISP — W04 Build Script: Milestone G0 Pipeline Compilation on KV260
# ============================================================================
# Chạy trên KV260 qua SSH:
#   1. Kiểm tra môi trường biên dịch C++17, OpenCV4, VART/XIR/XRT
#   2. Cấu hình CMake Release và build binary 'baseline_ba'
#   3. Ghi log biên dịch vào results/raw/W04_g0/build.log
# ============================================================================
set -euo pipefail

SW_DIR="${1:-$HOME/taco-isp/sw}"
BUILD_DIR="$SW_DIR/build"
OUT_DIR="${2:-$HOME/taco-isp/results/raw/W04_g0}"
BUILD_LOG="$OUT_DIR/build.log"

mkdir -p "$OUT_DIR"
mkdir -p "$BUILD_DIR"

echo "============================================================"
echo "  TACo-ISP W04: Build Milestone G0 (Camera -> DPU Pipeline)"
echo "  Thời gian: $(date -Iseconds)"
echo "============================================================" | tee "$BUILD_LOG"

# --- 1. Kiểm tra công cụ & thư viện hệ thống ---
echo "" | tee -a "$BUILD_LOG"
echo ">>> [1/4] Kiểm tra trình biên dịch và thư viện..." | tee -a "$BUILD_LOG"

set +o pipefail
for tool in cmake g++ make; do
    if command -v "$tool" >/dev/null 2>&1; then
        echo "  [✓] $tool: $(command -v $tool) ($("$tool" --version | head -n 1))" | tee -a "$BUILD_LOG"
    else
        echo "  [✗] THIẾU CÔNG CỤ: $tool" | tee -a "$BUILD_LOG"
        exit 1
    fi
done
set -o pipefail

# Kiểm tra thư viện OpenCV
if pkg-config --exists opencv4 2>/dev/null || pkg-config --exists opencv 2>/dev/null; then
    CV_VER=$(pkg-config --modversion opencv4 2>/dev/null || pkg-config --modversion opencv 2>/dev/null)
    echo "  [✓] OpenCV: phiên bản $CV_VER" | tee -a "$BUILD_LOG"
else
    echo "  [!] Cảnh báo: pkg-config không tìm thấy opencv4, CMake sẽ dò trực tiếp." | tee -a "$BUILD_LOG"
fi

# Kiểm tra VART & XIR
echo "--- Kiểm tra thư viện Vitis AI Runtime (VART/XIR/XRT) ---" | tee -a "$BUILD_LOG"
set +o pipefail
for lib in libvart-runner.so libvart-util.so libxir.so libxrt_coreutil.so; do
    if ldconfig -p 2>/dev/null | grep -q "$lib" || find /usr/lib /usr/lib64 /usr/local/lib -maxdepth 2 -name "$lib*" 2>/dev/null | head -n 1 | grep -q .; then
        echo "  [✓] $lib: TÌM THẤY" | tee -a "$BUILD_LOG"
    else
        echo "  [!] Cảnh báo: $lib chưa đăng ký ldconfig (CMake sẽ tìm trong /usr/lib)" | tee -a "$BUILD_LOG"
    fi
done
set -o pipefail

# --- 2. Cấu hình CMake ---
echo "" | tee -a "$BUILD_LOG"
echo ">>> [2/4] Cấu hình CMake (Release mode)..." | tee -a "$BUILD_LOG"
rm -rf "$BUILD_DIR"/*
cd "$BUILD_DIR"

cmake "$SW_DIR" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_CXX_STANDARD=17 2>&1 | tee -a "$BUILD_LOG"

# --- 3. Biên dịch target baseline_ba ---
echo "" | tee -a "$BUILD_LOG"
echo ">>> [3/4] Biên dịch target 'baseline_ba' cho Milestone G0..." | tee -a "$BUILD_LOG"

NPROC=$(nproc || echo 2)
echo "  Sử dụng $NPROC luồng biên dịch..." | tee -a "$BUILD_LOG"

make baseline_ba -j"$NPROC" 2>&1 | tee -a "$BUILD_LOG"

# --- 4. Kiểm tra binary đầu ra ---
echo "" | tee -a "$BUILD_LOG"
echo ">>> [4/4] Kiểm tra binary đầu ra..." | tee -a "$BUILD_LOG"
BIN_PATH="$BUILD_DIR/baseline_ba"

if [ -f "$BIN_PATH" ] && [ -x "$BIN_PATH" ]; then
    BIN_SIZE=$(stat -c%s "$BIN_PATH")
    echo "  [✓] BIÊN DỊCH THÀNH CÔNG!" | tee -a "$BUILD_LOG"
    echo "      Tập tin:    $BIN_PATH" | tee -a "$BUILD_LOG"
    echo "      Dung lượng: $BIN_SIZE bytes" | tee -a "$BUILD_LOG"
    echo "      MD5:        $(md5sum "$BIN_PATH" | awk '{print $1}')" | tee -a "$BUILD_LOG"
else
    echo "  [✗] LỖI: Không tìm thấy binary thực thi tại $BIN_PATH!" | tee -a "$BUILD_LOG"
    exit 1
fi

echo "" | tee -a "$BUILD_LOG"
echo "============================================================" | tee -a "$BUILD_LOG"
echo "  [HOÀN TẤT BUILD W04] Binary sẵn sàng cho nghiệm thu Cổng G0!" | tee -a "$BUILD_LOG"
echo "  Log biên dịch: $BUILD_LOG" | tee -a "$BUILD_LOG"
echo "============================================================" | tee -a "$BUILD_LOG"
