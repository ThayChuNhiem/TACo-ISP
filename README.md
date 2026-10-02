# TACo-ISP: Task-Aware, Closed-Loop HW/SW Co-Design of ISP and DPU on AMD Kria KV260

Đồng thiết kế Phần cứng / Phần mềm giữa Bộ xử lý tín hiệu hình ảnh (ISP) và Bộ suy luận học sâu (DPU) cho thị giác AI thời gian thực trên AMD Kria KV260 (XCK26 Zynq UltraScale+ MPSoC).

---

## 1. Cấu trúc Kho mã

```text
taco-isp/
├── hw/                  # Phần cứng PL (Vitis HLS C++, link script, device tree)
│   ├── hls/common/      # Quy ước số học dấu phẩy tĩnh (taco_types.h) + host shim
│   ├── hls/isp/         # ISP: BLC, DPC, NR, demosaic MHC, WB, CCM, LUT tone, thống kê
│   ├── hls/s2t/         # Stream-to-Tensor zero-copy (s2t_top) & memory-to-memory (s2t_m2m)
│   ├── hls/replay/      # Phát lại RAW từ DDR vào ISP (raw_mm2s)
│   ├── hls/tb/          # Testbench C++ (tb_host.cpp) cho g++ và Vitis HLS
│   ├── hls/scripts/     # Kịch bản Vitis HLS (run_hls.tcl)
│   ├── vitis/           # Cấu hình ghép hệ thống (link.cfg, dpu_conf.vh)
│   └── overlay/         # Device tree overlay UIO (taco.dtsi)
├── sw/                  # Phần mềm PS (ARM Cortex-A53 Linux C++17)
│   ├── common/          # UIO driver (uio.hpp), đồng hồ AXI Timer (HwClock), nạp thanh ghi
│   ├── app/             # Ứng dụng P-TACo (taco_app.cpp), baseline BA1/BA2/BA3, YOLOX post
│   ├── controller/      # Bộ điều khiển vòng kín C++ runtime (< 0.5 ms/khung)
│   └── CMakeLists.txt   # Build hệ thống trên Linux KV260
├── twin/                # Bản sao số khả vi (NumPy reference, PyTorch bit-exact twin)
├── train/               # Hiệu chuẩn nhiễu, unprocess COCO, huấn luyện joint, oracle, MLP
├── measure/             # Firmware đo công suất INA228 1 kHz (ina228_logger) & script log
├── experiments/         # Tự động hóa đo đạc qua SSH (run_matrix.py) & ma trận thực nghiệm
├── analysis/            # Phân tích độ trễ glass-to-decision, năng lượng mJ/khung, sinh bảng/hình
├── tables/templates/    # 9 bảng chuẩn CSV theo SCHEMAS.md (T-A1 .. T-B5)
├── regs/                # File thanh ghi nạp phần cứng (default.txt, tone_basis.txt)
├── tools/               # Tiện ích sinh vector kiểm thử, sinh thanh ghi, dữ liệu demo
├── tests/               # 35 bài kiểm thử tự động (khớp bit, controller, pipeline)
└── results/             # Nhật ký thực nghiệm (raw/ và summary/)
```

---

## 2. Phân công Nhóm 3 Kỹ sư
- **TV1:** Phần cứng PL (HLS ISP, Stream-to-Tensor, Vivado IPI, timing closure, Vitis link).
- **TV2:** Phần mềm PS & Đo lường (Linux, VART zero-copy, C++17 runtime, đo độ trễ glass-to-decision, đo công suất 12V INA228, phân tích Bài A).
- **TV3:** AI & Dữ liệu (Dữ liệu RAW, twin PyTorch khớp bit, huấn luyện joint ISP-DPU, bộ điều khiển thích nghi).

---

## 3. Lệnh Nhanh (Quick Start)
```bash
# Cài đặt môi trường Python
pip install -r requirements.txt

# Kiểm tra khớp bit toàn bộ hệ thống
make test

# Sinh file thanh ghi mặc định
make regs

# Sinh bảng và biểu đồ mẫu
make tables
make figs
```
