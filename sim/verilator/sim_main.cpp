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
#include <limits>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

#include "VSwanTop.h"
#include "input_script.hpp"
#include "rom_image.hpp"
#include "trace_logger.hpp"

namespace fs = std::filesystem;

static std::vector<uint8_t> read_file(const fs::path& path) {
  std::ifstream stream(path, std::ios::binary);
  if (!stream) throw std::runtime_error("cannot open " + path.string());
  return {std::istreambuf_iterator<char>(stream), {}};
}

static std::vector<uint8_t> read_file_limited(const fs::path& path,
                                              size_t limit,
                                              const char* description) {
  std::ifstream stream(path, std::ios::binary);
  if (!stream) throw std::runtime_error("cannot open " + path.string());
  std::vector<uint8_t> result;
  result.reserve(std::min<size_t>(limit, 64u * 1024u));
  std::array<char, 16u * 1024u> buffer{};
  while (stream) {
    stream.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
    const size_t count = static_cast<size_t>(stream.gcount());
    if (count > limit - result.size()) {
      throw std::runtime_error(
          std::string(description) + " exceeds " + std::to_string(limit) +
          "-byte limit: " + path.string());
    }
    result.insert(result.end(), buffer.begin(), buffer.begin() + count);
  }
  if (!stream.eof()) throw std::runtime_error("cannot read " + path.string());
  return result;
}

static unsigned parse_frame_count(const std::string& text) {
  size_t consumed = 0;
  uint64_t value = 0;
  try {
    value = std::stoull(text, &consumed, 10);
  } catch (const std::exception&) {
    throw std::runtime_error("--frames must be a decimal integer");
  }
  if (consumed != text.size() || value == 0 ||
      value > std::numeric_limits<unsigned>::max()) {
    throw std::runtime_error("--frames must be within 1.." +
                             std::to_string(std::numeric_limits<unsigned>::max()));
  }
  return static_cast<unsigned>(value);
}

static std::string format_fnv1a64(uint64_t hash) {
  constexpr char digits[] = "0123456789abcdef";
  std::string result(16, '0');
  for (int index = 15; index >= 0; --index) {
    result[static_cast<size_t>(index)] = digits[hash & 0xf];
    hash >>= 4;
  }
  return result;
}

static std::string write_rgb(const fs::path& path,
                             const std::array<uint16_t, 224 * 144>& frame) {
  fs::path temp_path = path;
  temp_path += ".tmp";
  fs::remove(temp_path);
  std::ofstream stream(temp_path, std::ios::binary);
  if (!stream) throw std::runtime_error("cannot write " + temp_path.string());
  uint64_t hash = UINT64_C(0xcbf29ce484222325);
  const auto write_byte = [&](uint8_t byte) {
    stream.put(static_cast<char>(byte));
    hash ^= byte;
    hash *= UINT64_C(0x100000001b3);
  };
  for (uint16_t pixel : frame) {
    const uint8_t r = static_cast<uint8_t>(((pixel >> 8) & 0xf) * 17);
    const uint8_t g = static_cast<uint8_t>(((pixel >> 4) & 0xf) * 17);
    const uint8_t b = static_cast<uint8_t>((pixel & 0xf) * 17);
    write_byte(r);
    write_byte(g);
    write_byte(b);
  }
  stream.close();
  if (!stream) throw std::runtime_error("failed to write " + temp_path.string());

  std::error_code rename_error;
  fs::rename(temp_path, path, rename_error);
  if (rename_error) {
    std::error_code remove_error;
    fs::remove(path, remove_error);
    if (remove_error) {
      throw std::runtime_error("cannot replace " + path.string() + ": " +
                               remove_error.message());
    }
    fs::rename(temp_path, path);
  }
  return format_fnv1a64(hash);
}

static std::string json_escape(const std::string& value) {
  std::string escaped;
  for (const unsigned char character : value) {
    switch (character) {
      case '\\': escaped += "\\\\"; break;
      case '"': escaped += "\\\""; break;
      case '\n': escaped += "\\n"; break;
      case '\r': escaped += "\\r"; break;
      case '\t': escaped += "\\t"; break;
      default:
        if (character < 0x20) throw std::runtime_error("control byte in manifest path");
        escaped += static_cast<char>(character);
    }
  }
  return escaped;
}

static fs::path trace_manifest_path(const fs::path& trace) {
  fs::path path = trace;
  path += ".manifest.json";
  return path;
}

static fs::path trace_manifest_temp_path(const fs::path& trace) {
  fs::path path = trace_manifest_path(trace);
  path += ".tmp";
  return path;
}

static std::string trace_fnv1a64(const fs::path& path) {
  std::ifstream input(path, std::ios::binary);
  if (!input) throw std::runtime_error("cannot hash " + path.string());
  uint64_t hash = UINT64_C(0xcbf29ce484222325);
  std::array<char, 16384> buffer{};
  while (input) {
    input.read(buffer.data(), buffer.size());
    for (std::streamsize index = 0; index < input.gcount(); ++index) {
      hash ^= static_cast<unsigned char>(buffer[static_cast<size_t>(index)]);
      hash *= UINT64_C(0x100000001b3);
    }
  }
  if (!input.eof()) throw std::runtime_error("failed to hash " + path.string());
  return format_fnv1a64(hash);
}

static std::string bytes_fnv1a64(const std::vector<uint8_t>& bytes) {
  uint64_t hash = UINT64_C(0xcbf29ce484222325);
  for (const uint8_t byte : bytes) {
    hash ^= byte;
    hash *= UINT64_C(0x100000001b3);
  }
  return format_fnv1a64(hash);
}

struct FrameArtifact {
  unsigned index;
  uint64_t completion_cycle;
  fs::path path;
  uintmax_t size_bytes;
  std::string fnv1a64;
};

static fs::path weakly_canonical_or_absolute(const fs::path& path) {
  std::error_code error;
  const fs::path canonical = fs::weakly_canonical(path, error);
  return error ? fs::absolute(path).lexically_normal() : canonical;
}

static bool generated_frame_path_collision(const fs::path& candidate,
                                           const fs::path& out_dir,
                                           unsigned target_frames) {
  const fs::path parent = candidate.has_parent_path() ? candidate.parent_path() : ".";
  if (weakly_canonical_or_absolute(parent) != weakly_canonical_or_absolute(out_dir)) {
    return false;
  }
  const std::string name = candidate.filename().string();
  constexpr const char* prefix = "frame-";
  const size_t prefix_size = 6;
  size_t suffix_size = 0;
  if (name.size() > 4 && name.compare(name.size() - 4, 4, ".rgb") == 0) {
    suffix_size = 4;
  } else if (name.size() > 8 &&
             name.compare(name.size() - 8, 8, ".rgb.tmp") == 0) {
    suffix_size = 8;
  } else {
    return false;
  }
  if (name.compare(0, prefix_size, prefix) != 0) return false;
  const std::string index_text =
      name.substr(prefix_size, name.size() - prefix_size - suffix_size);
  if (index_text.empty() ||
      std::any_of(index_text.begin(), index_text.end(),
                  [](unsigned char character) { return character < '0' || character > '9'; }) ||
      (index_text.size() > 1 && index_text.front() == '0')) {
    return false;
  }
  try {
    return std::stoull(index_text) < target_frames;
  } catch (const std::exception&) {
    return false;
  }
}

static void reject_symlink_output(const fs::path& path, const char* description) {
  std::error_code error;
  const fs::file_status status = fs::symlink_status(path, error);
  if (!error && fs::is_symlink(status)) {
    throw std::runtime_error(std::string(description) +
                             " must not be a symlink: " + path.string());
  }
}

static std::string manifest_relative_path(const fs::path& artifact,
                                          const fs::path& manifest) {
  const fs::path parent = manifest.has_parent_path() ? manifest.parent_path() : ".";
  const fs::path relative = fs::absolute(artifact).lexically_normal().lexically_relative(
      fs::absolute(parent).lexically_normal());
  if (relative.empty()) {
    throw std::runtime_error("cannot make frame path relative to trace manifest");
  }
  return relative.generic_string();
}

static void write_trace_manifest(const swansong::trace::Config& config,
                                 uint64_t capture_cycles, unsigned frames,
                                 const std::vector<uint8_t>& rom,
                                 const std::vector<uint8_t>& bios,
                                 const swansong::input::Script* input_script,
                                 size_t applied_input_events,
                                 const std::vector<FrameArtifact>* frame_artifacts) {
  const fs::path path = trace_manifest_path(config.output);
  const fs::path temp_path = trace_manifest_temp_path(config.output);
  if (path.has_parent_path()) fs::create_directories(path.parent_path());
  if (frame_artifacts && frame_artifacts->size() != frames) {
    throw std::runtime_error("frame artifact count does not match completed frames");
  }
  if (frame_artifacts) {
    uint64_t previous_cycle = 0;
    const fs::file_status trace_status = fs::symlink_status(config.output);
    if (fs::is_symlink(trace_status) || !fs::is_regular_file(trace_status)) {
      throw std::runtime_error("frame-bound trace is not a regular non-symlink file");
    }
    for (size_t position = 0; position < frame_artifacts->size(); ++position) {
      const FrameArtifact& artifact = (*frame_artifacts)[position];
      if (artifact.index != position) {
        throw std::runtime_error("frame artifact indices are not contiguous");
      }
      if ((position > 0 && artifact.completion_cycle <= previous_cycle) ||
          artifact.completion_cycle >= capture_cycles) {
        throw std::runtime_error("frame artifact cycles are outside the capture order");
      }
      previous_cycle = artifact.completion_cycle;
      const fs::file_status status = fs::symlink_status(artifact.path);
      if (fs::is_symlink(status) || !fs::is_regular_file(status)) {
        throw std::runtime_error("frame artifact is not a regular non-symlink file");
      }
      if (artifact.size_bytes != 224u * 144u * 3u ||
          fs::file_size(artifact.path) != artifact.size_bytes) {
        throw std::runtime_error("frame artifact is not 224x144 RGB888");
      }
      if (trace_fnv1a64(artifact.path) != artifact.fnv1a64) {
        throw std::runtime_error("frame artifact changed after publication");
      }
      if (fs::equivalent(artifact.path, config.output)) {
        throw std::runtime_error("frame artifact aliases the event trace");
      }
      for (size_t earlier = 0; earlier < position; ++earlier) {
        if (fs::equivalent(artifact.path, (*frame_artifacts)[earlier].path)) {
          throw std::runtime_error("frame artifacts alias one filesystem object");
        }
      }
    }
    if (frame_artifacts->empty() ||
        frame_artifacts->back().completion_cycle + 1 != capture_cycles) {
      throw std::runtime_error("final frame artifact does not end the capture");
    }
  }
  fs::remove(temp_path);
  std::ofstream output(temp_path, std::ios::out | std::ios::trunc);
  if (!output) throw std::runtime_error("cannot write " + temp_path.string());

  const uintmax_t trace_size = fs::file_size(config.output);
  const std::string trace_hash = trace_fnv1a64(config.output);

  const bool memory_filters =
      config.mem_initiators != swansong::trace::kAllMemInitiators ||
      config.mem_accesses != swansong::trace::kAllMemAccesses ||
      config.mem_spaces != swansong::trace::kAllMemSpaces ||
      config.origin_statuses != swansong::trace::kAllOriginStatuses ||
      !config.mem_address.empty() || !config.mem_offset.empty() ||
      !config.origin_pc.empty();
  const bool display_filters =
      config.vram_roles != swansong::trace::kAllVramRoles ||
      !config.vram_address.empty();
  const bool has_mem = config.includes(swansong::trace::EventType::Mem);
  const bool has_vram = config.includes(swansong::trace::EventType::Vram);
  const bool has_bg_cell = config.includes(swansong::trace::EventType::BgCell);
  const bool has_sprite_row = config.includes(swansong::trace::EventType::SpriteRow);

  output << "{\n"
         << "  \"schema\": \"swan-song-trace-manifest-v"
         << (frame_artifacts ? 2 : 1) << "\",\n"
         << "  \"trace_schema\": " << (has_sprite_row ? 6 : 5) << ",\n"
         << "  \"trace_file\": \"" << json_escape(config.output.string()) << "\",\n"
         << "  \"trace_size_bytes\": " << trace_size << ",\n"
         << "  \"trace_fnv1a64\": \"" << trace_hash << "\",\n"
         << "  \"capture_start\": \"reset_release\",\n"
         << "  \"capture_completed\": true,\n"
         << "  \"capture_cycles\": " << capture_cycles << ",\n"
         << "  \"completed_frames\": " << frames;
  if (frame_artifacts) {
    output << ",\n  \"frames\": [";
    for (size_t position = 0; position < frame_artifacts->size(); ++position) {
      const FrameArtifact& artifact = (*frame_artifacts)[position];
      output << (position == 0 ? "\n" : ",\n")
             << "    {\"index\": " << artifact.index
             << ", \"completion_cycle\": " << artifact.completion_cycle
             << ", \"file\": \""
             << json_escape(manifest_relative_path(artifact.path, path))
             << "\", \"size_bytes\": " << artifact.size_bytes
             << ", \"fnv1a64\": \"" << artifact.fnv1a64 << "\"}";
    }
    output << "\n  ]";
  }
  output << ",\n"
         << "  \"rom_size\": " << rom.size() << ",\n"
         << "  \"rom_fnv1a64\": \"" << bytes_fnv1a64(rom) << "\",\n"
         << "  \"bios_size\": " << bios.size() << ",\n"
         << "  \"bios_fnv1a64\": \"" << bytes_fnv1a64(bios) << "\",\n"
         << "  \"iram_initial_state\": \"zero\",\n"
         << "  \"savestate_inputs_asserted\": false";
  if (input_script) {
    output << ",\n"
           << "  \"input_script\": {\n"
           << "    \"schema\": \"" << swansong::input::kSchema << "\",\n"
           << "    \"source_size_bytes\": "
           << input_script->source_size_bytes << ",\n"
           << "    \"source_fnv1a64\": \""
           << input_script->source_fnv1a64 << "\",\n"
           << "    \"normalized_fnv1a64\": \""
           << input_script->normalized_fnv1a64 << "\",\n"
           << "    \"event_count\": " << input_script->events.size() << ",\n"
           << "    \"applied_events\": " << applied_input_events << ",\n"
           << "    \"completed\": true,\n"
           << "    \"final_state\": \"released\"\n"
           << "  }";
  }
  output << ",\n"
         << "  \"events\": {\n"
         << "    \"cpu\": " << (config.includes(swansong::trace::EventType::Cpu) ? "true" : "false") << ",\n"
         << "    \"bank\": " << (config.includes(swansong::trace::EventType::Bank) ? "true" : "false") << ",\n"
         << "    \"vram\": " << (has_vram ? "true" : "false") << ",\n"
         << "    \"mem\": " << (has_mem ? "true" : "false") << ",\n"
         << "    \"bg_cell\": " << (has_bg_cell ? "true" : "false");
  if (has_sprite_row) {
    output << ",\n    \"sprite_row\": true";
  }
  output << "\n"
         << "  },\n"
         << "  \"memory_filters_active\": " << (memory_filters ? "true" : "false") << ",\n"
         << "  \"display_filters_active\": " << (display_filters ? "true" : "false") << ",\n"
         << "  \"complete_memory_history\": " << (has_mem && !memory_filters ? "true" : "false") << ",\n"
         << "  \"complete_display_history\": " << (has_vram && !display_filters ? "true" : "false") << ",\n"
         << "  \"complete_bg_cell_history\": " << (has_bg_cell ? "true" : "false");
  if (has_sprite_row) {
    output << ",\n  \"complete_sprite_row_history\": true";
  }
  output << "\n}\n";
  output.close();
  if (!output) throw std::runtime_error("failed to write " + temp_path.string());
  fs::remove(path);
  fs::rename(temp_path, path);
}

static void usage(const char* argv0) {
  std::cerr
      << "usage: " << argv0 << " --rom FILE [OPTIONS]\n\n"
      << "Simulation:\n"
      << "  --bios FILE             4 KiB mono or 8 KiB color BIOS\n"
      << "  --frames N              stop after N complete frames (default: 1)\n"
      << "  --out DIR               raw/PNG frame directory\n"
      << "  --max-cycles N          timeout in 36.864 MHz system cycles\n"
      << "  --input-script FILE     system-cycle controller state replay\n"
      << "  --trace FILE.vcd        whole-design VCD waveform\n\n"
      << "Structured debug trace:\n"
      << "  --event-trace FILE      write CSV, or JSONL for a .jsonl filename\n"
      << "  --trace-frame-artifacts bind raw RGB frames and cycles in manifest v2\n"
      << "  --trace-events LIST     cpu,bank,vram,mem,bg_cell,sprite_row (default: all)\n"
      << "  --trace-pc RANGES       inclusive 20-bit CPU PC range union\n"
      << "  --trace-vram-address R  VRAM ADDR or START-END list (inclusive)\n"
      << "  --trace-vram-role LIST  screen1_map,screen1_tile,screen2_map,\n"
         "                            screen2_tile,sprite_table,sprite_tile\n"
      << "  --trace-mem-initiator L cpu,gdma,sdma\n"
      << "  --trace-mem-access L    read,write\n"
      << "  --trace-mem-address R   20-bit address/range list\n"
      << "  --trace-mem-space L     iram,cart_sram,cart_rom0,cart_rom1,\n"
         "                            cart_rom_linear,boot_rom,unmapped,absent_sram\n"
      << "  --trace-mem-offset R    resolved 24-bit byte offset/range list\n"
      << "  --trace-mem-origin L    exact,unattributed,not_applicable\n"
      << "  --trace-origin-pc RANGES exact memory-owner PC range union\n"
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
                     decltype(std::declval<Top>().debug_reg_instruction_id),
                     decltype(std::declval<Top>().debug_reg_origin_pc),
                     decltype(std::declval<Top>().debug_reg_origin_status),
                     decltype(std::declval<Top>().romtype),
                     decltype(std::declval<Top>().debug_gpu_vram_valid),
                     decltype(std::declval<Top>().debug_gpu_vram_addr),
                     decltype(std::declval<Top>().debug_gpu_vram_role),
                     decltype(std::declval<Top>().debug_gpu_vram_value),
                     decltype(std::declval<Top>().debug_gpu_vram_collision),
                     decltype(std::declval<Top>().debug_bg0_cell_valid),
                     decltype(std::declval<Top>().debug_bg0_cell_map_addr),
                     decltype(std::declval<Top>().debug_bg0_cell_map_value),
                     decltype(std::declval<Top>().debug_bg0_cell_row_addr),
                     decltype(std::declval<Top>().debug_bg0_cell_row_value),
                     decltype(std::declval<Top>().debug_bg0_cell_meta),
                     decltype(std::declval<Top>().debug_bg1_cell_valid),
                     decltype(std::declval<Top>().debug_bg1_cell_map_addr),
                     decltype(std::declval<Top>().debug_bg1_cell_map_value),
                     decltype(std::declval<Top>().debug_bg1_cell_row_addr),
                     decltype(std::declval<Top>().debug_bg1_cell_row_value),
                     decltype(std::declval<Top>().debug_bg1_cell_meta),
                     decltype(std::declval<Top>().debug_sprite_row_valid),
                     decltype(std::declval<Top>().debug_sprite_row_table_addr),
                     decltype(std::declval<Top>().debug_sprite_row_table_value),
                     decltype(std::declval<Top>().debug_sprite_row_table_generation),
                     decltype(std::declval<Top>().debug_sprite_row_line_epoch),
                     decltype(std::declval<Top>().debug_sprite_row_addr),
                     decltype(std::declval<Top>().debug_sprite_row_value),
                     decltype(std::declval<Top>().debug_sprite_row_meta),
                     decltype(std::declval<Top>().debug_mem_valid),
                     decltype(std::declval<Top>().debug_mem_write),
                     decltype(std::declval<Top>().debug_mem_initiator),
                     decltype(std::declval<Top>().debug_mem_address),
                     decltype(std::declval<Top>().debug_mem_value),
                     decltype(std::declval<Top>().debug_mem_byte_enable),
                     decltype(std::declval<Top>().debug_mem_space),
                     decltype(std::declval<Top>().debug_mem_offset),
                     decltype(std::declval<Top>().debug_mem_offset_valid),
                     decltype(std::declval<Top>().debug_mem_instruction_id),
                     decltype(std::declval<Top>().debug_mem_origin_pc),
                     decltype(std::declval<Top>().debug_mem_origin_status)>> {
  static constexpr bool available = true;

  void capture(const Top& top, swansong::trace::Logger& logger, uint64_t cycle) {
    if (top.debug_cpu_done) {
      logger.cpu(cycle, top.debug_cpu_pc, top.debug_cpu_cs, top.debug_cpu_ip);
    }
    const bool common_bank_port =
        top.debug_reg_addr >= 0xc0 && top.debug_reg_addr <= 0xc3;
    const bool mapper_2003_alias =
        top.romtype == 0x01 &&
        (top.debug_reg_addr == 0xcf || top.debug_reg_addr == 0xd0 ||
         top.debug_reg_addr == 0xd2 || top.debug_reg_addr == 0xd4);
    if (top.debug_reg_write && (common_bank_port || mapper_2003_alias)) {
      logger.bank(
          cycle, top.debug_reg_addr, top.debug_reg_data,
          top.debug_reg_instruction_id, top.debug_reg_origin_pc,
          swansong::trace::origin_status_from_code(
              top.debug_reg_origin_status));
    }
    if (top.debug_gpu_vram_valid) {
      logger.vram(cycle, top.debug_gpu_vram_addr,
                  swansong::trace::vram_role_from_code(
                      top.debug_gpu_vram_role),
                  top.debug_gpu_vram_value,
                  top.debug_gpu_vram_collision != 0);
    }
    const auto capture_bg_cell = [&](uint8_t layer, uint16_t map_address,
                                     uint16_t map_value, uint16_t row_address,
                                     uint32_t row_value, uint32_t meta) {
      const uint8_t bpp = (meta & (1u << 16)) ? 4 : 2;
      logger.bg_cell(
          cycle, layer, map_address, map_value,
          static_cast<uint8_t>((map_address >> 1) & 31),
          static_cast<uint8_t>((map_address >> 6) & 31),
          (meta & (1u << 21)) != 0, static_cast<uint16_t>(meta & 0x3ff),
          static_cast<uint8_t>((meta >> 10) & 0xf),
          (meta & (1u << 14)) != 0, (meta & (1u << 15)) != 0, bpp,
          (meta & (1u << 17)) != 0,
          static_cast<uint8_t>((meta >> 18) & 7), row_address, bpp,
          row_value, (meta & (1u << 22)) != 0, (meta & (1u << 23)) != 0);
    };
    if (top.debug_bg0_cell_valid) {
      capture_bg_cell(1, top.debug_bg0_cell_map_addr,
                      top.debug_bg0_cell_map_value,
                      top.debug_bg0_cell_row_addr,
                      top.debug_bg0_cell_row_value, top.debug_bg0_cell_meta);
    }
    if (top.debug_bg1_cell_valid) {
      capture_bg_cell(2, top.debug_bg1_cell_map_addr,
                      top.debug_bg1_cell_map_value,
                      top.debug_bg1_cell_row_addr,
                      top.debug_bg1_cell_row_value, top.debug_bg1_cell_meta);
    }
    if (top.debug_sprite_row_valid) {
      const uint32_t meta = top.debug_sprite_row_meta;
      logger.sprite_row(
          cycle, top.debug_sprite_row_table_addr,
          top.debug_sprite_row_table_value, (meta & (1u << 15)) != 0,
          top.debug_sprite_row_table_generation,
          static_cast<uint8_t>(meta & 0xff),
          static_cast<uint8_t>((meta >> 8) & 0x1f),
          top.debug_sprite_row_line_epoch,
          (meta & (1u << 13)) ? 4 : 2,
          (meta & (1u << 14)) != 0, top.debug_sprite_row_addr,
          top.debug_sprite_row_value, (meta & (1u << 16)) != 0);
    }
    if (top.debug_mem_valid) {
      const auto origin_status = swansong::trace::origin_status_from_code(
          top.debug_mem_origin_status);
      std::optional<uint32_t> mapped_offset;
      std::optional<uint32_t> instruction_id;
      std::optional<uint32_t> origin_pc;
      if (top.debug_mem_offset_valid) mapped_offset = top.debug_mem_offset;
      if (origin_status == swansong::trace::OriginStatus::Exact) {
        instruction_id = top.debug_mem_instruction_id;
        origin_pc = top.debug_mem_origin_pc;
      }
      logger.mem(
          cycle,
          swansong::trace::mem_initiator_from_code(top.debug_mem_initiator),
          top.debug_mem_write ? swansong::trace::MemAccess::Write
                              : swansong::trace::MemAccess::Read,
          top.debug_mem_address, top.debug_mem_value,
          top.debug_mem_byte_enable,
          swansong::trace::mem_space_from_code(top.debug_mem_space),
          mapped_offset, instruction_id, origin_pc, origin_status);
    }
  }
};

static int run_main(int argc, char** argv) {
  Verilated::commandArgs(argc, argv);
  fs::path rom_path;
  fs::path bios_path;
  fs::path out_dir = "build/sim/frames";
  fs::path trace_path;
  fs::path input_script_path;
  swansong::trace::Config event_trace_config;
  uint64_t max_cycles = 36'864'000;
  unsigned target_frames = 1;
  bool trace_frame_artifacts = false;

  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    auto value = [&](const char* name) -> std::string {
      if (++i >= argc) throw std::runtime_error(std::string("missing value for ") + name);
      return argv[i];
    };
    if (arg == "--rom") rom_path = value("--rom");
    else if (arg == "--bios") bios_path = value("--bios");
    else if (arg == "--frames") target_frames = parse_frame_count(value("--frames"));
    else if (arg == "--out") out_dir = value("--out");
    else if (arg == "--input-script") input_script_path = value("--input-script");
    else if (arg == "--trace") trace_path = value("--trace");
    else if (arg == "--event-trace") event_trace_config.output = value("--event-trace");
    else if (arg == "--trace-frame-artifacts") trace_frame_artifacts = true;
    else if (arg == "--trace-events") {
      event_trace_config.events = swansong::trace::parse_events(value("--trace-events"));
    } else if (arg == "--trace-pc") {
      event_trace_config.cpu_pc =
          swansong::trace::parse_pc_ranges(value("--trace-pc"));
    } else if (arg == "--trace-vram-address") {
      event_trace_config.vram_address =
          swansong::trace::parse_address_ranges(value("--trace-vram-address"));
    } else if (arg == "--trace-vram-role") {
      event_trace_config.vram_roles =
          swansong::trace::parse_vram_roles(value("--trace-vram-role"));
    } else if (arg == "--trace-mem-initiator") {
      event_trace_config.mem_initiators =
          swansong::trace::parse_mem_initiators(value("--trace-mem-initiator"));
    } else if (arg == "--trace-mem-access") {
      event_trace_config.mem_accesses =
          swansong::trace::parse_mem_accesses(value("--trace-mem-access"));
    } else if (arg == "--trace-mem-address") {
      event_trace_config.mem_address = swansong::trace::parse_mem_ranges(
          value("--trace-mem-address"), 0xfffff, "memory address");
    } else if (arg == "--trace-mem-space") {
      event_trace_config.mem_spaces =
          swansong::trace::parse_mem_spaces(value("--trace-mem-space"));
    } else if (arg == "--trace-mem-offset") {
      event_trace_config.mem_offset = swansong::trace::parse_mem_ranges(
          value("--trace-mem-offset"), 0xffffff, "memory offset");
    } else if (arg == "--trace-mem-origin") {
      event_trace_config.origin_statuses =
          swansong::trace::parse_origin_statuses(value("--trace-mem-origin"));
    } else if (arg == "--trace-origin-pc") {
      event_trace_config.origin_pc =
          swansong::trace::parse_pc_ranges(value("--trace-origin-pc"));
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
  if (trace_frame_artifacts && !event_trace_config.enabled()) {
    throw std::runtime_error("--trace-frame-artifacts requires --event-trace");
  }
  if (trace_frame_artifacts) {
    reject_symlink_output(event_trace_config.output, "event trace output");
    if (!trace_path.empty()) reject_symlink_output(trace_path, "VCD output");
    const std::array<fs::path, 3> trace_outputs = {
        event_trace_config.output,
        trace_manifest_path(event_trace_config.output),
        trace_manifest_temp_path(event_trace_config.output),
    };
    for (const fs::path& output : trace_outputs) {
      if (generated_frame_path_collision(output, out_dir, target_frames)) {
        throw std::runtime_error("trace output collides with a raw frame path: " +
                                 output.string());
      }
    }
    if (!trace_path.empty() &&
        generated_frame_path_collision(trace_path, out_dir, target_frames)) {
      throw std::runtime_error("VCD output collides with a raw frame path: " +
                               trace_path.string());
    }
  }

  // A manifest certifies one successful trace. Invalidate any older
  // certificate before validating inputs that could abort this attempted run.
  if (event_trace_config.enabled()) {
    fs::remove(trace_manifest_path(event_trace_config.output));
    fs::remove(trace_manifest_temp_path(event_trace_config.output));
  }

  std::optional<swansong::input::Script> input_script;
  if (!input_script_path.empty()) {
    const auto input_bytes = read_file_limited(
        input_script_path, swansong::input::kMaxSourceSizeBytes,
        "input script");
    const std::string input_text(input_bytes.begin(), input_bytes.end());
    input_script = swansong::input::parse_script(
        input_text, input_script_path.string());
    if (input_script->events.back().cycle >= max_cycles) {
      std::cerr << "input script final release must occur before --max-cycles\n";
      return 2;
    }
  }

  const auto rom = read_file(rom_path);
  const auto prepared_rom = swansong::rom::prepare(rom);
  const auto& mapped_rom = prepared_rom.mapped;
  const bool color_cartridge = mapped_rom[mapped_rom.size() - 9] == 1;

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
  // The direct SwanTop harness retains the legacy deterministic cold-reset
  // seed. The Pocket wrapper drives this high and supplies both persistent
  // model banks through the dedicated second port instead.
  top->preserve_internal_eeprom = 0;
  top->EXTRAM_dataread = 0;
  top->eeprom_addr = 0;
  top->eeprom_din = 0;
  top->eeprom_req = 0;
  top->eeprom_rnw = 1;
  top->internal_eeprom_bank = 0;
  top->internal_eeprom_addr = 0;
  top->internal_eeprom_din = 0;
  top->internal_eeprom_req = 0;
  top->internal_eeprom_rnw = 1;
  top->maskAddr = static_cast<uint32_t>(mapped_rom.size() - 1);
  top->romtype = mapped_rom[mapped_rom.size() - 3];
  top->ramtype = mapped_rom[mapped_rom.size() - 5];
  top->hasRTC = mapped_rom[mapped_rom.size() - 3] == 1;
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
      const uint32_t a = address & static_cast<uint32_t>(mapped_rom.size() - 1);
      const uint8_t lo = mapped_rom[a % mapped_rom.size()];
      const uint8_t hi = mapped_rom[(a + 1) % mapped_rom.size()];
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

  // Establish the initialized low clock levels before the first programming
  // edge.  Without this evaluation Verilator has no preceding clk=0 sample,
  // so the first 0->1 transition is not observed and BIOS bytes 0/1 remain
  // unwritten.
  eval();

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
  std::vector<FrameArtifact> frame_artifacts;
  std::optional<swansong::input::Replay> input_replay;
  if (input_script) input_replay.emplace(*input_script);
  for (uint64_t cycle_count = 0; cycle_count < max_cycles && frames < target_frames;
       ++cycle_count) {
    if (input_replay) {
      swansong::input::apply(input_replay->state_for_cycle(cycle_count), *top);
    }
    cycle();
    if (top->pixel_out_we && top->pixel_out_addr < frame.size()) {
      frame[top->pixel_out_addr] = top->pixel_out_data;
      wrote_pixel = true;
      if (top->pixel_out_addr == frame.size() - 1) {
        const fs::path output = out_dir / ("frame-" + std::to_string(frames) + ".rgb");
        const std::string frame_hash = write_rgb(output, frame);
        std::cout << output.string() << '\n';
        if (trace_frame_artifacts) {
          // cycle_count is the reset-release trace cycle whose rising edge
          // produced the last visible pixel in this raw RGB artifact.
          frame_artifacts.push_back(
              {frames, cycle_count, output, 224u * 144u * 3u, frame_hash});
        }
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
  if (input_replay && !input_replay->completed()) {
    std::cerr << "simulation reached its frame target before applying the "
                 "complete input script\n";
    return 1;
  }
  if (event_trace) {
    event_trace.reset();
    write_trace_manifest(event_trace_config, trace_cycle, frames, rom, bios,
                         input_script ? &*input_script : nullptr,
                         input_replay ? input_replay->applied_events() : 0,
                         trace_frame_artifacts ? &frame_artifacts : nullptr);
  }
  return 0;
}

int main(int argc, char** argv) {
  try {
    return run_main(argc, argv);
  } catch (const std::exception& error) {
    std::cerr << "error: " << error.what() << '\n';
    return 2;
  }
}
