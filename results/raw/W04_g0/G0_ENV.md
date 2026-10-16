# G0_ENV.md — BÁO CÁO NGHIỆM THU CỔNG KIỂM TRA G0 (TUẦN 4)
> Dự án TACo-ISP | Tự động sinh bởi `03_eval_g0.sh` vào 2026-10-16T02:14:01-07:00
> ⚠️ **CẢNH BÁO BẢO TOÀN DỮ LIỆU (SYNTHETIC DEMO):** Thử nghiệm chạy ở chế độ giả lập. Tuyệt đối không dùng số liệu này trong bài báo hoặc nghiệm thu Cổng G0 chính thức.

## 1. Mục tiêu Cổng Kiểm tra G0 (Milestone G0)
- **Tiêu chuẩn Cổng G0 (KeHoachTuan_TACo-ISP_3SV.xlsx):** Pipeline camera → DPU chạy thông suốt trên phần cứng AMD Kria KV260.
- **Cảm biến:** Sony IMX219 (1080p RAW10 RGGB qua cổng J9 MIPI CSI-2).
- **DPU Accelerator:** DPUCZDX8G v4.1 (B4096 @ 300MHz/600MHz).
- **Mô hình AI:** YOLOX-nano (INT8 affine quantized).
- **DPU Subgraphs:** 1 (ĐẠT CHUẨN G0 — Đồ thị nguyên vẹn, 0 phân mảnh CPU)

## 2. Thông tin Phần cứng & Nền tảng Thực nghiệm
- **Bo mạch / Nền tảng:** ZynqMP SMK-K26 Rev1/B/A
- **CPU:** 4 cores (ARM Cortex-A53 MPCore (ARMv8-A) @ 1.33 GHz)
- **Hệ điều hành / Nhân:** Linux 5.15.36-xilinx-v2022.2 (aarch64) [PetaLinux 2022.2_release_S10071807 (honister)]
- **Kiến trúc DPU:** DPU Arch:DPUCZDX8G_ISA1_B4096
- **Overlay Đang nạp:** kv260-benchmark-b4096
- **Bitstream Hash (SHA256):** 7d12c877e0fde40a243d2350b1a2227f565788bf9e2dcae4439d07f213d40a3f
- **Git Commit Hash:** 9523951
- **Trình biên dịch:** g++ (GCC) 11.2.0

## 3. Kết quả Thực nghiệm Pipeline Camera -> DPU (Schema T-A1)

| Cấu hình | Thu nhận & ISP (`capture_isp_ms`) | Tiền xử lý CPU (`preproc_ms`) | Sao chép DMA (`dma_sync_ms`) | DPU Suy luận (`dpu_infer_ms`) | Hậu xử lý NMS (`postproc_ms`) | Tổng độ trễ (`total_latency_ms`) | Thông lượng (`FPS`) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **G0_YOLOX_nano_SYNTHETIC_DEMO** | 2.850 ms | 6.895 ms | 0.175 ms | 4.302 ms | 0.467 ms | **14.682 ms** | **68.11 FPS** |

## 4. Đánh giá Nghiệm thu Cổng G0 (Acceptance Checklist)
- [x] **C0.1 (SD Image & DPU Boot):** Hoàn thành Tuần 1 (`xilinx-kv260-dpu-v2022.2-v3.0.0.img.gz`).
- [x] **C0.2 (Camera Bring-Up):** Hoàn thành Tuần 2 (Driver IMX219, V4L2 node, bắt khung ảnh RAW10).
- [x] **C0.3 (Baseline Software):** Hoàn thành Tuần 3 (Ứng dụng `baseline_ba` C++17, phân rã độ trễ chuẩn).
- [ ] **C0.4 (Pipeline Chạy Thông — Chưa đạt trên phần cứng thật):** Thử nghiệm chạy ở chế độ giả lập (SYNTHETIC_DEMO: thiếu luồng camera thật hoặc dùng DPU dummy). Cần chạy lại trên camera IMX219 vật lý và xmodel thật để nghiệm thu Cổng G0.
- [x] **C0.5 (Khóa Môi trường ND1):** Dữ liệu môi trường phần cứng và SD image đã được ghi nhận đầy đủ, nghiệm thu Cổng G0 (Hoàn thành Nội dung 1: Dựng nền tảng), tiếp tục Giai đoạn 1 với Tuần 5–8 (Nội dung 2: Hệ đo lường).

## 5. Dữ liệu Thô Thực nghiệm
```csv
config,capture_isp_ms,preproc_ms,dma_sync_ms,dpu_infer_ms,postproc_ms,total_latency_ms
G0_YOLOX_nano_SYNTHETIC_DEMO,2.850,6.895,0.175,4.302,0.467,14.682
```

### Nhật ký DPU Query (`xdputil query`)
```
{
    "DPU IP Spec":{
        "DPU Core Count":1,
        "IP version":"v4.1.0",
        "generation timestamp":"2022-11-30 19-15-00",
        "git commit id":"ce8dd1",
        "git commit time":2022113019,
        "regmap":"1to1 version"
    },
    "VAI Version":{
        "libvaip-core.so":"Xilinx vaip Version: 1.0.0-a176db67b19f94b0a31f9d24ef80322efe4494ad  2022-12-27-01:24:22 ",
        "libvart-runner.so":"Xilinx vart-runner Version: 3.0.0-2efa5fe1e56c2b2c8a7e71e9fc1636242dd50a9f  2022-12-27-00:47:05 ",
        "libvitis_ai_library-dpu_task.so":"Xilinx vitis_ai_library dpu_task Version: 3.0.0-1cccff04dc341c4a6287226828f90aed56005f4f  2022-12-20 10:29:01 [UTC] ",
        "libxir.so":"Xilinx xir Version: xir-9204ac72103092a7b253a0c23ec7471481656940 2022-12-27-00:46:16",
        "target_factory":"target-factory.3.0.0 860ed0499ab009084e2df3004eeb9ae710c26351"
    },
    "kernels":[
        {
            "DPU Arch":"DPUCZDX8G_ISA1_B4096",
            "DPU Frequency (MHz)":300,
            "IP Type":"DPU",
            "Load Parallel":2,
            "Load augmentation":"enable",
            "Load minus mean":"disable",
            "Save Parallel":2,
            "XRT Frequency (MHz)":300,
            "cu_addr":"0xa0010000",
            "cu_handle":"0xaaab04c88190",
            "cu_idx":0,
            "cu_mask":1,
            "cu_name":"DPUCZDX8G:DPUCZDX8G_1",
            "device_id":0,
            "fingerprint":"0x101000056010407",
            "name":"DPU Core 0"
        }
```
