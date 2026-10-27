#include "uio.hpp"
#include <cassert>
#include <iostream>

int main() {
    taco::UioDevice dev("/dev/uio0");
    assert(dev.is_valid());
    assert(dev.is_mock());

    // Test write and read
    dev.write32(0x08, 0x12345678);
    assert(dev.read32(0x08) == 0x12345678);
    assert(!dev.has_hardware()); // Mock device has no physical hardware

    // Test HwClock fallback with mock device (registers are 0)
    taco::UioDevice mock_empty("/dev/uio99");
    taco::HwClock clock_mock(&mock_empty, 100000000ULL);
    assert(!clock_mock.has_hardware());
    uint64_t fallback_ns1 = clock_mock.now_ns();
    assert(fallback_ns1 > 0); // Must NOT be 0! Must fallback to steady_clock
    uint64_t fallback_ns2 = clock_mock.now_ns();
    assert(fallback_ns2 >= fallback_ns1);

    // Test HwClock
    taco::HwClock clock(&dev, 100000000ULL);
    assert(clock.frequency() == 100000000ULL);
    assert(clock.ticks_to_ns(100) == 1000); // 100 ticks @ 100MHz = 1000ns

    // Test 200MHz frequency configuration
    clock.set_frequency(200000000ULL);
    assert(clock.frequency() == 200000000ULL);
    assert(clock.ticks_to_ns(100) == 500); // 100 ticks @ 200MHz = 500ns

    // Revert to 100MHz
    clock.set_frequency(100000000ULL);

    // Test 64-bit anti-rollover read
    dev.write32(taco::HwClock::REG_TCR0, 0xDEADBEEF);
    dev.write32(taco::HwClock::REG_TCR1, 0x00000001);
    uint64_t ticks = clock.now_ticks();
    assert(ticks == 0x00000001DEADBEEFULL);

    // Test Gpio
    taco::Gpio gpio(338, &dev, 0);
    gpio.set();
    assert((dev.read32(taco::Gpio::AXI_GPIO_DATA) & 1) == 1);
    gpio.clear();
    assert((dev.read32(taco::Gpio::AXI_GPIO_DATA) & 1) == 0);

    // Test fallback clock
    taco::HwClock fallback_clock(100000000ULL);
    uint64_t ns1 = fallback_clock.now_ns();
    uint64_t ns2 = taco::HwClock::get_now_ns();
    assert(ns1 > 0);
    assert(ns2 >= ns1);

    std::cout << "[✓] All C++ UIO / HwClock / Gpio assertions passed!" << std::endl;
    return 0;
}
