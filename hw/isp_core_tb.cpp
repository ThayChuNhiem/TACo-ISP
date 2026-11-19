#include <iostream>
#include <cassert>
#include "isp_core.h"

int main() {
    const int W = 16;
    const int H = 16;
    const int BLC = 64;     
    const int THRESH = 100; 

    hls::stream<axis_raw10_t>  src_stream;
    hls::stream<axis_rgb888_t> dst_stream;

    for (int y = 0; y < H; y++) {
        for (int x = 0; x < W; x++) {
            axis_raw10_t pkt;
            int val = 0;
            if ((y % 2 == 0) && (x % 2 == 0))      val = 464; 
            else if ((y % 2 == 1) && (x % 2 == 1)) val = 164; 
            else                                   val = 264; 

            if (y == 4 && x == 4) val = 1023; 

            pkt.data = val;
            pkt.keep = 0x3;
            pkt.strb = 0x3;
            pkt.user = (y == 0 && x == 0) ? 1 : 0;
            pkt.last = (x == W - 1) ? 1 : 0;
            src_stream.write(pkt);
        }
    }

    isp_core(src_stream, dst_stream, W, H, BLC, THRESH, 0);

    int count = 0;
    for (int y = 0; y < H; y++) {
        for (int x = 0; x < W; x++) {
            assert(!dst_stream.empty());
            axis_rgb888_t out = dst_stream.read();
            int r = (out.data >> 16) & 0xFF;
            int g = (out.data >> 8)  & 0xFF;
            int b = out.data & 0xFF;

            if (y == 0 && x == 0) assert(out.user == 1);
            if (x == W - 1)       assert(out.last == 1);

            if (y == 4 && x == 4) {
                std::cout << "[Pixel (4,4) sau DPC + Malvar 5x5] R=" << r
                          << ", G=" << g << ", B=" << b << std::endl;
                assert(r >= 95 && r <= 105);
                assert(g >= 45 && g <= 55);
                assert(b >= 20 && b <= 30);
            }
            count++;
        }
    }

    std::cout << "=== TESTBENCH PASS! Tong so pixel xu ly: " << count << " ===" << std::endl;
    return 0;
}