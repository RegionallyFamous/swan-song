// SPDX-License-Identifier: GPL-2.0-only
#include <verilated.h>
#include <verilated_vcd_c.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <memory>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

#include "VSwanTop.h"
#include "trace_logger.hpp"

namespace fs = std::filesystem;

static std::vector<uint8_t> read_file(const fs::path& path) {
  std::ifstream stream(path, std::ios::binary);
  if (!stream) throw std::runtime_error("cannot open " + path.string());
  return {std::istreambuf_iterator<char>(stream), {}};
}

static void write_rgb(const fs::path& path,
                      const std::array<uint16_t, 224 * 144>& frame) {
  std::ofstream stream(path, std::ios::binary);
  if (!stream) throw std::runtime_error("cannot write " + path.string());
  for (uint16_t pixel : frame) {
    const uint8_t r = static_cast<uint8_t>(((pixel >> 8) & 0xf) * 17);
    const uint8_t g = static_cast<uint8_t>(((pixel >> 4) & 0xf) * 17);
    const uint8_t b = static_cast<uint8_t>((pixel & 0xf) * 17);
    stream.put(static_cast<char>(r));
    stream.put(static_cast<char>(g));
    stream.put(static_cast<char>(b));
  }
}

static void usage(const char* argv0) {
  std::cerr
      << "usage: " << argv0 << " --rom FILE [OPTIONS]\n\n"
      << "Simulation:\n"
      << "  --bios FILE             4 KiB mono or 8 KiB color BIOS\n"
      << "  --frames N              stop after N complete frames (default: 1)\n"
      << "  --out DIR               raw/PNG frame directory\n"
      << "  --max-cycles N          timeout in 36.864 MHz system cycles\n"
      << "  --trace FILE.vcd        whole-design VCD waveform\n\n"
      << "Structured debug trace:\n"
      << "  --event-trace FILE      write CSV, or JSONL for a .jsonl filename\n"
      << "  --trace-events LIST     comma list: cpu,bank,vram (default: all)\n"
      << "  --trace-pc START-END    inclusive 20-bit physical CPU PC filter\n"
      << "  --trace-vram-address R  VRAM ADDR or START-END list (inclusive)\n"
      << "  --trace-vram-role LIST  screen1_map,screen1_tile,screen2_map,\n"
         "                            screen2_tile,sprite_table,sprite_tile\n"
      << "  --trace-format FORMAT   csv or jsonl (overrides filename suffix)\n"
      << "  --trace-config FILE     load KEY=VALUE trace settings; later CLI"
         " options win\n"
      << "  --help                  show this help\n";
}

template <typename Top, typename = void>
struct DebugTapAdapter {
  static constexpr bool available = false;
  void capture(const Top&, swansong::trace::Logger&, uint64_t) {}
};

template <typename Top>
struct DebugTapAdapter<
    Top, std::void_t<decltype(std::declval<Top>().debug_cpu_done),
                     decltype(std::declval<Top>().debug_cpu_cs),
                     decltype(std::declval<Top>().debug_cpu_ip),
                     decltype(std::declval<Top>().debug_cpu_pc),
                     decltype(std::declval<Top>().debug_reg_write),
                     decltype(std::declval<Top>().debug_reg_addr),
                     decltype(std::declval<Top>().debug_reg_data),
                     decltype(std::declval<Top>().debug_gpu_vram_valid),
                     decltype(std::declval<Top>().debug_gpu_vram_addr),
                     decltype(std::declval<Top>().debug_gpu_vram_role)>> {
  static constexpr bool available = true;

  void capture(const Top& top, swansong::trace::Logger& logger, uint64_t cycle) {
    if (top.debug_cpu_done) {
      logger.cpu(cycle, top.debug_cpu_pc, top.debug_cpu_cs, top.debug_cpu_ip);
    }
    const bool repeated_write = previous_reg_write_ &&
                                previous_reg_addr_ == top.debug_reg_addr &&
                                previous_reg_data_ == top.debug_reg_data;
    if (top.debug_reg_write && !repeated_write && top.debug_reg_addr >= 0xc0 &&
        top.debug_reg_addr <= 0xc3) {
      logger.bank(cycle, top.debug_reg_addr, top.debug_reg_data);
    }
    if (top.debug_gpu_vram_valid) {
      logger.vram(cycle, top.debug_gpu_vram_addr,
                  swansong::trace::vram_role_from_code(
                      top.debug_gpu_vram_role));
    }
    previous_reg_write_ = top.debug_reg_write;
    previous_reg_addr_ = top.debug_reg_addr;
    previous_reg_data_ = top.debug_reg_data;
  }

 private:
  bool previous_reg_write_ = false;
  uint8_t previous_reg_addr_ = 0;
  uint8_t previous_reg_data_ = 0;
};

int main(int argc, char** argv) {
  Verilated::commandArgs(argc, argv);
  fs::path rom_path;
  fs::path bios_path;
  fs::path out_dir = "build/sim/frames";
  fs::path trace_path;
  swansong::trace::Config event_trace_config;
  uint64_t max_cycles = 36'864'000;
  unsigned target_frames = 1;

  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    auto value = [&](const char* name) -> std::string {
      if (++i >= argc) throw std::runtime_error(std::string("missing value for ") + name);
      return argv[i];
    };
    if (arg == "--rom") rom_path = value("--rom");
    else if (arg == "--bios") bios_path = value("--bios");
    else if (arg == "--frames") target_frames = std::stoul(value("--frames"));
    else if (arg == "--out") out_dir = value("--out");
    else if (arg == "--trace") trace_path = value("--trace");
    else if (arg == "--event-trace") event_trace_config.output = value("--event-trace");
    else if (arg == "--trace-events") {
      event_trace_config.events = swansong::trace::parse_events(value("--trace-events"));
    } else if (arg == "--trace-pc") {
      event_trace_config.cpu_pc = swansong::trace::parse_pc_range(value("--trace-pc"));
    } else if (arg == "--trace-vram-address") {
      event_trace_config.vram_address =
          swansong::trace::parse_address_ranges(value("--trace-vram-address"));
    } else if (arg == "--trace-vram-role") {
      event_trace_config.vram_roles =
          swansong::trace::parse_vram_roles(value("--trace-vram-role"));
    } else if (arg == "--trace-format") {
      event_trace_config.format = swansong::trace::parse_format(value("--trace-format"));
    } else if (arg == "--trace-config") {
      swansong::trace::parse_config_file(value("--trace-config"), event_trace_config);
    }
    else if (arg == "--max-cycles") max_cycles = std::stoull(value("--max-cycles"));
    else if (arg == "--help") { usage(argv[0]); return 0; }
    else throw std::runtime_error("unknown argument: " + arg);
  }
  if (rom_path.empty()) { usage(argv[0]); return 2; }

  const auto rom = read_file(rom_path);
  if (rom.size() < 16 || rom.size() > (1u << 24)) {
    throw std::runtime_error("ROM size must be between 16 bytes and 16 MiB");
  }
  if ((rom.size() & (rom.size() - 1)) != 0) {
    throw std::runtime_error("ROM size must be a power of two for the hardware address mask");
  }
  const bool color_cartridge = rom[rom.size() - 9] == 1;

  std::vector<uint8_t> bios;
  if (!bios_path.empty()) {
    bios = read_file(bios_path);
    if (bios.size() != 4096 && bios.size() != 8192) {
      throw std::runtime_error("BIOS must be exactly 4096 or 8192 bytes");
    }
  } else {
    // Open simulation bootstrap: enable cartridge visibility via port A0, then
    // jump through the cartridge reset vector at FFFF:0000. This is not a
    // replacement firmware implementation.
    bios.assign(color_cartridge ? 8192 : 4096, 0x90);
    const uint8_t bootstrap[] = {0xb0, 0x01, 0xe6, 0xa0, 0xea,
                                 0x00, 0x00, 0xff, 0xff};
    std::copy(std::begin(bootstrap), std::end(bootstrap), bios.end() - 16);
  }

  auto top = std::make_unique<VSwanTop>();
  using TraceTaps = DebugTapAdapter<VSwanTop>;
  TraceTaps trace_taps;
  if (event_trace_config.enabled() && !TraceTaps::available) {
    throw std::runtime_error(
        "structured trace requested, but this model was built without debug taps");
  }
  std::unique_ptr<swansong::trace::Logger> event_trace;
  if (event_trace_config.enabled()) {
    event_trace = std::make_unique<swansong::trace::Logger>(event_trace_config);
  }
  std::unique_ptr<VerilatedVcdC> trace;
  if (!trace_path.empty()) {
    if (trace_path.has_parent_path()) fs::create_directories(trace_path.parent_path());
    Verilated::traceEverOn(true);
    trace = std::make_unique<VerilatedVcdC>();
    top->trace(trace.get(), 8);
    trace->open(trace_path.string().c_str());
  }

  top->clk = 0;
  top->clk_ram = 0;
  top->reset_in = 1;
  top->pause_in = 0;
  top->EXTRAM_dataread = 0;
  top->eeprom_addr = 0;
  top->eeprom_din = 0;
  top->eeprom_req = 0;
  top->eeprom_rnw = 1;
  top->maskAddr = static_cast<uint32_t>(rom.size() - 1);
  top->romtype = rom[rom.size() - 6];
  top->ramtype = rom[rom.size() - 5];
  top->hasRTC = rom[rom.size() - 3] == 1;
  top->isColor = color_cartridge || bios.size() == 8192;
  top->fastforward = 0;
  top->turbo = 0;
  top->KeyY1 = top->KeyY2 = top->KeyY3 = top->KeyY4 = 0;
  top->KeyX1 = top->KeyX2 = top->KeyX3 = top->KeyX4 = 0;
  top->KeyStart = top->KeyA = top->KeyB = 0;
  top->RTC_timestampNew = 0;
  top->RTC_timestampIn = 0;
  top->RTC_timestampSaved = 0;
  top->RTC_savedtimeIn = 0;
  top->RTC_saveLoaded = 0;
  top->increaseSSHeaderCount = 0;
  top->save_state = top->load_state = 0;
  top->savestate_number = 0;
  top->SAVE_out_Dout = 0;
  top->SAVE_out_done = 0;
  top->rewind_on = top->rewind_active = 0;

  std::vector<uint8_t> sram(1u << 20, 0);
  uint64_t ticks = 0;
  uint64_t trace_cycle = 0;
  bool trace_capture_active = false;
  auto eval = [&] {
    top->eval();
    const uint32_t raw_address = top->EXTRAM_addr & 0x01ff'ffffu;
    if (raw_address & 0x0100'0000u) {
      // The Pocket wrapper drops EXTRAM_addr bit 0 when addressing its 16-bit
      // SDRAM. Model the same aligned word; memorymux supplies byte enables
      // and selects the requested byte for odd CPU addresses.
      const size_t address = ((raw_address & 0x00ff'ffffu) & ~1u) % sram.size();
      if (top->EXTRAM_write) {
        if (top->EXTRAM_be & 0x1) sram[address] = top->EXTRAM_datawrite & 0xff;
        if (top->EXTRAM_be & 0x2) sram[(address + 1) % sram.size()] = top->EXTRAM_datawrite >> 8;
      }
      top->EXTRAM_dataread = static_cast<uint16_t>(
          sram[address] | (sram[(address + 1) % sram.size()] << 8));
    } else {
      const uint32_t address = (raw_address & 0x00ff'ffffu) & ~1u;
      const uint32_t a = address & static_cast<uint32_t>(rom.size() - 1);
      const uint8_t lo = rom[a % rom.size()];
      const uint8_t hi = rom[(a + 1) % rom.size()];
      top->EXTRAM_dataread = static_cast<uint16_t>(lo | (hi << 8));
    }
    top->eval();
    if (trace) trace->dump(ticks);
    ++ticks;
  };
  auto cycle = [&] {
    // The production clocks are 36.864 and 110.592 MHz (exactly 1:3).
    for (int phase = 0; phase < 6; ++phase) {
      top->clk_ram = phase & 1;
      if (phase == 0) top->clk = 1;
      if (phase == 3) top->clk = 0;
      eval();
      if (trace_capture_active && event_trace) {
        if (phase == 0) trace_taps.capture(*top, *event_trace, trace_cycle);
      }
    }
    if (trace_capture_active) ++trace_cycle;
  };

  // Program the inferred BIOS RAM while reset is asserted.
  for (size_t byte = 0; byte < bios.size(); byte += 2) {
    top->bios_wraddr = static_cast<uint16_t>(byte);
    top->bios_wrdata = static_cast<uint16_t>(bios[byte] | (bios[byte + 1] << 8));
    top->bios_wr = bios.size() == 4096;
    top->bios_wrcolor = bios.size() == 8192;
    cycle();
  }
  top->bios_wr = top->bios_wrcolor = 0;
  for (int i = 0; i < 16; ++i) cycle();
  top->reset_in = 0;
  trace_capture_active = true;

  fs::create_directories(out_dir);
  std::array<uint16_t, 224 * 144> frame{};
  unsigned frames = 0;
  bool wrote_pixel = false;
  for (uint64_t cycle_count = 0; cycle_count < max_cycles && frames < target_frames;
       ++cycle_count) {
    cycle();
    if (top->pixel_out_we && top->pixel_out_addr < frame.size()) {
      frame[top->pixel_out_addr] = top->pixel_out_data;
      wrote_pixel = true;
      if (top->pixel_out_addr == frame.size() - 1) {
        const fs::path output = out_dir / ("frame-" + std::to_string(frames) + ".rgb");
        write_rgb(output, frame);
        std::cout << output.string() << '\n';
        ++frames;
      }
    }
  }

  if (trace) trace->close();
  top->final();
  if (!wrote_pixel || frames < target_frames) {
    std::cerr << "simulation timed out after " << max_cycles
              << " system cycles; completed " << frames << " frame(s)\n";
    return 1;
  }
  return 0;
}
