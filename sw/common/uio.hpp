#pragma once
/**
 * ============================================================================
 * TACo-ISP — Userspace I/O (UIO) & Hardware Timing Abstraction (C++17)
 * ============================================================================
 * Hardware Targets on AMD Kria KV260:
 *   1. UioDevice: Memory-mapped userspace access to AXI4-Lite registers & IRQ
 *   2. HwClock: 64-bit Cascade AXI Timer (LogiCORE IP AXI Timer v2.0)
 *      - Anti-rollover 64-bit atomic counter read
 *      - Configurable clock frequency (default 100 MHz, supports 200 MHz)
 *      - TCSR0 / TCSR1 cascade initialization
 *      - Fallback to std::chrono when hardware UIO is not present
 *   3. Gpio: Memory-mapped AXI GPIO / Sysfs GPIO with Cortex-A53 memory barrier
 * ============================================================================
 */

#include <cstdint>
#include <string>
#include <chrono>
#include <fstream>
#include <iostream>
#include <vector>
#include <memory>
#include <cstring>
#include <atomic>
#include <sstream>

#if defined(__linux__) || defined(__unix__)
#include <sys/mman.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <poll.h>
#endif

namespace taco {

// ============================================================================
// Memory Barrier Helper (Critical for ARM Cortex-A53 Weak Memory Model)
// ============================================================================
inline void memory_barrier() {
#if defined(__aarch64__) || defined(__arm__)
    asm volatile("dmb sy" ::: "memory");
#elif defined(__x86_64__) || defined(_M_X64)
    asm volatile("" ::: "memory");
    std::atomic_thread_fence(std::memory_order_seq_cst);
#else
    std::atomic_thread_fence(std::memory_order_seq_cst);
#endif
}

// ============================================================================
// UioDevice: Userspace I/O driver abstraction
// ============================================================================
class UioDevice {
public:
    UioDevice() = default;

    explicit UioDevice(int uio_index, size_t map_size = 0x10000) {
        open_device(uio_index, map_size);
    }

    explicit UioDevice(const std::string& dev_path, size_t map_size = 0x10000) {
        open_path(dev_path, map_size);
    }

    ~UioDevice() {
        close_device();
    }

    // Non-copyable
    UioDevice(const UioDevice&) = delete;
    UioDevice& operator=(const UioDevice&) = delete;

    // Moveable
    UioDevice(UioDevice&& other) noexcept {
        move_from(std::move(other));
    }

    UioDevice& operator=(UioDevice&& other) noexcept {
        if (this != &other) {
            close_device();
            move_from(std::move(other));
        }
        return *this;
    }

    bool open_device(int uio_index, size_t map_size = 0x10000) {
        std::string path = "/dev/uio" + std::to_string(uio_index);
        return open_path(path, map_size);
    }

    bool open_path(const std::string& dev_path, size_t map_size = 0x10000) {
        close_device();
        dev_path_ = dev_path;
        map_size_ = map_size;

#if defined(__linux__) || defined(__unix__)
        fd_ = ::open(dev_path.c_str(), O_RDWR | O_SYNC);
        if (fd_ >= 0) {
            void* ptr = ::mmap(nullptr, map_size_, PROT_READ | PROT_WRITE, MAP_SHARED, fd_, 0);
            if (ptr != MAP_FAILED) {
                map_ptr_ = static_cast<volatile uint32_t*>(ptr);
                is_mock_ = false;
                return true;
            }
            ::close(fd_);
            fd_ = -1;
        }
#endif

        // If physical UIO device is not accessible, enable mock mode for host verification
        mock_storage_.assign(map_size_ / sizeof(uint32_t), 0);
        map_ptr_ = reinterpret_cast<volatile uint32_t*>(mock_storage_.data());
        is_mock_ = true;
        return true;
    }

    void close_device() {
#if defined(__linux__) || defined(__unix__)
        if (!is_mock_ && map_ptr_ != nullptr) {
            ::munmap(const_cast<uint32_t*>(map_ptr_), map_size_);
        }
        if (fd_ >= 0) {
            ::close(fd_);
            fd_ = -1;
        }
#endif
        map_ptr_ = nullptr;
        map_size_ = 0;
        mock_storage_.clear();
        is_mock_ = false;
    }

    bool is_valid() const {
        return map_ptr_ != nullptr;
    }

    bool is_mock() const {
        return is_mock_;
    }

    bool has_hardware() const noexcept {
        return (map_ptr_ != nullptr && !is_mock_);
    }

    const std::string& path() const {
        return dev_path_;
    }

    uint32_t read32(size_t offset_bytes) const {
        if (!map_ptr_) return 0;
        size_t idx = offset_bytes / sizeof(uint32_t);
        if (idx >= map_size_ / sizeof(uint32_t)) return 0;
        memory_barrier();
        uint32_t val = map_ptr_[idx];
        memory_barrier();
        return val;
    }

    void write32(size_t offset_bytes, uint32_t val) {
        if (!map_ptr_) return;
        size_t idx = offset_bytes / sizeof(uint32_t);
        if (idx >= map_size_ / sizeof(uint32_t)) return;
        memory_barrier();
        map_ptr_[idx] = val;
        memory_barrier();
    }

    bool wait_irq(int timeout_ms = -1) {
#if defined(__linux__) || defined(__unix__)
        if (!is_mock_ && fd_ >= 0) {
            if (timeout_ms >= 0) {
                struct pollfd pfd;
                pfd.fd = fd_;
                pfd.events = POLLIN;
                int ret = ::poll(&pfd, 1, timeout_ms);
                if (ret <= 0) return false;
            }
            uint32_t count = 0;
            ssize_t s = ::read(fd_, &count, sizeof(count));
            return (s == sizeof(count));
        }
#endif
        // In mock mode or non-linux, simulate success
        (void)timeout_ms;
        return true;
    }

    void enable_irq() {
#if defined(__linux__) || defined(__unix__)
        if (!is_mock_ && fd_ >= 0) {
            uint32_t reenable = 1;
            (void)::write(fd_, &reenable, sizeof(reenable));
        }
#endif
    }

private:
    void move_from(UioDevice&& other) noexcept {
        fd_ = other.fd_;
        map_ptr_ = other.map_ptr_;
        map_size_ = other.map_size_;
        dev_path_ = std::move(other.dev_path_);
        is_mock_ = other.is_mock_;
        mock_storage_ = std::move(other.mock_storage_);

        other.fd_ = -1;
        other.map_ptr_ = nullptr;
        other.map_size_ = 0;
        other.is_mock_ = false;
    }

    int fd_ = -1;
    volatile uint32_t* map_ptr_ = nullptr;
    size_t map_size_ = 0;
    std::string dev_path_;
    bool is_mock_ = false;
    std::vector<uint32_t> mock_storage_;
};

// ============================================================================
// HwClock: 64-bit Cascade AXI Timer (LogiCORE IP AXI Timer v2.0)
// ============================================================================
class HwClock {
public:
    // LogiCORE IP AXI Timer Register Offsets
    static constexpr size_t REG_TCSR0 = 0x00; // Timer 0 Control / Status
    static constexpr size_t REG_TLR0  = 0x04; // Timer 0 Load Register
    static constexpr size_t REG_TCR0  = 0x08; // Timer 0 Counter (bits 0..31)
    static constexpr size_t REG_TCSR1 = 0x10; // Timer 1 Control / Status
    static constexpr size_t REG_TLR1  = 0x14; // Timer 1 Load Register
    static constexpr size_t REG_TCR1  = 0x18; // Timer 1 Counter (bits 32..63 in cascade mode)

    // TCSR Bit Definitions
    static constexpr uint32_t TCSR_CASC = (1U << 11); // Cascade Mode (Timer0 + Timer1 = 64-bit)
    static constexpr uint32_t TCSR_ENT  = (1U << 8);  // Enable Timer
    static constexpr uint32_t TCSR_UDT  = (1U << 7);  // Up/Down Count (0 = Count Up)
    static constexpr uint32_t TCSR_ARHT = (1U << 5);  // Auto Reload / Hold (1 = Auto Reload)
    static constexpr uint32_t TCSR_LOAD = (1U << 4);  // Load Counter from TLR

    static constexpr uint64_t DEFAULT_FREQ_HZ = 100'000'000ULL; // 100 MHz (10 ns / tick)
    static constexpr uint64_t FREQ_200MHZ     = 200'000'000ULL; // 200 MHz (5 ns / tick)

    explicit HwClock(uint64_t freq_hz = DEFAULT_FREQ_HZ)
        : freq_hz_(freq_hz > 0 ? freq_hz : DEFAULT_FREQ_HZ) {}

    HwClock(UioDevice* dev, uint64_t freq_hz = DEFAULT_FREQ_HZ)
        : uio_dev_(dev), freq_hz_(freq_hz > 0 ? freq_hz : DEFAULT_FREQ_HZ) {
        if (uio_dev_ && uio_dev_->has_hardware()) {
            init_cascade();
        }
    }

    void attach_uio(UioDevice* dev) {
        uio_dev_ = dev;
        if (uio_dev_ && uio_dev_->has_hardware()) {
            init_cascade();
        }
    }

    void set_frequency(uint64_t freq_hz) {
        if (freq_hz > 0) {
            freq_hz_ = freq_hz;
        }
    }

    uint64_t frequency() const {
        return freq_hz_;
    }

    bool has_hardware() const noexcept {
        return (uio_dev_ != nullptr && uio_dev_->has_hardware());
    }

    /**
     * Initialize TCSR0 / TCSR1 in 64-bit Cascade Up-Counter Auto-Reload Mode.
     */
    void init_cascade() {
        if (!uio_dev_ || !uio_dev_->is_valid()) return;

        // 1. Stop both timers
        uio_dev_->write32(REG_TCSR0, 0);
        uio_dev_->write32(REG_TCSR1, 0);

        // 2. Clear load registers
        uio_dev_->write32(REG_TLR0, 0);
        uio_dev_->write32(REG_TLR1, 0);

        // 3. Load 0 into counters
        uio_dev_->write32(REG_TCSR0, TCSR_LOAD);
        uio_dev_->write32(REG_TCSR1, TCSR_LOAD);

        // 4. Release load bit
        uio_dev_->write32(REG_TCSR0, 0);
        uio_dev_->write32(REG_TCSR1, 0);

        // 5. Start Timer 1 (high 32 bits) in auto-reload mode
        uio_dev_->write32(REG_TCSR1, TCSR_ENT | TCSR_ARHT);

        // 6. Start Timer 0 (low 32 bits) with CASC enabled (cascades carry into Timer 1)
        uio_dev_->write32(REG_TCSR0, TCSR_CASC | TCSR_ENT | TCSR_ARHT);
    }

    /**
     * 64-bit Cascade Anti-Rollover Counter Read:
     * When reading cascaded TCR0 (low) and TCR1 (high), read high -> low -> high.
     * If high changed during read (counter rollover happened), repeat to prevent race condition.
     */
    uint64_t now_ticks() const {
        if (has_hardware()) {
            uint32_t hi1, lo, hi2;
            do {
                hi1 = uio_dev_->read32(REG_TCR1);
                lo  = uio_dev_->read32(REG_TCR0);
                hi2 = uio_dev_->read32(REG_TCR1);
            } while (hi1 != hi2);
            return (static_cast<uint64_t>(hi1) << 32) | lo;
        }

        // If mock UIO device was explicitly written (e.g. for unit testing mock registers)
        if (uio_dev_ && uio_dev_->is_mock()) {
            uint32_t hi = uio_dev_->read32(REG_TCR1);
            uint32_t lo = uio_dev_->read32(REG_TCR0);
            if (hi != 0 || lo != 0) {
                return (static_cast<uint64_t>(hi) << 32) | lo;
            }
        }

        // Fallback: std::chrono steady_clock
        auto now = std::chrono::steady_clock::now();
        auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(now.time_since_epoch()).count();
        return ns_to_ticks(static_cast<uint64_t>(ns));
    }

    uint64_t now_ns() const {
        if (has_hardware()) {
            return ticks_to_ns(now_ticks());
        }

        if (uio_dev_ && uio_dev_->is_mock()) {
            uint32_t hi = uio_dev_->read32(REG_TCR1);
            uint32_t lo = uio_dev_->read32(REG_TCR0);
            if (hi != 0 || lo != 0) {
                return ticks_to_ns((static_cast<uint64_t>(hi) << 32) | lo);
            }
        }

        auto now = std::chrono::steady_clock::now();
        return static_cast<uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(now.time_since_epoch()).count());
    }

    uint64_t ticks_to_ns(uint64_t ticks) const {
#if defined(__SIZEOF_INT128__)
        return static_cast<uint64_t>(
            (static_cast<unsigned __int128>(ticks) * 1'000'000'000ULL) / freq_hz_);
#else
        return static_cast<uint64_t>(
            static_cast<double>(ticks) * 1e9 / static_cast<double>(freq_hz_));
#endif
    }

    uint64_t ns_to_ticks(uint64_t ns) const {
#if defined(__SIZEOF_INT128__)
        return static_cast<uint64_t>(
            (static_cast<unsigned __int128>(ns) * freq_hz_) / 1'000'000'000ULL);
#else
        return static_cast<uint64_t>(
            static_cast<double>(ns) * static_cast<double>(freq_hz_) / 1e9);
#endif
    }

    double ticks_to_ms(uint64_t ticks) const {
        return static_cast<double>(ticks) * 1000.0 / static_cast<double>(freq_hz_);
    }

    // Static helper for universal timestamping fallback
    static uint64_t get_now_ns() {
        auto now = std::chrono::steady_clock::now();
        return static_cast<uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(now.time_since_epoch()).count());
    }

private:
    UioDevice* uio_dev_ = nullptr;
    uint64_t freq_hz_ = DEFAULT_FREQ_HZ;
};

// ============================================================================
// Gpio: Pin abstraction with Cortex-A53 Memory Barrier
// ============================================================================
class Gpio {
public:
    static constexpr size_t AXI_GPIO_DATA = 0x00; // Channel 1 Data Register
    static constexpr size_t AXI_GPIO_TRI  = 0x04; // Channel 1 3-State Register (0 = Output)

    explicit Gpio(int pin = 338, UioDevice* axi_uio = nullptr, int bit_index = 0)
        : pin_(pin), axi_uio_(axi_uio), bit_index_(bit_index) {
        if (axi_uio_ && axi_uio_->is_valid()) {
            // Configure AXI GPIO as output (tri-state = 0)
            uint32_t tri = axi_uio_->read32(AXI_GPIO_TRI);
            tri &= ~(1U << bit_index_);
            axi_uio_->write32(AXI_GPIO_TRI, tri);
        }
    }

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
        memory_barrier();

        bool success = false;
        if (axi_uio_ && axi_uio_->is_valid()) {
            uint32_t cur = axi_uio_->read32(AXI_GPIO_DATA);
            if (val) {
                cur |= (1U << bit_index_);
            } else {
                cur &= ~(1U << bit_index_);
            }
            axi_uio_->write32(AXI_GPIO_DATA, cur);
            success = true;
        } else {
            std::ofstream f("/sys/class/gpio/gpio" + std::to_string(pin_) + "/value");
            if (f) {
                f << (val ? "1" : "0");
                success = true;
            }
        }

        memory_barrier();
        return success;
    }

    void set() {
        write(1);
    }

    void clear() {
        write(0);
    }

    int pin() const {
        return pin_;
    }

private:
    int pin_;
    UioDevice* axi_uio_ = nullptr;
    int bit_index_ = 0;
};

} // namespace taco
