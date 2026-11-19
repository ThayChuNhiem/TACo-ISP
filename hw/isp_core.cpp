#include "isp_core.h"

// Hàm kẹp giá trị bảo vệ tràn số
static inline pixel_u10_t clamp_u10(int val) {
    #pragma HLS INLINE
    if (val < 0) return 0;
    if (val > 1023) return 1023;
    return (pixel_u10_t)val;
}

static inline pixel_u8_t clamp_u8_from_u10(int val) {
    #pragma HLS INLINE
    int v8 = (val + 2) >> 2; 
    if (v8 < 0) return 0;
    if (v8 > 255) return 255;
    return (pixel_u8_t)v8;
}

// Phản xạ biên gương
static inline int reflect_idx(int idx, int limit) {
    #pragma HLS INLINE
    if (idx < 0) return -idx;
    if (idx >= limit) return 2 * limit - 2 - idx;
    return idx;
}

// STAGE 1: BLC + DPC/NR
void stage_blc_dpc_nr_5x5(
    hls::stream<axis_raw10_t>& s_axis_raw,
    hls::stream<pixel_u10_t>&  s_clean_bayer,
    ap_uint<12> width,
    ap_uint<12> height,
    ap_uint<10> blc_offset,
    ap_uint<10> dpc_thresh
) {
    pixel_u10_t linebuf[4][MAX_WIDTH];
    #pragma HLS ARRAY_PARTITION variable=linebuf complete dim=1
    #pragma HLS BIND_STORAGE variable=linebuf type=ram_2p impl=bram

    pixel_u10_t win[5][5];
    #pragma HLS ARRAY_PARTITION variable=win complete dim=0

    ROW_LOOP: for (int y = 0; y < height + 2; y++) {
        COL_LOOP: for (int x = 0; x < width + 2; x++) {
            #pragma HLS PIPELINE II=1

            pixel_u10_t in_val = 0;
            if (y < height && x < width) {
                axis_raw10_t pkt = s_axis_raw.read();
                int sub_blc = (int)(pkt.data & 0x3FF) - (int)blc_offset;
                in_val = clamp_u10(sub_blc);
            }

            for (int r = 0; r < 5; r++) {
                for (int c = 0; c < 4; c++) {
                    win[r][c] = win[r][c + 1];
                }
            }

            int rx_in = reflect_idx(x, width);
            if (y < height) {
                win[0][4] = linebuf[0][rx_in];
                win[1][4] = linebuf[1][rx_in];
                win[2][4] = linebuf[2][rx_in];
                win[3][4] = linebuf[3][rx_in];
                win[4][4] = in_val;

                if (x < width) {
                    linebuf[0][x] = linebuf[1][x];
                    linebuf[1][x] = linebuf[2][x];
                    linebuf[2][x] = linebuf[3][x];
                    linebuf[3][x] = in_val;
                }
            } else {
                win[0][4] = linebuf[0][rx_in];
                win[1][4] = linebuf[1][rx_in];
                win[2][4] = linebuf[2][rx_in];
                win[3][4] = linebuf[3][rx_in];
                win[4][4] = (y == height) ? linebuf[2][rx_in] : linebuf[1][rx_in];
            }

            if (y >= 2 && x >= 2) {
                pixel_u10_t center = win[2][2];

                pixel_u10_t nb[8];
                #pragma HLS ARRAY_PARTITION variable=nb complete
                nb[0] = (y == 2) ? win[4][0] : win[0][0];
                nb[1] = (y == 2) ? win[4][2] : win[0][2];
                nb[2] = (y == 2) ? win[4][4] : win[0][4];
                nb[3] = (x == 2) ? win[2][4] : win[2][0];
                nb[4] = win[2][4];
                nb[5] = win[4][0];
                nb[6] = win[4][2];
                nb[7] = win[4][4];

                pixel_u10_t p_max = 0;
                pixel_u10_t p_min = 1023;
                int sum_nb = 0;

                for (int i = 0; i < 8; i++) {
                    #pragma HLS UNROLL
                    if (nb[i] > p_max) p_max = nb[i];
                    if (nb[i] < p_min) p_min = nb[i];
                    sum_nb += nb[i];
                }

                int avg_nb = (sum_nb + 4) >> 3;
                pixel_u10_t out_pix;

                if (center > clamp_u10((int)p_max + (int)dpc_thresh) ||
                    center < clamp_u10((int)p_min - (int)dpc_thresh)) {
                    out_pix = (pixel_u10_t)avg_nb;
                } else {
                    out_pix = (pixel_u10_t)((3 * (int)center + avg_nb + 2) >> 2);
                }

                s_clean_bayer.write(out_pix);
            }
        }
    }
}

// STAGE 2: DEMOSAIC MALVAR-HE-CUTLER 5x5
void stage_demosaic_malvar_5x5(
    hls::stream<pixel_u10_t>&  s_clean_bayer,
    hls::stream<axis_rgb888_t>& m_axis_rgb,
    ap_uint<12> width,
    ap_uint<12> height,
    ap_uint<2>  bayer_phase
) {
    pixel_u10_t linebuf[4][MAX_WIDTH];
    #pragma HLS ARRAY_PARTITION variable=linebuf complete dim=1
    #pragma HLS BIND_STORAGE variable=linebuf type=ram_2p impl=bram

    pixel_u10_t w[5][5];
    #pragma HLS ARRAY_PARTITION variable=w complete dim=0

    ROW_DEM: for (int y = 0; y < height + 2; y++) {
        COL_DEM: for (int x = 0; x < width + 2; x++) {
            #pragma HLS PIPELINE II=1

            pixel_u10_t in_val = 0;
            if (y < height && x < width) {
                in_val = s_clean_bayer.read();
            }

            for (int r = 0; r < 5; r++) {
                for (int c = 0; c < 4; c++) {
                    w[r][c] = w[r][c + 1];
                }
            }

            int rx_in = reflect_idx(x, width);
            if (y < height) {
                w[0][4] = linebuf[0][rx_in];
                w[1][4] = linebuf[1][rx_in];
                w[2][4] = linebuf[2][rx_in];
                w[3][4] = linebuf[3][rx_in];
                w[4][4] = in_val;

                if (x < width) {
                    linebuf[0][x] = linebuf[1][x];
                    linebuf[1][x] = linebuf[2][x];
                    linebuf[2][x] = linebuf[3][x];
                    linebuf[3][x] = in_val;
                }
            } else {
                w[0][4] = linebuf[0][rx_in];
                w[1][4] = linebuf[1][rx_in];
                w[2][4] = linebuf[2][rx_in];
                w[3][4] = linebuf[3][rx_in];
                w[4][4] = (y == height) ? linebuf[2][rx_in] : linebuf[1][rx_in];
            }

            if (y >= 2 && x >= 2) {
                int out_y = y - 2;
                int out_x = x - 2;

                int p02 = (out_y == 0) ? (int)w[4][2] : (int)w[0][2];
                int p42 = (int)w[4][2];
                int p20 = (out_x == 0) ? (int)w[2][4] : (int)w[2][0];
                int p24 = (int)w[2][4];

                int p11 = (out_y == 0) ? (int)w[3][1] : (int)w[1][1];
                int p13 = (out_y == 0) ? (int)w[3][3] : (int)w[1][3];
                int p31 = (int)w[3][1];
                int p33 = (int)w[3][3];

                int p12 = (out_y == 0) ? (int)w[3][2] : (int)w[1][2];
                int p32 = (int)w[3][2];
                int p21 = (out_x == 0) ? (int)w[2][3] : (int)w[2][1];
                int p23 = (int)w[2][3];
                int p22 = (int)w[2][2];

                int G_at_RB = (4 * p22 + 2 * (p12 + p32 + p21 + p23) - (p02 + p42 + p20 + p24) + 4) >> 3;
                int RB_at_G_h = (5 * p22 + 4 * (p21 + p23) - (p20 + p24 + p11 + p13 + p31 + p33) + ((p02 + p42) >> 1) + 4) >> 3;
                int RB_at_G_v = (5 * p22 + 4 * (p12 + p32) - (p02 + p42 + p11 + p13 + p31 + p33) + ((p20 + p24) >> 1) + 4) >> 3;
                int RB_at_BR = (6 * p22 + 2 * (p11 + p13 + p31 + p33) - ((3 * (p02 + p42 + p20 + p24)) >> 1) + 4) >> 3;

                ap_uint<2> pos = (((ap_uint<1>)(out_y & 1), (ap_uint<1>)(out_x & 1))) ^ bayer_phase;
                int R, G, B;

                if (pos == 0) {        
                    R = p22; G = G_at_RB; B = RB_at_BR;
                } else if (pos == 1) { 
                    R = RB_at_G_h; G = p22; B = RB_at_G_v;
                } else if (pos == 2) { 
                    R = RB_at_G_v; G = p22; B = RB_at_G_h;
                } else {               
                    R = RB_at_BR; G = G_at_RB; B = p22;
                }

                axis_rgb888_t out_pkt;
                pixel_u8_t r8 = clamp_u8_from_u10(R);
                pixel_u8_t g8 = clamp_u8_from_u10(G);
                pixel_u8_t b8 = clamp_u8_from_u10(B);

                out_pkt.data = ((ap_uint<24>)r8 << 16) | ((ap_uint<24>)g8 << 8) | (ap_uint<24>)b8;
                out_pkt.keep = 0x7;
                out_pkt.strb = 0x7;
                out_pkt.user = (out_y == 0 && out_x == 0) ? 1 : 0;
                out_pkt.last = (out_x == width - 1) ? 1 : 0;
                out_pkt.id   = 0;
                out_pkt.dest = 0;

                m_axis_rgb.write(out_pkt);
            }
        }
    }
}

// TOP-LEVEL MODULE
void isp_core(
    hls::stream<axis_raw10_t>&  s_axis_video,
    hls::stream<axis_rgb888_t>& m_axis_video,
    ap_uint<12> width,
    ap_uint<12> height,
    ap_uint<10> blc_offset,
    ap_uint<10> dpc_thresh,
    ap_uint<2>  bayer_phase
) {
    #pragma HLS INTERFACE axis port=s_axis_video
    #pragma HLS INTERFACE axis port=m_axis_video
    #pragma HLS INTERFACE s_axilite port=width       bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=height      bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=blc_offset  bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=dpc_thresh  bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=bayer_phase bundle=CTRL
    #pragma HLS INTERFACE s_axilite port=return      bundle=CTRL

    hls::stream<pixel_u10_t> s_clean_bayer("s_clean_bayer");
    #pragma HLS STREAM variable=s_clean_bayer depth=64

    #pragma HLS DATAFLOW
    stage_blc_dpc_nr_5x5(s_axis_video, s_clean_bayer, width, height, blc_offset, dpc_thresh);
    stage_demosaic_malvar_5x5(s_clean_bayer, m_axis_video, width, height, bayer_phase);
}