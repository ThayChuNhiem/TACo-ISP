/**
 * ============================================================================
 * TACo-ISP — Controller Standalone Reference (C++17)
 * ============================================================================
 * Tham chiếu bộ điều khiển thích nghi vòng kín chạy trên ARM Cortex-A53.
 * Ngân sách thời gian: < 0.5 ms / khung hình.
 * ============================================================================
 */

#include <iostream>
#include <vector>
#include <chrono>
#include <cmath>

namespace taco {

struct IspStats {
    uint32_t histogram[64];
    uint32_t sat_cnt;
    uint32_t noise_est;
};

struct IspParams {
    uint32_t blc_r;
    uint32_t blc_gr;
    uint32_t blc_gb;
    uint32_t blc_b;
    uint32_t nr_sigma;
    uint32_t wb_gain_r;
    uint32_t wb_gain_b;
};

class AdaptiveControllerRef {
public:
    AdaptiveControllerRef() = default;

    IspParams compute(const IspStats& stats, float dpu_confidence) {
        IspParams p;
        p.blc_r = 64;
        p.blc_gr = 64;
        p.blc_gb = 64;
        p.blc_b = 64;

        // Thích nghi mức lọc nhiễu NR dựa trên độ tin cậy DPU và ước lượng nhiễu
        if (dpu_confidence < 0.4f) {
            p.nr_sigma = std::min(255u, static_cast<uint32_t>(stats.noise_est * 1.5f + 16));
        } else {
            p.nr_sigma = static_cast<uint32_t>(stats.noise_est);
        }

        p.wb_gain_r = 1024;
        p.wb_gain_b = 1024;
        return p;
    }
};

} // namespace taco

int main() {
    std::cout << "[TACo-ISP] Controller Reference C++ benchmark starting...\n";
    taco::AdaptiveControllerRef ctrl;
    taco::IspStats stats{};
    stats.noise_est = 32;

    auto t0 = std::chrono::high_resolution_clock::now();
    for (int i = 0; i < 1000; ++i) {
        auto p = ctrl.compute(stats, 0.5f);
        (void)p;
    }
    auto t1 = std::chrono::high_resolution_clock::now();
    double total_us = std::chrono::duration<double, std::micro>(t1 - t0).count();
    double avg_us = total_us / 1000.0;

    std::cout << "[TACo-ISP] 1000 controller iterations: total = " << total_us << " us, "
              << "avg = " << avg_us << " us/frame (budget: < 500 us)\n";
    return 0;
}
