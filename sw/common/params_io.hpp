#pragma once
/**
 * ============================================================================
 * TACo-ISP — Register Parameters File I/O
 * ============================================================================
 */

#include <string>
#include <vector>
#include <fstream>
#include <sstream>
#include <cstdint>
#include <iostream>

namespace taco {

struct RegEntry {
    uint32_t addr;
    uint32_t value;
};

inline std::vector<RegEntry> load_register_file(const std::string& path) {
    std::vector<RegEntry> entries;
    std::ifstream file(path);
    if (!file.is_open()) {
        std::cerr << "[!] Cannot open register file: " << path << "\n";
        return entries;
    }
    std::string line;
    while (std::getline(file, line)) {
        if (line.empty() || line[0] == '#' || line[0] == '/') continue;
        std::istringstream iss(line);
        std::string s_addr, s_val;
        if (iss >> s_addr >> s_val) {
            uint32_t addr = std::stoul(s_addr, nullptr, 0);
            uint32_t val = std::stoul(s_val, nullptr, 0);
            entries.push_back({addr, val});
        }
    }
    return entries;
}

} // namespace taco
