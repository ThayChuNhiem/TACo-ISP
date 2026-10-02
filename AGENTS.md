# INSTRUCTION DÀNH CHO AI ASSISTANT — ĐỀ TÀI TACo-ISP (KV260)
> **Dành cho:** AI Assistant khi tương tác với người dùng tại thư mục `d:\2026\TACo-ISP`.  
> **Người dùng hiện tại:** **TV2 (Thành viên 2)** — Phụ trách **Phần mềm PS (Processing System) & Hệ thống Đo lường**.  
> **Cơ chế nạp:** Tự động đọc và kích hoạt toàn bộ chỉ dẫn dưới đây trong mọi phiên làm việc.

---

## 1. BỐI CẢNH DỰ ÁN & VỊ TRÍ CỦA TV2

- **Tên đề tài:** TACo-ISP: Task-Aware, Closed-loop Hardware–Software Co-Design of Image Signal Processing and DPU Inference for Real-Time Edge Vision on AMD Kria KV260.
- **Phần cứng mục tiêu:** AMD Kria KV260 (XCK26 Zynq UltraScale+ MPSoC), Camera Sony IMX219 (RAW10 Bayer RGGB qua MIPI CSI-2 J9), DPU DPUCZDX8G v4.1 (Vitis AI 3.0), Linux Ubuntu 22.04 / PetaLinux 2022.2 trên 4 lõi ARM Cortex-A53.
- **Mục tiêu học thuật:** 2 bài báo quốc tế (Bài A nộp Tuần 40, Bài B nộp Tuần 62) + Đồ án tốt nghiệp / Báo cáo khoa học.
- **Phân công nhóm 3 SV:**
  - **TV1:** Phần cứng PL (HLS ISP, Stream-to-Tensor, Vivado IPI, timing closure, Vitis link).
  - **TV2 (BẠN ĐANG LÀM VIỆC CÙNG):** Phần mềm PS & Hệ thống Đo lường (Linux, VART zero-copy, C++17 runtime, đo độ trễ glass-to-decision, đo công suất 12V INA228, phân tích kết quả bài A). Đồng tác giả chính Bài A.
  - **TV3:** AI & Dữ liệu (Bộ dữ liệu RAW, twin PyTorch khớp bit, huấn luyện joint ISP-DPU, bộ điều khiển thích nghi).
- **Lịch dùng board KV260:** Board dùng chung vật lý. **Ca của TV2 là buổi CHIỀU** (TV1 sáng, TV3 tối/cuối tuần).

---

## 2. PHẠM VI TRÁCH NHIỆM & CÁC THƯ MỤC CỦA TV2

Mỗi khi TV2 đưa ra yêu cầu, AI phải ưu tiên hướng giải quyết nằm trong các thư mục và module mà TV2 làm chủ:

### 2.1. Mã nguồn phần mềm PS (`sw/`)
- `sw/common/`:
  - `uio.hpp`: Driver userspace UIO (`/dev/uio*`) ánh xạ thanh ghi mmap, bắt ngắt `ap_done` của ISP/S2T; lớp `HwClock` (đọc AXI Timer 64-bit); lớp `Gpio` (bật tắt LED độ trễ, cờ cửa sổ đo công suất).
  - `kernels.hpp`: Giao tiếp thanh ghi AXI4-Lite với `isp_top` và `s2t_top` từ header HLS (`xisp_top_hw.h`, `xs2t_top_hw.h`).
  - `params_io.hpp`: Đọc file thanh ghi text (`regs/default.txt`, `regs/tone_basis.txt`) nạp xuống phần cứng.
- `sw/app/`:
  - `taco_app.cpp`: Ứng dụng P-TACo đề xuất (4 luồng: T1 ngắt khung, T2 VART execute_async zero-copy, T3 YOLOX decode + NMS, T4 bộ điều khiển vòng kín; 3 bộ đệm xoay vòng). Chứa các switch thí nghiệm ablation: `--copy-mode` (A1), `--nbuf 1` (A3), `--led`, `--subdev`.
  - `baseline_ba.cpp`: Hai baseline BA1 (V4L2 → OpenCV resize/quant CPU → VART) và BA2 (tiền xử lý NEON của Vitis AI Library `DpuTask`).
  - `baseline_ba3.cpp`: Baseline BA3 (ảnh vào DDR qua V4L2, kernel `s2t_m2m` trên PL đọc ra ghi tensor).
  - `yolox_post.hpp`: Hậu xử lý YOLOX (stride 8/16/32, NMS) dùng chung chuẩn hóa so sánh.
- `sw/controller/`:
  - `controller.hpp` & `ctrl_ref.cpp`: Tích hợp bộ điều khiển thích nghi từ TV3, tối ưu thực thi trên A53 đảm bảo budget `< 0.5 ms/khung`.
- `sw/CMakeLists.txt`: Build hệ thống C++17 liên kết `vart-runner`, `xir`, `xrt_coreutil`, `opencv4`.

### 2.2. Đo lường phần cứng (`measure/`)
- `measure/ina228_logger/`: Firmware MCU (ESP32/Arduino) đọc cảm biến INA228 ở 1 kHz qua I2C, nhận chân cờ GPIO từ KV260 để đồng bộ cửa sổ đo công suất 12V.
- `measure/log_power.py`: Kịch bản Python ghi log nguồn (chế độ serial từ MCU trên máy host và hwmon INA260 trên SOM).
- Hệ đo độ trễ: Mạch LED quang + photodiode/AXI Timer đo độ trễ glass-to-decision end-to-end; AXI Performance Monitor (APM) đo băng thông DDR.

### 2.3. Tự động hóa thí nghiệm & Phân tích (`experiments/`, `analysis/`)
- `experiments/run_matrix.py`: Chạy chuỗi thí nghiệm tự động qua SSH, xáo trộn thứ tự, nạp overlay, bật đo công suất, nghỉ nhiệt, ghi nhận `ENV.md` (commit hash, bitstream hash, xdputil query).
- `analysis/`:
  - `latency.py`: Tách tầng độ trễ, phân tích block-bootstrap (khối 300 khung) cho phân vị p50/p95/p99.
  - `energy.py`: Tích phân công suất tính mJ/khung (tổng và động), Welch t-test.
  - `make_tables.py`: Tự động kết xuất bảng T-A1 đến T-A4 dạng Markdown và LaTeX (booktabs) theo schema chuẩn tại `analysis/SCHEMAS.md`.
  - `plots.py`: Sinh hình F-A2 (phân rã độ trễ), F-A3 (CDF), F-A4/F-A5 (trade-off Pareto) dạng PDF vector.

---

## 3. NGUYÊN TẮC CỐT LÕI (GOLDEN RULES) AI PHẢI TUÂN THỦ

1. **Số liệu thật 100% từ board — Tuyệt đối không bịa hay dùng số demo:**
   - Mọi số liệu trong bài báo/báo cáo phải xuất phát từ thực nghiệm đo trên KV260 qua `analysis/make_tables.py`.
   - Tuyệt đối không lấy số từ `results_demo/` (thư mục này chỉ để test pipeline sinh bảng và có watermark).
2. **Quy tắc Zero-Copy VART:**
   - Lấy địa chỉ vật lý bằng `TensorBuffer::data_phy()` từ `vart::RunnerExt`.
   - Ghi địa chỉ vào thanh ghi `dst` của `s2t_top` qua AXI4-Lite.
   - Khi `s2t_top` phát ngắt `ap_done`, gọi `execute_async` trên bộ đệm đó.
   - Cổng kiểm tra G2: Tensor do PL ghi phải giống hệt tensor CPU tính (0 sai khác trên 500 khung).
3. **Độ trễ Glass-to-Decision:**
   - Bật LED ở t₀ (AXI GPIO + AXI Timer). Khung đầu tiên nhận LED qua bước nhảy `sat_cnt` của thống kê ISP; t_dec kết thúc khi NMS xong.
   - Thu thập tối thiểu 10.000 khung × 5 lần chạy mỗi cấu hình; phân tích thống kê bằng block-bootstrap (khối 300 khung).
4. **Đo công suất 12V chính xác:**
   - Không dùng PPK2 (vì giới hạn 5V/1A). Dùng INA228 với shunt 10 mΩ trên đường 12V, lấy mẫu 1 kHz.
   - Báo cáo cả công suất tổng và công suất động (trừ công suất nền tĩnh khi overlay đã nạp nhưng chưa xử lý ảnh).
5. **Cấm sửa tay file thanh ghi:**
   - Mọi file cấu hình thanh ghi (`regs/*.txt`) phải được sinh từ `twin/params.py` hoặc `tools/make_default_regs.py`.
6. **Bảo toàn môi trường đã khóa:**
   - Vitis/Vivado 2022.2, Vitis AI 3.0 (DPUCZDX8G v4.1 B4096).
   - Mỗi thư mục kết quả trong `results/raw/<ngày>_<TN>/` bắt buộc phải có file `ENV.md` ghi log môi trường.

---

## 4. LỘ TRÌNH 65 TUẦN CỦA TV2 & CÁC CỔNG KIỂM TRA

AI cần chủ động nắm mốc thời gian và nhiệm vụ của TV2 theo `KeHoachTuan_TACo-ISP_3SV.xlsx`:

| Giai đoạn | Tuần | Nhiệm vụ chính của TV2 | Mốc / Cổng |
| :--- | :--- | :--- | :--- |
| **GĐ1: Nền tảng, baseline, dữ liệu** | W1–W4 | Ghi SD image Vitis AI 3.0; bring-up IMX219 (V4L2/media-ctl 1080p RAW10); viết ứng dụng BA1 (OpenCV + VART); chạy YOLOX-nano | **G0 (W4)**: Pipeline camera → DPU chạy thông |
| | W5–W8 | Hệ đo AXI Timer + GPIO; mạch INA228 + MCU 1 kHz; hiệu chuẩn đo công suất; kiểm tra lặp lại LED latency | Hệ đo hoàn chỉnh |
| | W9–W14 | TN-A1 (BA1, BA2 trên 3 mô hình, 10.000 khung × 3); phân tích phân rã độ trễ; đo công suất nền; báo cáo RQ1 sơ bộ | **G1 (W14)**: Xong phân rã baseline BA1/BA2 |
| **GĐ2: ISP + S2T trên PL, zero-copy** | W15–W18 | Nghiên cứu `vart::RunnerExt`, `TensorBuffer::data_phy()`; viết PoC zero-copy với UIO; kiểm tra Tensor PL = CPU (0 sai khác) | Đạt chỉ tiêu ND5 |
| | W19–W26 | Ứng dụng P-TACo (4 luồng, 3 buffer); đo trễ I2C phơi sáng/gain; tối ưu ≥ 30 FPS; kịch bản tự động `run_matrix.py`; APM DDR | **G2 (W26)**: P-TACo chạy mượt, khóa SD image |
| **GĐ3: Thí nghiệm, nộp bài A** | W27–W33 | Thực hiện TN-A1 (BA3), TN-A2 (glass-to-decision), TN-A3 (năng lượng 12V 5×60s), TN-A4 (APM DDR); các ablation A1, A3, A4, A7 | Đủ dữ liệu bài A |
| | W34–W40 | Chạy `make_tables.py`, `plots.py`; viết mục Đo lường & Kết quả; hoàn thiện bản thảo Bài A; nộp bài | **G3 (W36) / Nộp A (W40)** |
| **GĐ4: Vòng kín HW-in-loop** | W41–W46 | Viết luồng T4 trên A53 cho bộ điều khiển; hỗ trợ TV3 thu tập D4 (hộp sáng dimmer); tối ưu C++ inference `< 0.5 ms` | **G4 (W46)**: Closed-loop chạy real-time |
| | W47–W56 | TN-B3 (P-static vs P-loop trên D4 replay và trực tiếp); TN-B4 (đo năng lượng P-loop); kiểm tra tính ổn định/tái lập | **G5 (W56)**: Xong dữ liệu bài B |
| **GĐ5: Viết, nộp bài B, phát hành** | W57–W65 | Viết phần hệ thống bài B; kiểm tra tái lập từ kho sạch; đóng gói phát hành mã nguồn & kịch bản đo; viết báo cáo tốt nghiệp | **G6 / Nộp B (W62) / Nghiệm thu (W65)** |

---

## 5. CÁCH THỨC TƯƠNG TÁC VỚI TV2

1. **Xưng hô & Định vị:**
   - Luôn nhớ rõ: Người dùng là **TV2** (phụ trách PS, C++, VART, đo lường độ trễ & năng lượng).
   - Khi thảo luận kỹ thuật, tập trung vào góc độ hệ điều hành Linux, driver UIO, bộ đệm DMA, thread sync, POSIX timers, VART API, và độ chính xác của phép đo.
2. **Khi TV2 cần viết hoặc gỡ lỗi mã C++:**
   - Áp dụng C++17 hiện đại, cấu trúc RAII chặt chẽ, tối ưu phân bổ bộ nhớ (tránh cấp phát động trong vòng lặp xử lý khung hình).
   - Đồng bộ luồng bằng lock-free queue hoặc condition variables hiệu năng cao.
   - Luôn chú ý đến cache flush / invalidate khi làm việc với bộ đệm DMA giữa CPU và PL.
3. **Khi TV2 cần chạy thực nghiệm hoặc xử lý số liệu:**
   - Đảm bảo các script Python trong `measure/` và `analysis/` xử lý dữ liệu chặt chẽ (định dạng CSV đúng schema, xử lý ngoại lệ mất gói serial, tự động bù trôi xung nhịp).
   - Luôn sẵn sàng hỗ trợ viết kịch bản shell/python tự động hóa kiểm thử để TV2 tối ưu thời gian sử dụng board vào buổi chiều.
4. **Kiểm tra chéo với TV1 và TV3:**
   - Nhắc TV2 kiểm tra đồng bộ địa chỉ thanh ghi từ file header HLS của TV1 (`hw/hls/`) khi build `sw/`.
   - Nhắc TV2 phối hợp với TV3 khi nhận các file trọng số bộ điều khiển (`ctrl_mlp.txt`, `tone_basis.txt`) để nạp vào `sw/controller/`.
