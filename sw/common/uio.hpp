#pragma once
/**
 * ============================================================================
 * TACo-ISP — Userspace I/O (UIO) & Hardware Timing Abstraction (C++17)
 * ============================================================================
 */

#include <cstdint>
#include <string>
#include <chrono>
#include <fstream>
#include <iostream>

namespace taco {

class HwClock {
public:
    static uint64_t now_ns() {
        auto now = std::chrono::steady_clock::now();
        return std::chrono::duration_cast<std::chrono::nanoseconds>(now.time_since_epoch()).count();
    }
};

class Gpio {
public:
    explicit Gpio(int pin = 338) : pin_(pin) {}

    bool export_pin() {
        std::ofstream f("/sys/class/gpio/export");
        if (f) {
            f << pin_;
            return true;
        }
        return false;
    }

    bool set_direction(bool out = true) {
        std::ofstream f("/sys/class/gpio/gpio" + std::to_string(pin_) + "/direction");
        if (f) {
            f << (out ? "out" : "in");
            return true;
        }
        return false;
    }

    bool write(int val) {
        std::ofstream f("/sys/class/gpio/gpio" + std::to_string(pin_) + "/value");
        if (f) {
            f << (val ? "1" : "0");
            return true;
        }
        return false;
    }

private:
    int pin_;
};

class UioDevice {
public:
    UioDevice() = default;
    ~UioDevice() = default;
};

} // namespace taco
