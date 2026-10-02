# Hướng Dẫn Tích Hợp Hệ Thống Phần Cứng (Vitis Link & Overlay)

Phụ trách: **TV1**, phối hợp **TV2**.

## 1. Các bước tích hợp
1. Tổng hợp HLS các kernel: `isp_top`, `s2t_top`, `raw_mm2s` thành `.xo`.
2. Tạo cấu hình DPU TRD (`dpu_conf.vh`) với kích thước **B4096** và xuất `dpu.xo`.
3. Chạy `v++ -l` với file cấu hình `link.cfg` để ghép DPU và các kernel HLS vào KV260 camera platform.
4. Đóng gói bitstream và tạo device tree overlay `taco.dtsi`.
5. Đưa `.bit.bin` và `.dtbo` vào `/lib/firmware/xilinx/taco` trên KV260, nạp bằng `sudo xmutil loadapp taco`.

## 2. Phiên bản công cụ bắt buộc
- **Vivado / Vitis:** 2022.2
- **Vitis AI:** 3.0 (DPUCZDX8G v4.1)
- **Linux Kernel:** 5.15-xilinx
