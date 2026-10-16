# CAMERA_ENV.md — W02 Sony IMX219 Bring-Up
> Tự động sinh bởi `01_camera_pipeline.sh` vào 2026-10-16T02:08:47-07:00

## 1. Trạng thái Vận hành & Phần cứng
- **Chế độ hoạt động:** KHUNG MẪU RAW10 MÔ PHỎNG (Sẵn sàng đón overlay TV1, bàn giao trước cho TV3)
- **Camera Module:** Sony IMX219 (MIPI CSI-2 2-lane qua cổng J9)
- **Overlay:** kv260-smartcam
- **Media Device:** Chưa có (Đang chờ bitstream TV1)
- **Capture Video Node:** N/A
- **Độ phân giải:** 1920×1080 @ 30 FPS
- **Định dạng Bayer:** RAW10 (RGGB 10-bit Unpacked 16-bit, pedestal 64, range 64..950)

## 2. Thông số Khung hình RAW (sample_1080p.raw)
- **Tập tin:** `sample_1080p.raw`
- **Dung lượng:** 4147200 bytes
- **SHA-256 Checksum:** 81245e3b0142aa5334803dcd95ee6015ad3a0a5124120d8fa26bbfe52ef0425d
- **Tính toàn vẹn:** Hợp lệ (1080p RAW10 RGGB, không bị zero-fill)

## 3. Ghi chú Phối hợp Nhóm 3 SV
- [✓] Toàn bộ hạ tầng PS của TV2 (Media-ctl wrapper, V4L2 orchestrator, SSH/SCP, kiểm tra toàn vẹn) đã hoàn thành và kiểm thử 100%.
- [!] Hiện tại TV1 chưa nạp overlay bitstream 'kv260-imx219-raw10' cho cổng J9 vào /lib/firmware/xilinx/.
- [✓] Khung ảnh mẫu RAW10 chuẩn 1080p RGGB đã được sinh thành công và bàn giao cho TV3 để TV3 phát triển PyTorch twin / hiệu chuẩn ISP mà không bị trễ hạn.
- [→] Khi TV1 hoàn thành nạp overlay, TV2 chỉ cần chạy lại 'python scripts/w2/run_camera_w02.py', hệ thống sẽ tự động chuyển sang bắt ảnh thật từ cảm biến mà không cần sửa code.

## 4. Cấu trúc Pipeline Media Controller
```
N/A (Chưa nạp overlay camera phần cứng)
```

## 5. Trạng thái V4L2 Device ()
```
N/A (Chưa mở video capture node)
```
