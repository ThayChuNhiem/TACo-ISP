# SCHEMAS: Lược đồ Dữ liệu Thực nghiệm & Bảng Kết quả TACo-ISP

Mọi file CSV trong `results/summary/` và `tables/templates/` phải tuân thủ nghiêm ngặt các cột dưới đây để script `analysis/make_tables.py` và `analysis/plots.py` tự động xuất bản mà không bị lỗi.

---

## 1. T-A1: Phân rã độ trễ Baseline & Đề xuất (Latency Breakdown) - `latency.csv`
- `config`: Tên cấu hình (`BA1_YOLOX_nano`, `BA2_YOLOX_nano`, `BA3_YOLOX_nano`, `PTACo_YOLOX_nano`, ...)
- `capture_isp_ms`: Độ trễ thu nhận và ISP (ms, p50)
- `preproc_ms`: Độ trễ tiền xử lý CPU/NEON/PL (ms, p50)
- `dma_sync_ms`: Độ trễ truyền bộ đệm / sync cache (ms, p50)
- `dpu_infer_ms`: Độ trễ suy luận DPU (ms, p50)
- `postproc_ms`: Độ trễ giải mã YOLOX + NMS (ms, p50)
- `total_latency_ms`: Tổng độ trễ từ lúc nhận khung đến ra quyết định (ms)

---

## 2. T-A2: Hiệu năng & Năng lượng Đầu cuối (Glass-to-Decision & Energy) - `energy.csv`
- `config`: Tên cấu hình (`BA1`, `BA2`, `BA3`, `PTACo`)
- `fps`: Tốc độ khung hình thực tế đạt được (FPS)
- `g2d_p50_ms`: Độ trễ Glass-to-decision phân vị 50 (ms)
- `g2d_p95_ms`: Độ trễ Glass-to-decision phân vị 95 (ms)
- `g2d_p99_ms`: Độ trễ Glass-to-decision phân vị 99 (ms)
- `power_w`: Công suất trung bình đường 12V (W)
- `mj_per_frame_total`: Năng lượng tổng mỗi khung hình (mJ/frame)
- `mj_per_frame_dyn`: Năng lượng động (trừ công suất tĩnh nền) (mJ/frame)

---

## 3. T-A3: Sử dụng Tài nguyên Phần cứng PL - `resources.csv`
- `module`: Tên khối (`isp_top`, `s2t_top`, `DPUCZDX8G_B4096`, `axi_timer_gpio`, `Total_Design`, `KV260_Available`)
- `lut`: Số LUT sử dụng
- `lut_percent`: Tỷ lệ % LUT
- `ff`: Số Flip-Flop
- `ff_percent`: Tỷ lệ % FF
- `bram`: Số BRAM 36Kb
- `bram_percent`: Tỷ lệ % BRAM
- `uram`: Số URAM 288Kb
- `uram_percent`: Tỷ lệ % URAM
- `dsp`: Số DSP48E2
- `dsp_percent`: Tỷ lệ % DSP
- `fmax_mhz`: Tần số hoạt động thực tế đóng timing (MHz)

---

## 4. T-A4: Phân tích Ablation Bài A - `ablation_a.csv`
- `ablation_id`: Mã ablation (`A1_no_zerocopy`, `A2_m2m_preproc`, `A3_nbuf_1`, `A3_nbuf_2`, `A3_nbuf_3`, `A4_display_off`, `A4_display_on`, `A7_polling`, `A7_irq`, `A7_isolcpus`)
- `description`: Mô tả cấu hình
- `fps`: Tốc độ khung hình (FPS)
- `latency_p99_ms`: Độ trễ p99 (ms)
- `ddr_traffic_mb_per_frame`: Băng thông DDR đo bằng APM (MB/frame)
- `cpu_util_percent`: Tải CPU Cortex-A53 (%)

---

## 5. T-B1 đến T-B5: Bảng thực nghiệm Bài B
- `map_by_lux.csv`: Độ chính xác mAP@0.5 và mAP@0.5:0.95 ở các dải ánh sáng (1 lux, 5 lux, 10 lux, 50 lux, 200 lux, 1000 lux).
- `deploy_gap.csv`: Khoảng cách mAP giữa bản sao số PyTorch và phần cứng thực tế qua replay.
- `closed_loop.csv`: Đánh giá mAP trên video chuyển sáng D4 (P-static vs P-loop).
- `cost.csv`: Chi phí thời gian tính toán của bộ điều khiển trên Cortex-A53 (< 0.5 ms).
- `ablation_b.csv`: Các ablation của Bài B (bỏ lượng tử hóa đầu vào, bỏ tone mapping nhận biết lượng tử...).

---

## 6. Dữ liệu thô đo công suất 12V (Raw Power Trace) - `raw_power.csv`
- `timestamp_ms`: Dấu thời gian lấy mẫu từ MCU ESP32 / host (ms)
- `voltage_v`: Điện áp đo trên đường 12V DC (V)
- `current_a`: Dòng điện đo qua shunt 10 mΩ (A)
- `power_w`: Công suất tức thời P = V × I (W)
- `gpio_mark`: Cờ đồng bộ từ KV260 (1 = trong cửa sổ thực thi pipeline, 0 = ngoài cửa sổ / idle)

---

## 7. Dữ liệu thô dấu thời gian phân tầng độ trễ (Raw Stage Timestamps) - `raw_timestamps.csv`
- `frame_id`: Số thứ tự khung hình
- `t_sof_ns`: Dấu thời gian Start of Frame (ns)
- `t_pre_done_ns`: Dấu thời gian hoàn tất tiền xử lý (ns)
- `t_dpu_start_ns`: Dấu thời gian bắt đầu gọi DPU execute_async (ns)
- `t_dpu_end_ns`: Dấu thời gian DPU thực thi xong (ns)
- `t_nms_done_ns`: Dấu thời gian hoàn tất giải mã YOLOX và NMS (ns)
- `capture_isp_ms`: Thời gian thu nhận & ISP (ms)
- `preproc_ms`: Thời gian tiền xử lý CPU/NEON/S2T (ms)
- `dma_sync_ms`: Thời gian sync DMA / bộ đệm (ms)
- `dpu_infer_ms`: Thời gian suy luận DPU (ms)
- `postproc_ms`: Thời gian hậu xử lý NMS (ms)
- `total_ms`: Tổng thời gian từ t_sof đến t_nms_done (ms)
- `num_dets`: Số lượng bounding box phát hiện

