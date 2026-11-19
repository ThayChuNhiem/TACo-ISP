#ifndef _ISP_CORE_H_
#define _ISP_CORE_H_

#include <ap_int.h>
#include <ap_axi_sdata.h>
#include <hls_stream.h>

#define MAX_WIDTH  1920
#define MAX_HEIGHT 1080

// Khai báo kiểu dữ liệu cho luồng AXI4-Stream
typedef ap_axiu<16, 1, 1, 1> axis_raw10_t;
typedef ap_axiu<24, 1, 1, 1> axis_rgb888_t;
typedef ap_uint<10> pixel_u10_t;
typedef ap_uint<8>  pixel_u8_t;

// Khai báo nguyên mẫu hàm Top-Level
void isp_core(
    hls::stream<axis_raw10_t>&  s_axis_video,
    hls::stream<axis_rgb888_t>& m_axis_video,
    ap_uint<12> width,
    ap_uint<12> height,
    ap_uint<10> blc_offset,
    ap_uint<10> dpc_thresh,
    ap_uint<2>  bayer_phase
);

#endif // _ISP_CORE_H_