// SPDX-License-Identifier: GPL-2.0-only
#include "trace_logger.hpp"

#include <cassert>
#include <sstream>
#include <stdexcept>
#include <string>

using swansong::trace::Config;
using swansong::trace::Event;
using swansong::trace::EventType;
using swansong::trace::Format;
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

  Config config;
  std::istringstream config_text(
      "# Translation trace\n"
      "output = build/sim/game.jsonl\n"
      "format = jsonl\n"
      "events = cpu, vram\n"
      "cpu_pc = 0x80000-0x8ffff\n");
  swansong::trace::parse_config(config_text, config, "inline");
  assert(config.output == "build/sim/game.jsonl");
  assert(config.format == Format::Jsonl);
  assert(config.includes(EventType::Cpu));
  assert(!config.includes(EventType::Bank));
  assert(config.includes(EventType::Vram));
  assert(config.cpu_pc && config.cpu_pc->first == 0x80000);
  expect_failure([] {
    Config bad;
    std::istringstream text("bogus=yes\n");
    swansong::trace::parse_config(text, bad, "inline");
  });

  std::ostringstream csv;
  Writer csv_writer(csv, Format::Csv);
  csv_writer.write({7, EventType::Cpu, 0xabcde, 0xabcd, 0x012e,
                    std::nullopt, std::nullopt});
  csv_writer.write({8, EventType::Bank, std::nullopt, std::nullopt,
                    std::nullopt, 0xc2, 0x34});
  assert(csv.str() ==
         "cycle,event,physical_pc,cs,ip,address,value\n"
         "7,cpu,703710,43981,302,,\n"
         "8,bank,,,,194,52\n");

  std::ostringstream jsonl;
  Writer jsonl_writer(jsonl, Format::Jsonl);
  jsonl_writer.write({9, EventType::Vram, std::nullopt, std::nullopt,
                      std::nullopt, 0x4321, std::nullopt});
  assert(jsonl.str() ==
         "{\"cycle\":9,\"event\":\"vram\",\"physical_pc\":null,"
         "\"cs\":null,\"ip\":null,\"address\":17185,\"value\":null}\n");
}
