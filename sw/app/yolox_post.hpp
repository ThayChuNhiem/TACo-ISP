#pragma once
/**
 * ============================================================================
 * TACo-ISP — YOLOX Post-Processing & NMS (C++17)
 * ============================================================================
 * Dùng chung chuẩn hóa cho mọi baseline (BA1, BA2, BA3) và P-TACo.
 * Giải mã 3 tầng đặc trưng (stride 8, 16, 32) và thực hiện Non-Maximum Suppression.
 * ============================================================================
 */

#include <vector>
#include <cmath>
#include <algorithm>
#include <cstdint>

namespace taco {

struct Detection {
    float x1;
    float y1;
    float x2;
    float y2;
    float score;
    int class_id;
};

class YoloXPostProcessor {
public:
    explicit YoloXPostProcessor(int input_w = 416, int input_h = 416,
                                int num_classes = 80,
                                float conf_thresh = 0.25f,
                                float nms_thresh = 0.45f)
        : input_w_(input_w), input_h_(input_h),
          num_classes_(num_classes),
          conf_thresh_(conf_thresh),
          nms_thresh_(nms_thresh) {
        generate_grids_and_strides();
    }

    void set_input_size(int w, int h) {
        if (input_w_ != w || input_h_ != h) {
            input_w_ = w;
            input_h_ = h;
            generate_grids_and_strides();
        }
    }

    /**
     * Giải mã tensor INT8 từ DPU và áp dụng NMS
     * @param feat_ptr Con trỏ dữ liệu mảng phẳng các feature maps hoặc mảng kết hợp
     * @param total_elements Tổng số phần tử
     * @param fix_point Điểm cố định DPU (scale = 2^fix_point)
     * @return Danh sách bounding boxes sau NMS
     */
    std::vector<Detection> decode_and_nms(const int8_t* feat_ptr, size_t total_elements, int fix_point) const {
        if (!feat_ptr || total_elements == 0) return {};

        float scale = std::pow(2.0f, -static_cast<float>(fix_point));
        int num_channels = 5 + num_classes_;
        size_t num_anchors = total_elements / num_channels;
        size_t actual_anchors = std::min(num_anchors, grid_x_.size());

        std::vector<Detection> candidates;
        candidates.reserve(128);

        for (size_t i = 0; i < actual_anchors; ++i) {
            size_t offset = i * num_channels;
            float obj_conf = sigmoid(static_cast<float>(feat_ptr[offset + 4]) * scale);

            if (obj_conf < conf_thresh_) continue;

            // Tìm lớp có xác suất cao nhất
            int best_cls = -1;
            float max_cls_prob = 0.0f;
            for (int c = 0; c < num_classes_; ++c) {
                float cls_prob = sigmoid(static_cast<float>(feat_ptr[offset + 5 + c]) * scale);
                if (cls_prob > max_cls_prob) {
                    max_cls_prob = cls_prob;
                    best_cls = c;
                }
            }

            float final_score = obj_conf * max_cls_prob;
            if (final_score >= conf_thresh_) {
                float stride = strides_[i];
                float cx = (static_cast<float>(feat_ptr[offset + 0]) * scale + grid_x_[i]) * stride;
                float cy = (static_cast<float>(feat_ptr[offset + 1]) * scale + grid_y_[i]) * stride;
                float exp_w = std::clamp(static_cast<float>(feat_ptr[offset + 2]) * scale, -10.0f, 10.0f);
                float exp_h = std::clamp(static_cast<float>(feat_ptr[offset + 3]) * scale, -10.0f, 10.0f);
                float w = std::exp(exp_w) * stride;
                float h = std::exp(exp_h) * stride;

                Detection det;
                det.x1 = std::max(0.0f, cx - w * 0.5f);
                det.y1 = std::max(0.0f, cy - h * 0.5f);
                det.x2 = std::min(static_cast<float>(input_w_), cx + w * 0.5f);
                det.y2 = std::min(static_cast<float>(input_h_), cy + h * 0.5f);
                if (det.x2 <= det.x1 || det.y2 <= det.y1) continue;
                det.score = final_score;
                det.class_id = best_cls;
                candidates.push_back(det);
            }
        }

        return nms(candidates);
    }

    /**
     * Non-Maximum Suppression (NMS) với ngưỡng Top-K để bảo vệ hiệu năng Cortex-A53
     */
    std::vector<Detection> nms(std::vector<Detection>& boxes, size_t max_det = 100) const {
        if (boxes.empty()) return {};

        // Top-k filtering trước NMS (tối đa 1000 candidates) tránh độ phức tạp O(N^2)
        if (boxes.size() > 1000) {
            std::partial_sort(boxes.begin(), boxes.begin() + 1000, boxes.end(), [](const Detection& a, const Detection& b) {
                return a.score > b.score;
            });
            boxes.resize(1000);
        } else {
            std::sort(boxes.begin(), boxes.end(), [](const Detection& a, const Detection& b) {
                return a.score > b.score;
            });
        }

        std::vector<Detection> result;
        result.reserve(std::min(boxes.size(), max_det));
        std::vector<bool> suppressed(boxes.size(), false);

        for (size_t i = 0; i < boxes.size(); ++i) {
            if (suppressed[i]) continue;
            result.push_back(boxes[i]);
            if (result.size() >= max_det) break;

            float area_i = (boxes[i].x2 - boxes[i].x1) * (boxes[i].y2 - boxes[i].y1);
            if (area_i <= 0.0f) continue;

            for (size_t j = i + 1; j < boxes.size(); ++j) {
                if (suppressed[j]) continue;

                float area_j = (boxes[j].x2 - boxes[j].x1) * (boxes[j].y2 - boxes[j].y1);
                if (area_j <= 0.0f) {
                    suppressed[j] = true;
                    continue;
                }

                float xx1 = std::max(boxes[i].x1, boxes[j].x1);
                float yy1 = std::max(boxes[i].y1, boxes[j].y1);
                float xx2 = std::min(boxes[i].x2, boxes[j].x2);
                float yy2 = std::min(boxes[i].y2, boxes[j].y2);

                float inter_w = std::max(0.0f, xx2 - xx1);
                float inter_h = std::max(0.0f, yy2 - yy1);
                float inter_area = inter_w * inter_h;

                float union_area = area_i + area_j - inter_area;

                if (union_area > 0.0f) {
                    float iou = inter_area / union_area;
                    if (iou > nms_thresh_) {
                        suppressed[j] = true;
                    }
                }
            }
        }
        return result;
    }

private:
    int input_w_;
    int input_h_;
    int num_classes_;
    float conf_thresh_;
    float nms_thresh_;

    std::vector<float> grid_x_;
    std::vector<float> grid_y_;
    std::vector<float> strides_;

    static inline float sigmoid(float x) {
        return 1.0f / (1.0f + std::exp(-x));
    }

    void generate_grids_and_strides() {
        grid_x_.clear();
        grid_y_.clear();
        strides_.clear();

        const std::vector<int> stride_list = {8, 16, 32};
        for (int stride : stride_list) {
            int num_grid_x = input_w_ / stride;
            int num_grid_y = input_h_ / stride;
            for (int g1 = 0; g1 < num_grid_y; ++g1) {
                for (int g0 = 0; g0 < num_grid_x; ++g0) {
                    grid_x_.push_back(static_cast<float>(g0));
                    grid_y_.push_back(static_cast<float>(g1));
                    strides_.push_back(static_cast<float>(stride));
                }
            }
        }
    }
};

} // namespace taco
