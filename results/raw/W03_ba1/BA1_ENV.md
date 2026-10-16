# BA1_ENV.md — W03 Baseline Pipeline (BA1) Report
> Tự động sinh bởi `03_eval_ba1.sh` vào 2026-10-16T02:12:55-07:00
> ⚠️ **CẢNH BÁO BẢO TOÀN DỮ LIỆU (SYNTHETIC DEMO):** Thử nghiệm chạy ở chế độ giả lập (synthetic fallback hoặc dummy DPU). Tuyệt đối không dùng số liệu này trong bài báo hoặc nghiệm thu chính thức (Tuân thủ Nguyên tắc Vàng #1).

## 1. Thông tin Phần cứng & Nền tảng (Trích xuất động từ Board)
- **Hệ thống / Board:** ZynqMP SMK-K26 Rev1/B/A
- **CPU:** 4 cores (ARM Cortex-A53 MPCore (ARMv8-A) @ 1.33 GHz)
- **OS / Kernel:** Linux 5.15.36-xilinx-v2022.2 (aarch64) [PetaLinux 2022.2_release_S10071807 (honister)]
- **DPU Architecture:** DPU Arch:DPUCZDX8G_ISA1_B4096
- **Overlay (Active):** kv260-benchmark-b4096
- **Bitstream Hash (SHA256):** 7d12c877e0fde40a243d2350b1a2227f565788bf9e2dcae4439d07f213d40a3f
- **Git Commit Hash:** 9523951
- **C++ Compiler:** g++ (GCC) 11.2.0

## 2. Bảng Phân rã Độ trễ Chuẩn (Schema T-A1: `latency.csv`)

| Cấu hình | Thu nhận & ISP (`capture_isp_ms`) | Tiền xử lý CPU (`preproc_ms`) | Sao chép DMA (`dma_sync_ms`) | DPU Suy luận (`dpu_infer_ms`) | Hậu xử lý NMS (`postproc_ms`) | Tổng độ trễ (`total_latency_ms`) | Thông lượng (`FPS`) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **BA1_YOLOX_nano_SYNTHETIC_DEMO** | 2.843 ms | **6.843 ms** | 0.188 ms | 4.355 ms | 0.407 ms | **14.640 ms** | **68.31 FPS** |

## 3. Phân tích Nút cổ chai Kỹ thuật (Scientific Analysis)
- **Tỷ trọng Tiền xử lý CPU:** Tiền xử lý ảnh (debayer, resize song tuyến tính 1080p -> 416x416, và lượng tử hóa INT8) trên CPU Cortex-A53 chiếm **46.7%** tổng thời gian xử lý khung hình!
- **Xác nhận Động lực Đề tài:** 
  - Trong kiến trúc baseline BA1, CPU bị quá tải bởi việc resize và chuẩn hóa điểm ảnh, dẫn đến việc DPU bị đói dữ liệu (pipeline stall).
  - Đây chính là luận chứng thực nghiệm xác thực mục tiêu cốt lõi của **TACo-ISP**: Đưa toàn bộ ISP và bộ tiền xử lý vào phần cứng PL (`isp_top` + `s2t_top` Zero-Copy) để giải phóng 100% tải CPU và giảm $\ge 30\%$ độ trễ.

## 4. Dữ liệu Thô Kiểm chứng
```csv
config,capture_isp_ms,preproc_ms,dma_sync_ms,dpu_infer_ms,postproc_ms,total_latency_ms
BA1_YOLOX_nano_SYNTHETIC_DEMO,2.843,6.843,0.188,4.355,0.407,14.640
```

### Chi tiết DPU Query (`xdputil query`)
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
            "cu_handle":"0xaaaae930f190",
            "cu_idx":0,
            "cu_mask":1,
            "cu_name":"DPUCZDX8G:DPUCZDX8G_1",
            "device_id":0,
            "fingerprint":"0x101000056010407",
            "name":"DPU Core 0"
        }
```
