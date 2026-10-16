#pragma once
/**
 * ============================================================================
 * TACo-ISP — HLS Kernel Register Offsets & Constants
 * ============================================================================
 */

#include <cstdint>

namespace taco {
namespace hw {

// AXI4-Lite Control Registers for isp_top
constexpr uint32_t ISP_CTRL_ADDR_AP_CTRL     = 0x00;
constexpr uint32_t ISP_CTRL_ADDR_GIE         = 0x04;
constexpr uint32_t ISP_CTRL_ADDR_IER         = 0x08;
constexpr uint32_t ISP_CTRL_ADDR_ISR         = 0x0c;
constexpr uint32_t ISP_CTRL_ADDR_BLC_R       = 0x10;
constexpr uint32_t ISP_CTRL_ADDR_BLC_GR      = 0x14;
constexpr uint32_t ISP_CTRL_ADDR_BLC_GB      = 0x18;
constexpr uint32_t ISP_CTRL_ADDR_BLC_B       = 0x1c;
constexpr uint32_t ISP_CTRL_ADDR_NR_SIGMA    = 0x20;
constexpr uint32_t ISP_CTRL_ADDR_WB_GAIN_R   = 0x24;
constexpr uint32_t ISP_CTRL_ADDR_WB_GAIN_B   = 0x28;

// AXI4-Lite Control Registers for s2t_top
constexpr uint32_t S2T_CTRL_ADDR_AP_CTRL     = 0x00;
constexpr uint32_t S2T_CTRL_ADDR_DST_PHY     = 0x10;
constexpr uint32_t S2T_CTRL_ADDR_SCALE       = 0x18;

} // namespace hw
} // namespace taco
