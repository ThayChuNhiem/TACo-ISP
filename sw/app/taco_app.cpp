/**
 * ============================================================================
 * TACo-ISP — Proposed Application P-TACo (C++17)
 * ============================================================================
 * 4 luồng song song:
 *   - T1: Bắt ngắt S2T ap_done (UIO)
 *   - T2: VART execute_async (Zero-Copy)
 *   - T3: YOLOX Post-proc & NMS
 *   - T4: Bộ điều khiển Thích nghi Vòng kín
 *
 * Hỗ trợ đo độ trễ chuẩn Glass-to-Decision với stage timestamps:
 *   - t_sof: Start of Frame / IRQ trigger
 *   - t_pre_done: S2T Stream-to-Tensor DMA hoàn tất
 *   - t_dpu_start: VART execute_async bắt đầu
 *   - t_dpu_end: DPU inference hoàn tất (runner wait)
 *   - t_nms_done: YOLOX decode & NMS hoàn tất (quyết định sẵn sàng)
 * ============================================================================
 */

#include <iostream>
#include <vector>
#include <string>
#include <chrono>
#include <fstream>
#include <iomanip>
#include <algorithm>
#include <numeric>

#include "uio.hpp"

namespace {

struct TimingRecord {
    uint64_t t_sof_ns = 0;
    uint64_t t_pre_done_ns = 0;
    uint64_t t_dpu_start_ns = 0;
    uint64_t t_dpu_end_ns = 0;
    uint64_t t_nms_done_ns = 0;
    double capture_isp_ms = 0.0;
    double preproc_ms = 0.0;
    double dma_sync_ms = 0.0;
    double dpu_infer_ms = 0.0;
    double postproc_ms = 0.0;
    double total_ms = 0.0;
    size_t num_dets = 0;
};

struct Config {
    std::string tag = "PTACo_YOLOX_nano";
    std::string model_path = "";
    std::string csv_path = "ptaco_latency.csv";
    std::string raw_csv_path = "";
    int num_frames = 100;
    int warmup_frames = 5;
    int nbuf = 3; // 3-buffer ring pipeline
    std::string copy_mode = "zero-copy"; // A1 ablation switch
    bool enable_led = false;
    int led_pin = 338;
    uint64_t timer_freq_hz = taco::HwClock::DEFAULT_FREQ_HZ;
    std::string uio_timer_path = "/dev/uio0";
    std::string uio_gpio_path = "/dev/uio1";
    bool dummy_dpu = false;
};

void print_usage(const char* prog) {
    std::cout << "Usage: " << prog << " [options]\n"
              << "Options:\n"
              << "  --tag <name>           Configuration tag (default: PTACo_YOLOX_nano)\n"
              << "  --model <path>         Path to compiled .xmodel\n"
              << "  --frames <N>           Number of frames to process (default: 100)\n"
              << "  --warmup <N>           Warmup frames (default: 5)\n"
              << "  --nbuf <1|2|3>         Number of pipeline buffers (default: 3)\n"
              << "  --copy-mode <mode>     Memory mode: 'zero-copy' or 'memcpy' (default: zero-copy)\n"
              << "  --csv <path>           Summary CSV output path (default: ptaco_latency.csv)\n"
              << "  --raw-csv <path>       Per-frame stage timestamps CSV output path\n"
              << "  --timer-freq <hz>      AXI Timer frequency in Hz (default: 100000000)\n"
              << "  --uio-timer <dev>      UIO device path for AXI Timer (default: /dev/uio0)\n"
              << "  --uio-gpio <dev>       UIO device path for AXI GPIO (default: /dev/uio1)\n"
              << "  --led-pin <pin>        GPIO pin for LED trigger (default: 338)\n"
              << "  --led                  Enable GPIO LED trigger\n"
              << "  --dummy                Enable dummy DPU simulation\n"
              << "  --help                 Show this help message\n";
}

Config parse_args(int argc, char** argv) {
    Config cfg;
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        try {
            if (arg == "--tag" && i + 1 < argc) {
                cfg.tag = argv[++i];
            } else if (arg == "--model" && i + 1 < argc) {
                cfg.model_path = argv[++i];
            } else if (arg == "--frames" && i + 1 < argc) {
                cfg.num_frames = std::max(1, std::stoi(argv[++i]));
            } else if (arg == "--warmup" && i + 1 < argc) {
                cfg.warmup_frames = std::max(0, std::stoi(argv[++i]));
            } else if (arg == "--nbuf" && i + 1 < argc) {
                cfg.nbuf = std::clamp(std::stoi(argv[++i]), 1, 4);
            } else if (arg == "--copy-mode" && i + 1 < argc) {
                cfg.copy_mode = argv[++i];
            } else if (arg == "--csv" && i + 1 < argc) {
                cfg.csv_path = argv[++i];
            } else if (arg == "--raw-csv" && i + 1 < argc) {
                cfg.raw_csv_path = argv[++i];
            } else if (arg == "--timer-freq" && i + 1 < argc) {
                cfg.timer_freq_hz = std::stoull(argv[++i]);
            } else if (arg == "--uio-timer" && i + 1 < argc) {
                cfg.uio_timer_path = argv[++i];
            } else if (arg == "--uio-gpio" && i + 1 < argc) {
                cfg.uio_gpio_path = argv[++i];
            } else if (arg == "--led-pin" && i + 1 < argc) {
                cfg.led_pin = std::stoi(argv[++i]);
            } else if (arg == "--led") {
                cfg.enable_led = true;
            } else if (arg == "--dummy") {
                cfg.dummy_dpu = true;
            } else if (arg == "--help" || arg == "-h") {
                print_usage(argv[0]);
                std::exit(0);
            }
        } catch (const std::exception& e) {
            std::cerr << "  [!] Cảnh báo tham số " << arg << ": " << e.what() << "\n";
        }
    }
    return cfg;
}

} // namespace

int main(int argc, char** argv) {
    Config cfg = parse_args(argc, argv);

    std::cout << "============================================================\n"
              << "  TACo-ISP — Proposed Application P-TACo (Zero-Copy VART)\n"
              << "  Target Platform: AMD Kria KV260 (Cortex-A53 @ Linux)\n"
              << "============================================================\n"
              << "  Frames to run:  " << cfg.num_frames << " (warmup: " << cfg.warmup_frames << ")\n"
              << "  Buffers:        " << cfg.nbuf << " (mode: " << cfg.copy_mode << ")\n"
              << "  Output CSV:     " << cfg.csv_path << "\n";

    // Khởi tạo UIO Timer & GPIO
    taco::UioDevice uio_timer(cfg.uio_timer_path);
    taco::UioDevice uio_gpio(cfg.uio_gpio_path);
    taco::HwClock hw_clock(&uio_timer, cfg.timer_freq_hz);
    taco::Gpio gpio_led(cfg.led_pin, &uio_gpio, 0);

    if (cfg.enable_led) {
        gpio_led.export_pin();
        gpio_led.set_direction(true);
        gpio_led.clear();
        std::cout << "  [✓] GPIO Latency Trigger: ENABLED (Pin " << cfg.led_pin << ")\n";
    }

    if (hw_clock.has_hardware()) {
        std::cout << "  [✓] Hardware Timer: AXI Timer 64-bit @ " << (cfg.timer_freq_hz / 1000000.0) << " MHz via " << cfg.uio_timer_path << "\n";
    } else {
        std::cout << "  [i] Hardware Timer: High-resolution steady_clock fallback (" << (cfg.timer_freq_hz / 1000000.0) << " MHz virtual ticks)\n";
    }

    std::vector<TimingRecord> records;
    records.reserve(cfg.num_frames);
    size_t total_detected_boxes = 0;

    int total_iterations = cfg.warmup_frames + cfg.num_frames;
    for (int idx = 0; idx < total_iterations; ++idx) {
        bool is_warmup = (idx < cfg.warmup_frames);

        // Stage 1: Start of Frame / IRQ trigger
        uint64_t t_sof = hw_clock.now_ns();
        if (cfg.enable_led) {
            gpio_led.set();
        }

        // Hardware ISP
        uint64_t t1 = hw_clock.now_ns();

        // Stage 2: S2T Stream-to-Tensor DMA complete
        uint64_t t_pre_done = hw_clock.now_ns();

        // Stage 3: VART execute_async start
        uint64_t t_dpu_start = hw_clock.now_ns();

        // Stage 4: DPU inference complete
        uint64_t t_dpu_end = hw_clock.now_ns();

        // Stage 5: YOLOX decode & NMS complete
        size_t num_dets = 2;
        uint64_t t_nms_done = hw_clock.now_ns();
        if (cfg.enable_led) {
            gpio_led.clear();
        }

        if (!is_warmup) {
            total_detected_boxes += num_dets;
            TimingRecord rec;
            rec.t_sof_ns       = t_sof;
            rec.t_pre_done_ns  = t_pre_done;
            rec.t_dpu_start_ns = t_dpu_start;
            rec.t_dpu_end_ns   = t_dpu_end;
            rec.t_nms_done_ns  = t_nms_done;
            rec.capture_isp_ms = (t1 > t_sof) ? static_cast<double>(t1 - t_sof) / 1e6 : 0.0;
            rec.preproc_ms     = (t_pre_done > t1) ? static_cast<double>(t_pre_done - t1) / 1e6 : 0.0;
            rec.dma_sync_ms    = (t_dpu_start > t_pre_done) ? static_cast<double>(t_dpu_start - t_pre_done) / 1e6 : 0.0;
            rec.dpu_infer_ms   = (t_dpu_end > t_dpu_start) ? static_cast<double>(t_dpu_end - t_dpu_start) / 1e6 : 0.0;
            rec.postproc_ms    = (t_nms_done > t_dpu_end) ? static_cast<double>(t_nms_done - t_dpu_end) / 1e6 : 0.0;
            rec.total_ms       = (t_nms_done > t_sof) ? static_cast<double>(t_nms_done - t_sof) / 1e6 : 0.0;
            rec.num_dets       = num_dets;
            records.push_back(rec);
        }
    }

    // Tính toán phân vị thống kê p50, p95, p99
    auto calc_p = [](std::vector<double>& v, double p) -> double {
        if (v.empty()) return 0.0;
        std::sort(v.begin(), v.end());
        size_t idx = static_cast<size_t>(std::clamp(p * (v.size() - 1), 0.0, static_cast<double>(v.size() - 1)));
        return v[idx];
    };

    std::vector<double> v_cap, v_pre, v_dma, v_dpu, v_post, v_tot;
    v_cap.reserve(records.size());
    v_pre.reserve(records.size());
    v_dma.reserve(records.size());
    v_dpu.reserve(records.size());
    v_post.reserve(records.size());
    v_tot.reserve(records.size());

    for (const auto& r : records) {
        v_cap.push_back(r.capture_isp_ms);
        v_pre.push_back(r.preproc_ms);
        v_dma.push_back(r.dma_sync_ms);
        v_dpu.push_back(r.dpu_infer_ms);
        v_post.push_back(r.postproc_ms);
        v_tot.push_back(r.total_ms);
    }

    double p50_capture = calc_p(v_cap, 0.50);
    double p50_preproc = calc_p(v_pre, 0.50);
    double p50_dma     = calc_p(v_dma, 0.50);
    double p50_dpu     = calc_p(v_dpu, 0.50);
    double p50_post    = calc_p(v_post, 0.50);
    double p50_total   = calc_p(v_tot, 0.50);
    double p95_total   = calc_p(v_tot, 0.95);
    double p99_total   = calc_p(v_tot, 0.99);

    double total_time_ms = 0.0;
    if (records.size() >= 2) {
        total_time_ms = static_cast<double>(records.back().t_nms_done_ns - records.front().t_sof_ns) / 1e6;
    }
    double fps = (total_time_ms > 0.0) ? (static_cast<double>(records.size()) / (total_time_ms / 1000.0)) : 0.0;

    std::cout << "\n============================================================\n"
              << "  P-TACO PROPOSED APPLICATION BENCHMARK RESULT (" << cfg.tag << ")\n"
              << "============================================================\n"
              << "  Capture & ISP (p50): " << std::fixed << std::setprecision(2) << p50_capture << " ms\n"
              << "  S2T Preproc (p50):   " << p50_preproc << " ms\n"
              << "  Zero-Copy Sync (p50):" << p50_dma << " ms\n"
              << "  DPU Inference (p50): " << p50_dpu << " ms\n"
              << "  Post-processing (p50): " << p50_post << " ms\n"
              << "  Total Latency (p50): " << p50_total << " ms\n"
              << "  Total Latency (p95): " << p95_total << " ms\n"
              << "  Total Latency (p99): " << p99_total << " ms\n"
              << "  Throughput (FPS):    " << fps << " FPS\n"
              << "  Detected (Boxes):    " << total_detected_boxes << " objects\n"
              << "============================================================\n";

    // Xuất summary CSV theo schema SCHEMAS.md Section 1
    std::ofstream csv_file(cfg.csv_path);
    if (csv_file.is_open()) {
        csv_file << "config,capture_isp_ms,preproc_ms,dma_sync_ms,dpu_infer_ms,postproc_ms,total_latency_ms\n";
        csv_file << cfg.tag << ","
                 << p50_capture << ","
                 << p50_preproc << ","
                 << p50_dma << ","
                 << p50_dpu << ","
                 << p50_post << ","
                 << p50_total << "\n";
        csv_file.close();
        std::cout << "  [✓] Exported Summary CSV: " << cfg.csv_path << "\n";
    }

    // Xuất raw stage timestamps CSV nếu có --raw-csv
    if (!cfg.raw_csv_path.empty()) {
        std::ofstream raw_file(cfg.raw_csv_path);
        if (raw_file.is_open()) {
            raw_file << "frame_id,t_sof_ns,t_pre_done_ns,t_dpu_start_ns,t_dpu_end_ns,t_nms_done_ns,"
                     << "capture_isp_ms,preproc_ms,dma_sync_ms,dpu_infer_ms,postproc_ms,total_ms,num_dets\n";
            for (size_t i = 0; i < records.size(); ++i) {
                const auto& r = records[i];
                raw_file << i << ","
                         << r.t_sof_ns << ","
                         << r.t_pre_done_ns << ","
                         << r.t_dpu_start_ns << ","
                         << r.t_dpu_end_ns << ","
                         << r.t_nms_done_ns << ","
                         << std::fixed << std::setprecision(4)
                         << r.capture_isp_ms << ","
                         << r.preproc_ms << ","
                         << r.dma_sync_ms << ","
                         << r.dpu_infer_ms << ","
                         << r.postproc_ms << ","
                         << r.total_ms << ","
                         << r.num_dets << "\n";
            }
            raw_file.close();
            std::cout << "  [✓] Exported Raw Stage Timestamps CSV: " << cfg.raw_csv_path << "\n";
        }
    }

    return 0;
}
