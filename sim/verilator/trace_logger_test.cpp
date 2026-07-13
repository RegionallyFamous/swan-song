// SPDX-License-Identifier: GPL-2.0-only
#include "trace_logger.hpp"

#include <cassert>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>

using swansong::trace::Config;
using swansong::trace::Event;
using swansong::trace::EventType;
using swansong::trace::Format;
using swansong::trace::VramRole;
using swansong::trace::Writer;

template <typename Function>
static void expect_failure(Function function) {
  bool failed = false;
  try {
    function();
  } catch (const std::runtime_error&) {
    failed = true;
  }
  assert(failed);
}

int main() {
  const auto range = swansong::trace::parse_pc_range("0x12345-0x23456");
  assert(range.first == 0x12345);
  assert(range.last == 0x23456);
  assert(range.contains(0x12345) && range.contains(0x23456));
  assert(!range.contains(0x12344) && !range.contains(0x23457));
  expect_failure([] { swansong::trace::parse_pc_range("0x200-0x100"); });
  expect_failure([] { swansong::trace::parse_pc_range("0-0x100000"); });

  const auto address_ranges =
      swansong::trace::parse_address_ranges("0x2000-0x2fff, 0x4000, 20481");
  assert(address_ranges.size() == 3);
  assert(address_ranges[0].contains(0x2000));
  assert(address_ranges[0].contains(0x2fff));
  assert(!address_ranges[0].contains(0x3000));
  assert(address_ranges[1].first == 0x4000 && address_ranges[1].last == 0x4000);
  assert(address_ranges[2].first == 20481 && address_ranges[2].last == 20481);
  expect_failure([] { swansong::trace::parse_address_ranges(""); });
  expect_failure([] { swansong::trace::parse_address_ranges("0x2000-"); });
  expect_failure([] { swansong::trace::parse_address_ranges("0x3000-0x2000"); });
  expect_failure([] { swansong::trace::parse_address_ranges("0x10000"); });
  expect_failure([] { swansong::trace::parse_address_ranges("0x2000,"); });

  const uint8_t screen_roles =
      swansong::trace::parse_vram_roles("SCREEN1_MAP, screen2_tile");
  assert(screen_roles & (1u << static_cast<uint8_t>(VramRole::Screen1Map)));
  assert(screen_roles & (1u << static_cast<uint8_t>(VramRole::Screen2Tile)));
  assert(swansong::trace::parse_vram_roles("all") ==
         swansong::trace::kAllVramRoles);
  assert(swansong::trace::vram_role_from_code(5) == VramRole::SpriteTile);
  expect_failure([] { swansong::trace::parse_vram_roles(""); });
  expect_failure([] { swansong::trace::parse_vram_roles("screen1-map"); });
  expect_failure([] { swansong::trace::parse_vram_roles("screen1_map,"); });
  expect_failure([] { swansong::trace::vram_role_from_code(6); });

  Config config;
  std::istringstream config_text(
      "# Translation trace\n"
      "output = build/sim/game.jsonl\n"
      "format = jsonl\n"
      "events = cpu, vram\n"
      "cpu_pc = 0x80000-0x8ffff\n"
      "vram_address = 0x2000-0x2fff,0x4000\n"
      "vram_role = screen1_map, screen1_tile\n");
  swansong::trace::parse_config(config_text, config, "inline");
  assert(config.output == "build/sim/game.jsonl");
  assert(config.format == Format::Jsonl);
  assert(config.includes(EventType::Cpu));
  assert(!config.includes(EventType::Bank));
  assert(config.includes(EventType::Vram));
  assert(config.cpu_pc && config.cpu_pc->first == 0x80000);
  assert(config.vram_address.size() == 2);
  assert(config.includes(VramRole::Screen1Map));
  assert(config.includes(VramRole::Screen1Tile));
  assert(!config.includes(VramRole::Screen2Map));
  expect_failure([] {
    Config bad;
    std::istringstream text("bogus=yes\n");
    swansong::trace::parse_config(text, bad, "inline");
  });

  std::ostringstream csv;
  Writer csv_writer(csv, Format::Csv);
  csv_writer.write({7, EventType::Cpu, 0xabcde, 0xabcd, 0x012e,
                    std::nullopt, std::nullopt, std::nullopt});
  csv_writer.write({8, EventType::Bank, std::nullopt, std::nullopt,
                    std::nullopt, 0xc2, 0x34, std::nullopt});
  csv_writer.write({9, EventType::Vram, std::nullopt, std::nullopt,
                    std::nullopt, 0x4321, std::nullopt,
                    VramRole::Screen2Tile});
  assert(csv.str() ==
         "cycle,event,physical_pc,cs,ip,address,value,role\n"
         "7,cpu,703710,43981,302,,,\n"
         "8,bank,,,,194,52,\n"
         "9,vram,,,,17185,,screen2_tile\n");

  std::ostringstream jsonl;
  Writer jsonl_writer(jsonl, Format::Jsonl);
  jsonl_writer.write({9, EventType::Vram, std::nullopt, std::nullopt,
                      std::nullopt, 0x4321, std::nullopt,
                      VramRole::SpriteTile});
  assert(jsonl.str() ==
         "{\"cycle\":9,\"event\":\"vram\",\"physical_pc\":null,"
         "\"cs\":null,\"ip\":null,\"address\":17185,\"value\":null,"
         "\"role\":\"sprite_tile\"}\n");

  const std::filesystem::path filtered_path =
      std::filesystem::temp_directory_path() / "swansong-trace-filter-test.csv";
  Config filtered;
  filtered.output = filtered_path;
  filtered.events = static_cast<uint8_t>(EventType::Cpu) |
                    static_cast<uint8_t>(EventType::Vram);
  filtered.vram_address = swansong::trace::parse_address_ranges("0x2000-0x2fff");
  filtered.vram_roles = swansong::trace::parse_vram_roles("screen1_tile");
  {
    swansong::trace::Logger logger(filtered);
    logger.cpu(1, 0x12345, 0x1234, 5);
    logger.vram(2, 0x2000, VramRole::Screen1Map);
    logger.vram(3, 0x1fff, VramRole::Screen1Tile);
    logger.vram(4, 0x2000, VramRole::Screen1Tile);
    logger.vram(5, 0x2fff, VramRole::Screen1Tile);
    logger.vram(6, 0x3000, VramRole::Screen1Tile);
  }
  std::ifstream filtered_input(filtered_path);
  const std::string filtered_text((std::istreambuf_iterator<char>(filtered_input)),
                                  std::istreambuf_iterator<char>());
  assert(filtered_text ==
         "cycle,event,physical_pc,cs,ip,address,value,role\n"
         "1,cpu,74565,4660,5,,,\n"
         "4,vram,,,,8192,,screen1_tile\n"
         "5,vram,,,,12287,,screen1_tile\n");
  std::filesystem::remove(filtered_path);
}
