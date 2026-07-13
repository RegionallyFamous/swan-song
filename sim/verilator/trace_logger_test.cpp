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
using swansong::trace::MemAccess;
using swansong::trace::MemInitiator;
using swansong::trace::MemSpace;
using swansong::trace::OriginStatus;
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

  assert(swansong::trace::parse_mem_initiators("CPU, gdma") == 0x03);
  assert(swansong::trace::parse_mem_accesses("write") == 0x02);
  assert(swansong::trace::parse_mem_spaces("iram,cart_rom_linear") ==
         ((1u << 1) | (1u << 5)));
  assert(swansong::trace::parse_origin_statuses("exact,not_applicable") ==
         ((1u << 1) | (1u << 3)));
  const auto mem_ranges = swansong::trace::parse_mem_ranges(
      "0x100-0x1ff,0xf0000", 0xfffff, "memory address");
  assert(mem_ranges.size() == 2 && mem_ranges[0].contains(0x180));
  expect_failure([] { swansong::trace::parse_mem_initiators("cpu,dma"); });
  expect_failure([] { swansong::trace::parse_mem_spaces("rom"); });
  expect_failure([] {
    swansong::trace::parse_mem_ranges("0x100000", 0xfffff,
                                      "memory address");
  });

  Config config;
  std::istringstream config_text(
      "# Translation trace\n"
      "output = build/sim/game.jsonl\n"
      "format = jsonl\n"
      "events = cpu, vram\n"
      "cpu_pc = 0x80000-0x8ffff\n"
      "vram_address = 0x2000-0x2fff,0x4000\n"
      "vram_role = screen1_map, screen1_tile\n"
      "mem_initiator = cpu,gdma\n"
      "mem_access = write\n"
      "mem_address = 0x4000-0x4fff\n"
      "mem_space = iram\n"
      "mem_offset = 0x4000-0x4fff\n"
      "mem_origin = exact\n"
      "origin_pc = 0xf0000-0xfffff\n");
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
  assert(config.includes(MemInitiator::Cpu));
  assert(config.includes(MemInitiator::Gdma));
  assert(!config.includes(MemInitiator::Sdma));
  assert(config.includes(MemAccess::Write));
  assert(!config.includes(MemAccess::Read));
  assert(config.includes(MemSpace::Iram));
  assert(config.mem_address.size() == 1 && config.mem_offset.size() == 1);
  assert(config.origin_pc && config.origin_pc->first == 0xf0000);
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
  Event csv_vram{9, EventType::Vram, std::nullopt, std::nullopt,
                 std::nullopt, 0x4321, std::nullopt,
                 VramRole::Screen2Tile};
  csv_vram.fetch_value = 0xbeef;
  csv_vram.fetch_collision = 0;
  csv_writer.write(csv_vram);
  csv_writer.write({10, EventType::Mem, std::nullopt, std::nullopt,
                    std::nullopt, 0x4000, 0x1234, std::nullopt,
                    MemInitiator::Gdma, MemAccess::Write, 3,
                    MemSpace::Iram, 0x4000, std::nullopt, std::nullopt,
                    OriginStatus::NotApplicable});
  assert(csv.str() ==
         "cycle,event,physical_pc,cs,ip,address,value,role,initiator,access,"
         "byte_enable,space,mapped_offset,instruction_id,origin_pc,origin_status,"
         "fetch_value,fetch_collision\n"
         "7,cpu,703710,43981,302,,,,,,,,,,,,,\n"
         "8,bank,,,,194,52,,,,,,,,,,,\n"
         "9,vram,,,,17185,,screen2_tile,,,,,,,,,48879,0\n"
         "10,mem,,,,16384,4660,,gdma,write,3,iram,16384,,,not_applicable,,\n");

  std::ostringstream jsonl;
  Writer jsonl_writer(jsonl, Format::Jsonl);
  Event json_vram{9, EventType::Vram, std::nullopt, std::nullopt,
                  std::nullopt, 0x4321, std::nullopt,
                  VramRole::SpriteTile};
  json_vram.fetch_value = 0xcafe;
  json_vram.fetch_collision = 1;
  jsonl_writer.write(json_vram);
  assert(jsonl.str() ==
         "{\"cycle\":9,\"event\":\"vram\",\"physical_pc\":null,"
         "\"cs\":null,\"ip\":null,\"address\":17185,\"value\":null,"
         "\"role\":\"sprite_tile\",\"initiator\":null,\"access\":null,"
         "\"byte_enable\":null,\"space\":null,\"mapped_offset\":null,"
         "\"instruction_id\":null,\"origin_pc\":null,"
         "\"origin_status\":null,\"fetch_value\":51966,"
         "\"fetch_collision\":1}\n");

  std::ostringstream mem_jsonl;
  Writer mem_jsonl_writer(mem_jsonl, Format::Jsonl);
  mem_jsonl_writer.write(
      {10, EventType::Mem, std::nullopt, std::nullopt, std::nullopt,
       0x4000, 0x1234, std::nullopt, MemInitiator::Cpu, MemAccess::Write,
       3, MemSpace::Iram, 0x4000, 7, 0xf0010, OriginStatus::Exact});
  assert(mem_jsonl.str() ==
         "{\"cycle\":10,\"event\":\"mem\",\"physical_pc\":null,"
         "\"cs\":null,\"ip\":null,\"address\":16384,\"value\":4660,"
         "\"role\":null,\"initiator\":\"cpu\",\"access\":\"write\","
         "\"byte_enable\":3,\"space\":\"iram\",\"mapped_offset\":16384,"
         "\"instruction_id\":7,\"origin_pc\":983056,"
         "\"origin_status\":\"exact\",\"fetch_value\":null,"
         "\"fetch_collision\":null}\n");

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
    logger.vram(2, 0x2000, VramRole::Screen1Map, 0x1002, false);
    logger.vram(3, 0x1fff, VramRole::Screen1Tile, 0x1003, false);
    logger.vram(4, 0x2000, VramRole::Screen1Tile, 0x1004, false);
    logger.vram(5, 0x2fff, VramRole::Screen1Tile, 0x1005, true);
    logger.vram(6, 0x3000, VramRole::Screen1Tile, 0x1006, false);
  }
  std::ifstream filtered_input(filtered_path);
  const std::string filtered_text((std::istreambuf_iterator<char>(filtered_input)),
                                  std::istreambuf_iterator<char>());
  assert(filtered_text ==
         "cycle,event,physical_pc,cs,ip,address,value,role,initiator,access,"
         "byte_enable,space,mapped_offset,instruction_id,origin_pc,origin_status,"
         "fetch_value,fetch_collision\n"
         "1,cpu,74565,4660,5,,,,,,,,,,,,,\n"
         "4,vram,,,,8192,,screen1_tile,,,,,,,,,4100,0\n"
         "5,vram,,,,12287,,screen1_tile,,,,,,,,,4101,1\n");
  std::filesystem::remove(filtered_path);

  const std::filesystem::path mem_filtered_path =
      std::filesystem::temp_directory_path() / "swansong-mem-filter-test.csv";
  Config mem_filtered;
  mem_filtered.output = mem_filtered_path;
  mem_filtered.events = static_cast<uint8_t>(EventType::Mem);
  mem_filtered.mem_initiators =
      swansong::trace::parse_mem_initiators("cpu");
  mem_filtered.mem_accesses = swansong::trace::parse_mem_accesses("write");
  mem_filtered.mem_spaces = swansong::trace::parse_mem_spaces("iram");
  mem_filtered.origin_statuses =
      swansong::trace::parse_origin_statuses("exact");
  mem_filtered.mem_address = swansong::trace::parse_mem_ranges(
      "0x4000-0x4fff", 0xfffff, "memory address");
  mem_filtered.mem_offset = swansong::trace::parse_mem_ranges(
      "0x4000-0x4fff", 0xffffff, "memory offset");
  mem_filtered.origin_pc = swansong::trace::parse_pc_range("0xf0000-0xfffff");
  {
    swansong::trace::Logger logger(mem_filtered);
    expect_failure([&logger] {
      logger.mem(0, MemInitiator::Cpu, MemAccess::Write, 0x4000, 0, 3,
                 MemSpace::Iram, 0x4000, std::nullopt, std::nullopt,
                 OriginStatus::Exact);
    });
    expect_failure([&logger] {
      logger.mem(0, MemInitiator::Gdma, MemAccess::Read, 0xf0100, 0, 3,
                 MemSpace::CartRomLinear, 0x100, 1, 0xf0000,
                 OriginStatus::NotApplicable);
    });
    logger.mem(1, MemInitiator::Cpu, MemAccess::Read, 0x4000, 1, 3,
               MemSpace::Iram, 0x4000, 7, 0xf0010, OriginStatus::Exact);
    logger.mem(2, MemInitiator::Gdma, MemAccess::Write, 0x4000, 2, 3,
               MemSpace::Iram, 0x4000, std::nullopt, std::nullopt,
               OriginStatus::NotApplicable);
    logger.mem(3, MemInitiator::Cpu, MemAccess::Write, 0x4000, 0x1234, 3,
               MemSpace::Iram, 0x4000, 7, 0xf0010, OriginStatus::Exact);
  }
  std::ifstream mem_filtered_input(mem_filtered_path);
  const std::string mem_filtered_text(
      (std::istreambuf_iterator<char>(mem_filtered_input)),
      std::istreambuf_iterator<char>());
  assert(mem_filtered_text.find(
             "3,mem,,,,16384,4660,,cpu,write,3,iram,16384,7,983056,exact,,\n") !=
         std::string::npos);
  assert(mem_filtered_text.find("1,mem") == std::string::npos);
  assert(mem_filtered_text.find("2,mem") == std::string::npos);
  std::filesystem::remove(mem_filtered_path);
}
