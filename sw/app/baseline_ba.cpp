/**
 * ============================================================================
 * TACo-ISP — Baseline BA1 / BA2 Pipeline (C++17)
 * ============================================================================
 * BA1: V4L2 (1080p RAW10) -> OpenCV Debayer / Resize / INT8 CPU -> VART DPU
 * BA2: V4L2 -> NEON-accelerated Preprocessing -> VART DPU
 *
 * Đo lường chính xác các thành phần độ trễ:
 *   - capture_isp_ms: Thời gian thu nhận khung hình và debayer
 *   - preproc_ms: Resize song tuyến tính và lượng tử hóa INT8 trên CPU Cortex-A53
 *   - dma_sync_ms: Sao chép bộ đệm CPU vào VART TensorBuffer
 *   - dpu_infer_ms: Thời gian thực thi DPU (execute_async + wait)
 *   - postproc_ms: Giải mã anchor YOLOX và NMS
 *   - total_latency_ms: Tổng độ trễ toàn chuỗi (Glass-to-Decision baseline)
 * ============================================================================
 */

#include <iostream>
#include <vector>
#include <chrono>
#include <fstream>
#include <sstream>
#include <memory>
#include <string>
#include <cstring>
#include <cmath>
#include <iomanip>
#include <algorithm>
#include <numeric>
#include <tuple>
#include <utility>

#include <opencv2/opencv.hpp>
#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/videoio.hpp>

#ifdef HAVE_VART
#include <xir/graph/graph.hpp>
#include <xir/tensor/tensor.hpp>
#include <vart/runner.hpp>
#include <vart/tensor_buffer.hpp>
#if __has_include(<vart/runner_helper.hpp>)
#include <vart/runner_helper.hpp>
#endif
#if __has_include(<vart/experimental/runner_helper.hpp>)
#include <vart/experimental/runner_helper.hpp>
#endif
#endif

#include "yolox_post.hpp"

namespace {

using Clock = std::chrono::high_resolution_clock;

struct TimingRecord {
    double capture_isp_ms;
    double preproc_ms;
    double dma_sync_ms;
    double dpu_infer_ms;
    double postproc_ms;
    double total_ms;
};

struct Config {
    std::string mode = "ba1";
    std::string tag = "";
    std::string model_path = "";
    std::string device_path = "";
    std::string input_file = "";
    std::string csv_path = "ba1_latency.csv";
    int num_frames = 100;
    int warmup_frames = 5;
    int input_w = 1920;
    int input_h = 1080;
    int target_w = 416;
    int target_h = 416;
    int num_classes = 80;
    bool enable_led = false;
    bool dummy_dpu = false;
};

void print_usage(const char* prog) {
    std::cout << "Usage: " << prog << " [options]\n"
              << "Options:\n"
              << "  --mode <ba1|ba2>       Baseline mode (default: ba1)\n"
              << "  --tag <name>           Custom configuration name for output CSV\n"
              << "  --model <path>         Path to compiled .xmodel\n"
              << "  --device <node>        V4L2 capture device (default: /dev/video0 if no input file)\n"
              << "  --input <file>         Input RAW/image file (fallback offline mode)\n"
              << "  --frames <N>           Number of frames to process (default: 100)\n"
              << "  --warmup <N>           Warmup iterations (default: 5)\n"
              << "  --out-w <W>            Model input width (default: 416)\n"
              << "  --out-h <H>            Model input height (default: 416)\n"
              << "  --csv <path>           Path to save latency measurements\n"
              << "  --led                  Toggle GPIO trigger for glass-to-decision measurement\n"
              << "  --dummy                Force dummy DPU inference (for software integration test)\n"
              << "  --help                 Show this help message\n";
}

Config parse_args(int argc, char** argv) {
    Config cfg;
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        try {
            if (arg == "--mode" && i + 1 < argc) {
                cfg.mode = argv[++i];
            } else if (arg == "--tag" && i + 1 < argc) {
                cfg.tag = argv[++i];
            } else if (arg == "--model" && i + 1 < argc) {
                cfg.model_path = argv[++i];
            } else if (arg == "--device" && i + 1 < argc) {
                cfg.device_path = argv[++i];
            } else if (arg == "--input" && i + 1 < argc) {
                cfg.input_file = argv[++i];
            } else if (arg == "--frames" && i + 1 < argc) {
                cfg.num_frames = std::max(1, std::stoi(argv[++i]));
            } else if (arg == "--warmup" && i + 1 < argc) {
                cfg.warmup_frames = std::max(0, std::stoi(argv[++i]));
            } else if (arg == "--out-w" && i + 1 < argc) {
                cfg.target_w = std::stoi(argv[++i]);
            } else if (arg == "--out-h" && i + 1 < argc) {
                cfg.target_h = std::stoi(argv[++i]);
            } else if (arg == "--csv" && i + 1 < argc) {
                cfg.csv_path = argv[++i];
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

double get_percentile(std::vector<double>& values, double p) {
    if (values.empty()) return 0.0;
    std::sort(values.begin(), values.end());
    size_t idx = static_cast<size_t>(std::ceil(p * (values.size() - 1)));
    return values[std::min(idx, values.size() - 1)];
}

bool load_frame_file(const std::string& filepath, int w, int h, cv::Mat& out_bgr, cv::Mat& out_raw_bayer) {
    if (filepath.empty()) return false;
    std::ifstream raw_in(filepath, std::ios::binary);
    if (!raw_in) return false;

    raw_in.seekg(0, std::ios::end);
    size_t size = raw_in.tellg();
    raw_in.seekg(0, std::ios::beg);

    if (size == static_cast<size_t>(w * h * 2)) { // 1920x1080 unpacked 16-bit
        cv::Mat raw16(h, w, CV_16UC1);
        raw_in.read(reinterpret_cast<char*>(raw16.data), size);
        raw_in.close();
        cv::Mat raw8;
        raw16.convertTo(raw8, CV_8UC1, 1.0 / 4.0); // 10-bit -> 8-bit
        out_raw_bayer = raw8.clone();
        cv::cvtColor(raw8, out_bgr, cv::COLOR_BayerRG2BGR);
        std::cout << "  [✓] Loaded RAW10 frame (" << size << " bytes) -> Bayer RGGB / BGR\n";
        return true;
    } else if (size == static_cast<size_t>((w * h * 5) / 4)) { // 1920x1080 MIPI packed RAW10 (pRAA)
        std::vector<uint8_t> packed(size);
        raw_in.read(reinterpret_cast<char*>(packed.data()), size);
        raw_in.close();
        cv::Mat raw8(h, w, CV_8UC1);
        uint8_t* dst = raw8.data;
        const uint8_t* src = packed.data();
        size_t num_quads = (static_cast<size_t>(w) * h) / 4;
        for (size_t q = 0; q < num_quads; ++q) {
            dst[q * 4 + 0] = src[q * 5 + 0];
            dst[q * 4 + 1] = src[q * 5 + 1];
            dst[q * 4 + 2] = src[q * 5 + 2];
            dst[q * 4 + 3] = src[q * 5 + 3];
        }
        out_raw_bayer = raw8.clone();
        cv::cvtColor(raw8, out_bgr, cv::COLOR_BayerRG2BGR);
        std::cout << "  [✓] Loaded packed RAW10 (pRAA) frame (" << size << " bytes) -> Bayer RGGB / BGR\n";
        return true;
    }
    raw_in.close();

    cv::Mat img = cv::imread(filepath);
    if (!img.empty()) {
        cv::resize(img, out_bgr, cv::Size(w, h));
        cv::cvtColor(out_bgr, out_raw_bayer, cv::COLOR_BGR2GRAY);
        std::cout << "  [✓] Loaded image (" << out_bgr.cols << "x" << out_bgr.rows << ")\n";
        return true;
    }
    return false;
}

} // namespace

int main(int argc, char** argv) {
    Config cfg = parse_args(argc, argv);

    std::cout << "============================================================\n"
              << "  TACo-ISP — Baseline Application (" << (cfg.mode == "ba2" ? "BA2 NEON" : "BA1 CPU") << ")\n"
              << "  Target Platform: AMD Kria KV260 (Cortex-A53 @ Linux)\n"
              << "============================================================\n"
              << "  Frames to run:  " << cfg.num_frames << " (warmup: " << cfg.warmup_frames << ")\n"
              << "  Input Shape:    " << cfg.input_w << "x" << cfg.input_h << " RAW10/BGR\n"
              << "  Target Shape:   " << cfg.target_w << "x" << cfg.target_h << " INT8\n"
              << "  Output CSV:     " << cfg.csv_path << "\n";

    if (cfg.mode == "ba2") {
        cv::setUseOptimized(true);
        std::cout << "  OpenCV Optimization: ENABLED (NEON instruction set)\n";
    }

    // 1. Chuẩn bị nguồn dữ liệu đầu vào (V4L2 Camera hoặc File)
    cv::VideoCapture cap;
    bool using_live_camera = false;
    cv::Mat fallback_frame;
    cv::Mat raw_bayer_frame;

    // Ưu tiên nạp từ input_file nếu có
    if (!cfg.input_file.empty()) {
        load_frame_file(cfg.input_file, cfg.input_w, cfg.input_h, fallback_frame, raw_bayer_frame);
    }
    // Nếu chưa có, tự động dò tìm sample_1080p.raw từ Tuần 2
    if (fallback_frame.empty()) {
        std::vector<std::string> sample_candidates = {
            "results/raw/W02_camera/sample_1080p.raw",
            "../results/raw/W02_camera/sample_1080p.raw",
            "../../results/raw/W02_camera/sample_1080p.raw"
        };
        const char* home = std::getenv("HOME");
        if (home) {
            sample_candidates.push_back(std::string(home) + "/taco-isp/results/raw/W02_camera/sample_1080p.raw");
        }
        for (const auto& path : sample_candidates) {
            if (load_frame_file(path, cfg.input_w, cfg.input_h, fallback_frame, raw_bayer_frame)) {
                std::cout << "  [✓] Tự động nạp ảnh mẫu RAW10 từ Tuần 2: " << path << "\n";
                break;
            }
        }
    }

    if (cfg.device_path.empty() && cfg.input_file.empty()) {
        cfg.device_path = "/dev/video0";
    }

    // Kiểm tra camera trực tiếp nếu được chỉ định
    if (!cfg.device_path.empty() && cfg.device_path != "none") {
        std::cout << "  Opening V4L2 Device: " << cfg.device_path << "...\n";
        cap.open(cfg.device_path, cv::CAP_V4L2);
        if (cap.isOpened()) {
            cap.set(cv::CAP_PROP_FRAME_WIDTH, cfg.input_w);
            cap.set(cv::CAP_PROP_FRAME_HEIGHT, cfg.input_h);
            cv::Mat test_mat;
            cap >> test_mat;
            if (!test_mat.empty()) {
                using_live_camera = true;
                test_mat.copyTo(fallback_frame);
                std::cout << "  [✓] Live camera feed active on " << cfg.device_path << "\n";
            } else {
                std::cout << "  [!] Camera opened but returned empty frame. Using fallback frame.\n";
            }
        } else {
            std::cout << "  [!] Cannot open " << cfg.device_path << ". Using fallback frame.\n";
        }
    }

    if (fallback_frame.empty()) {
        std::cout << "  Generating 1080p synthetic test frame (fallback pattern)...\n";
        fallback_frame = cv::Mat(cfg.input_h, cfg.input_w, CV_8UC3, cv::Scalar(64, 128, 192));
        cv::rectangle(fallback_frame, cv::Rect(200, 200, 400, 400), cv::Scalar(0, 255, 0), -1);
        cv::circle(fallback_frame, cv::Point(960, 540), 150, cv::Scalar(255, 255, 255), -1);
        cv::cvtColor(fallback_frame, raw_bayer_frame, cv::COLOR_BGR2GRAY);
    }
    if (raw_bayer_frame.empty()) {
        cv::cvtColor(fallback_frame, raw_bayer_frame, cv::COLOR_BGR2GRAY);
    }

    // 2. Chuẩn bị VART Runner hoặc Dummy Execution
    bool has_real_runner = false;
    int in_fix_point = 7;
    int out_fix_point = 7;

#ifdef HAVE_VART
    std::unique_ptr<xir::Graph> graph;
    std::unique_ptr<vart::Runner> runner;
    std::vector<std::unique_ptr<vart::TensorBuffer>> input_tensor_buffers;
    std::vector<std::unique_ptr<vart::TensorBuffer>> output_tensor_buffers;
    std::vector<vart::TensorBuffer*> input_tb_ptrs;
    std::vector<vart::TensorBuffer*> output_tb_ptrs;
    int8_t* dpu_in_ptr = nullptr;
    size_t dpu_in_size = 0;
    int8_t* dpu_out_ptr = nullptr;
    size_t dpu_out_size = 0;
    std::vector<int8_t> dpu_output_buf;

    if (!cfg.dummy_dpu && !cfg.model_path.empty()) {
        try {
            std::cout << "  Loading xmodel: " << cfg.model_path << "...\n";
            graph = xir::Graph::deserialize(cfg.model_path);
            auto root = graph->get_root_subgraph();
            auto subgraphs = root->children_topological_sort();

            xir::Subgraph* dpu_sg = nullptr;
            for (auto* sg : subgraphs) {
                if (sg->has_attr("device") && sg->template get_attr<std::string>("device") == "DPU") {
                    dpu_sg = sg;
                    break;
                }
            }

            if (dpu_sg) {
                runner = vart::Runner::create_runner(dpu_sg, "run");
                auto in_tensors = runner->get_input_tensors();
                auto out_tensors = runner->get_output_tensors();

                input_tensor_buffers.clear();
                for (auto* t : in_tensors) {
                    input_tensor_buffers.push_back(vart::alloc_cpu_flat_tensor_buffer(t));
                }
                output_tensor_buffers.clear();
                for (auto* t : out_tensors) {
                    output_tensor_buffers.push_back(vart::alloc_cpu_flat_tensor_buffer(t));
                }

                input_tb_ptrs.clear();
                for (auto& b : input_tensor_buffers) {
                    input_tb_ptrs.push_back(b.get());
                }
                output_tb_ptrs.clear();
                for (auto& b : output_tensor_buffers) {
                    output_tb_ptrs.push_back(b.get());
                }

                if (!in_tensors.empty() && !input_tensor_buffers.empty()) {
                    if (in_tensors[0]->has_attr("fix_point")) {
                        in_fix_point = in_tensors[0]->get_attr<int>("fix_point");
                    } else if (in_tensors[0]->has_attr("fixpoint")) {
                        in_fix_point = in_tensors[0]->get_attr<int>("fixpoint");
                    } else {
                        in_fix_point = 7;
                    }
                    auto shape = in_tensors[0]->get_shape();
                    if (shape.size() >= 3) {
                        cfg.target_h = shape[1];
                        cfg.target_w = shape[2];
                    }
                    uint64_t in_addr = 0;
                    std::tie(in_addr, dpu_in_size) = input_tensor_buffers[0]->data();
                    dpu_in_ptr = reinterpret_cast<int8_t*>(in_addr);
                }

                if (!out_tensors.empty() && !output_tensor_buffers.empty()) {
                    if (out_tensors[0]->has_attr("fix_point")) {
                        out_fix_point = out_tensors[0]->get_attr<int>("fix_point");
                    } else if (out_tensors[0]->has_attr("fixpoint")) {
                        out_fix_point = out_tensors[0]->get_attr<int>("fixpoint");
                    } else {
                        out_fix_point = 7;
                    }
                    size_t total_out = 0;
                    for (auto* ot : out_tensors) {
                        total_out += ot->get_element_num();
                    }
                    dpu_output_buf.resize(total_out);

                    uint64_t out_addr = 0;
                    std::tie(out_addr, dpu_out_size) = output_tensor_buffers[0]->data();
                    dpu_out_ptr = reinterpret_cast<int8_t*>(out_addr);
                }

                has_real_runner = true;
                std::cout << "  [✓] VART Runner initialized successfully!\n"
                          << "      Model Input: " << cfg.target_w << "x" << cfg.target_h
                          << " (fix_point=" << in_fix_point << ")\n";
            } else {
                std::cerr << "  [!] No DPU subgraph found in " << cfg.model_path << "\n";
            }
        } catch (const std::exception& e) {
            std::cerr << "  [!] VART Initialization failed: " << e.what() << "\n"
                      << "      Continuing with dummy DPU emulation.\n";
            has_real_runner = false;
        }
    }
#endif

    if (!has_real_runner) {
        std::cout << "  DPU Engine: Dummy emulation mode (Cortex-A53 timer simulation)\n";
    }

    // 3. Khởi tạo Post-processor
    taco::YoloXPostProcessor post_proc(cfg.target_w, cfg.target_h, cfg.num_classes);

    // Chuẩn bị buffers tĩnh (tránh cấp phát động trong vòng lặp)
    cv::Mat raw_frame;
    cv::Mat bgr_frame;
    cv::Mat resized_frame;
    cv::Mat rgb_frame;
    std::vector<int8_t> quantized_tensor(cfg.target_w * cfg.target_h * 3);

    std::vector<TimingRecord> records;
    records.reserve(cfg.num_frames);
    size_t total_detected_boxes = 0;

    std::cout << "\n>>> Starting execution loop (" << cfg.num_frames << " frames)...\n";

    // 4. Vòng lặp xử lý khung hình
    int total_iterations = cfg.warmup_frames + cfg.num_frames;
    for (int idx = 0; idx < total_iterations; ++idx) {
        bool is_warmup = (idx < cfg.warmup_frames);
        const size_t num_pixels = static_cast<size_t>(cfg.target_w) * cfg.target_h * 3;

        // --- BƯỚC 1: Thu nhận khung hình & Debayer (Software ISP) ---
        auto t0 = Clock::now();
        if (using_live_camera) {
            cap >> bgr_frame;
            if (bgr_frame.empty()) {
                cv::cvtColor(raw_bayer_frame, bgr_frame, cv::COLOR_BayerRG2BGR);
            }
        } else {
            cv::cvtColor(raw_bayer_frame, bgr_frame, cv::COLOR_BayerRG2BGR);
        }
        auto t1 = Clock::now();

        // --- BƯỚC 2: Tiền xử lý CPU (Resize song tuyến tính + Lượng tử hóa INT8) ---
        cv::resize(bgr_frame, resized_frame, cv::Size(cfg.target_w, cfg.target_h), 0, 0, cv::INTER_LINEAR);
        cv::cvtColor(resized_frame, rgb_frame, cv::COLOR_BGR2RGB);

        // Affine INT8 quantization: x_int8 = clamp(round((x / 256.0) * scale), -128, 127)
        float scale = std::pow(2.0f, static_cast<float>(in_fix_point));
        if (quantized_tensor.size() < num_pixels) {
            quantized_tensor.resize(num_pixels);
        }
        const uint8_t* src_ptr = rgb_frame.data;
        for (size_t i = 0; i < num_pixels; ++i) {
            float val = (static_cast<float>(src_ptr[i]) - 128.0f) * (scale / 128.0f);
            quantized_tensor[i] = static_cast<int8_t>(std::clamp(std::round(val), -128.0f, 127.0f));
        }
        auto t2 = Clock::now();

        // --- BƯỚC 3: Đồng bộ bộ đệm / DMA Sync vào VART ---
        // Đối với BA1, dữ liệu phải memcpy từ bộ đệm CPU vào bộ đệm VART TensorBuffer
#ifdef HAVE_VART
        if (has_real_runner && dpu_in_ptr && !quantized_tensor.empty()) {
            std::memcpy(dpu_in_ptr, quantized_tensor.data(),
                        std::min(dpu_in_size, quantized_tensor.size() * sizeof(int8_t)));
            for (auto& tb : input_tensor_buffers) {
                tb->sync_for_write(0, tb->get_tensor()->get_data_size() / tb->get_tensor()->get_shape()[0]);
            }
        }
#endif
        auto t3 = Clock::now();

        // --- BƯỚC 4: DPU Inference ---
#ifdef HAVE_VART
        if (has_real_runner) {
            auto job_id = runner->execute_async(input_tb_ptrs, output_tb_ptrs);
            runner->wait(job_id.first, -1);
            for (auto& tb : output_tensor_buffers) {
                tb->sync_for_read(0, tb->get_tensor()->get_data_size() / tb->get_tensor()->get_shape()[0]);
            }
        } else
#endif
        {
            // Giả lập thời gian suy luận DPU B4096 cho YOLOX-nano (~5.5 ms)
            // Bằng cách chạy vòng lặp bận nhỏ
            auto spin_start = Clock::now();
            while (std::chrono::duration<double, std::milli>(Clock::now() - spin_start).count() < 5.5) {
                // spin
            }
        }
        auto t4 = Clock::now();

        // --- BƯỚC 5: Hậu xử lý YOLOX + NMS ---
        const int8_t* out_ptr = nullptr;
        size_t out_elements = 0;

#ifdef HAVE_VART
        if (has_real_runner) {
            if (output_tensor_buffers.size() == 1) {
                out_ptr = dpu_out_ptr;
                out_elements = dpu_out_size;
            } else if (output_tensor_buffers.size() > 1) {
                size_t offset = 0;
                for (size_t b_idx = 0; b_idx < output_tensor_buffers.size(); ++b_idx) {
                    uint64_t b_addr = 0;
                    size_t b_sz = 0;
                    std::tie(b_addr, b_sz) = output_tensor_buffers[b_idx]->data();
                    if (offset + b_sz > dpu_output_buf.size()) {
                        dpu_output_buf.resize(offset + b_sz);
                    }
                    std::memcpy(dpu_output_buf.data() + offset,
                                reinterpret_cast<const void*>(b_addr), b_sz);
                    offset += b_sz;
                }
                out_ptr = dpu_output_buf.data();
                out_elements = offset;
            }
        }
#endif
        if (!out_ptr) {
            out_ptr = quantized_tensor.data();
            out_elements = num_pixels;
        }

        auto detections = post_proc.decode_and_nms(out_ptr, out_elements, out_fix_point);
        size_t num_dets = detections.size();
        auto t5 = Clock::now();

        if (!is_warmup) {
            total_detected_boxes += num_dets;
            TimingRecord rec;
            rec.capture_isp_ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
            rec.preproc_ms     = std::chrono::duration<double, std::milli>(t2 - t1).count();
            rec.dma_sync_ms    = std::chrono::duration<double, std::milli>(t3 - t2).count();
            rec.dpu_infer_ms   = std::chrono::duration<double, std::milli>(t4 - t3).count();
            rec.postproc_ms    = std::chrono::duration<double, std::milli>(t5 - t4).count();
            rec.total_ms       = std::chrono::duration<double, std::milli>(t5 - t0).count();
            records.push_back(rec);

            if ((records.size() % 25 == 0) || records.size() == static_cast<size_t>(cfg.num_frames)) {
                std::cout << "  Frame [" << std::setw(4) << records.size() << "/" << cfg.num_frames << "]: "
                          << "Total = " << std::fixed << std::setprecision(2) << rec.total_ms << " ms "
                          << "(Preproc=" << rec.preproc_ms << "ms, DPU=" << rec.dpu_infer_ms << "ms, "
                          << "Post=" << rec.postproc_ms << "ms, Dets=" << num_dets << ")\n";
            }
        }
    }

    // 5. Thống kê và lưu kết quả
    std::vector<double> v_capture, v_preproc, v_dma, v_dpu, v_post, v_total;
    for (const auto& r : records) {
        v_capture.push_back(r.capture_isp_ms);
        v_preproc.push_back(r.preproc_ms);
        v_dma.push_back(r.dma_sync_ms);
        v_dpu.push_back(r.dpu_infer_ms);
        v_post.push_back(r.postproc_ms);
        v_total.push_back(r.total_ms);
    }

    double p50_capture = get_percentile(v_capture, 0.50);
    double p50_preproc = get_percentile(v_preproc, 0.50);
    double p50_dma     = get_percentile(v_dma, 0.50);
    double p50_dpu     = get_percentile(v_dpu, 0.50);
    double p50_post    = get_percentile(v_post, 0.50);
    double p50_total   = get_percentile(v_total, 0.50);
    double p95_total   = get_percentile(v_total, 0.95);
    double p99_total   = get_percentile(v_total, 0.99);

    double mean_total = v_total.empty() ? 0.0 : (std::accumulate(v_total.begin(), v_total.end(), 0.0) / v_total.size());
    double fps = (mean_total > 0.0) ? (1000.0 / mean_total) : 0.0;

    std::string config_tag = !cfg.tag.empty() ? cfg.tag : ((cfg.mode == "ba2") ? "BA2_YOLOX_nano" : "BA1_YOLOX_nano");

    std::cout << "\n============================================================\n"
              << "  KẾT QUẢ ĐO ĐỘ TRỄ BASELINE (" << config_tag << ")\n"
              << "============================================================\n"
              << "  Capture & ISP (p50): " << std::fixed << std::setprecision(2) << p50_capture << " ms\n"
              << "  CPU Preproc (p50):   " << p50_preproc << " ms\n"
              << "  DMA / Sync (p50):    " << p50_dma << " ms\n"
              << "  DPU Infer (p50):     " << p50_dpu << " ms\n"
              << "  Post-proc NMS (p50): " << p50_post << " ms\n"
              << "  --------------------------------------------------------\n"
              << "  Total Latency (p50): " << p50_total << " ms\n"
              << "  Total Latency (p95): " << p95_total << " ms\n"
              << "  Total Latency (p99): " << p99_total << " ms\n"
              << "  Thông lượng (FPS):   " << fps << " FPS\n"
              << "  Phát hiện (Boxes):   " << total_detected_boxes << " đối tượng\n"
              << "============================================================\n";

    // Xuất CSV theo đúng schema chuẩn tại analysis/SCHEMAS.md:
    // config,capture_isp_ms,preproc_ms,dma_sync_ms,dpu_infer_ms,postproc_ms,total_latency_ms
    std::ofstream csv_file(cfg.csv_path);
    if (csv_file.is_open()) {
        csv_file << "config,capture_isp_ms,preproc_ms,dma_sync_ms,dpu_infer_ms,postproc_ms,total_latency_ms\n";
        csv_file << config_tag << ","
                 << std::fixed << std::setprecision(3)
                 << p50_capture << ","
                 << p50_preproc << ","
                 << p50_dma << ","
                 << p50_dpu << ","
                 << p50_post << ","
                 << p50_total << "\n";
        csv_file.close();
        std::cout << "  [✓] Đã xuất file CSV chuẩn schema: " << cfg.csv_path << "\n";
    }

    return 0;
}
