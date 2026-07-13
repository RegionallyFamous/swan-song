// SPDX-License-Identifier: GPL-2.0-only
#include "input_script.hpp"

#include <cassert>
#include <cstdint>
#include <sstream>
#include <stdexcept>
#include <string>

template <typename Function>
static void expect_failure(Function function, const std::string& expected) {
  try {
    function();
  } catch (const std::runtime_error& error) {
    assert(std::string(error.what()).find(expected) != std::string::npos);
    return;
  }
  assert(false);
}

struct FakeTop {
  uint8_t KeyX1 = 0;
  uint8_t KeyX2 = 0;
  uint8_t KeyX3 = 0;
  uint8_t KeyX4 = 0;
  uint8_t KeyY1 = 0;
  uint8_t KeyY2 = 0;
  uint8_t KeyY3 = 0;
  uint8_t KeyY4 = 0;
  uint8_t KeyStart = 0;
  uint8_t KeyA = 0;
  uint8_t KeyB = 0;
};

int main() {
  const std::string source =
      "# Full controller states, counted from reset release\r\n"
      "0 start,a\r\n"
      "12000 none\r\n"
      "500000 x1,x2,x3,x4,y1,y2,y3,y4,start,a,b\r\n"
      "500001 none # release\r\n";
  const auto script = swansong::input::parse_script(source, "route.input");
  assert(script.events.size() == 4);
  assert(script.source_size_bytes == source.size());
  assert(script.source_fnv1a64 == swansong::input::fnv1a64(source));
  assert(script.normalized_fnv1a64 == swansong::input::fnv1a64(
      "0 0300\n12000 0000\n500000 07ff\n500001 0000\n"));

  swansong::input::Replay replay(script);
  assert(replay.state_for_cycle(0) ==
         (swansong::input::Start | swansong::input::A));
  assert(replay.state_for_cycle(11999) ==
         (swansong::input::Start | swansong::input::A));
  assert(replay.state_for_cycle(12000) == 0);
  assert(!replay.completed());
  assert(replay.state_for_cycle(500000) == 0x07ff);
  assert(replay.state_for_cycle(500001) == 0);
  assert(replay.completed());
  assert(replay.applied_events() == 4);

  swansong::input::Replay skipped(script);
  assert(skipped.state_for_cycle(11999) ==
         (swansong::input::Start | swansong::input::A));
  assert(skipped.applied_events() == 1);
  assert(skipped.state_for_cycle(500001) == 0);
  assert(skipped.completed());
  expect_failure(
      [&] { skipped.state_for_cycle(500000); }, "must not move backwards");

  // Replay owns its event schedule, so construction from a temporary is safe.
  swansong::input::Replay temporary(
      swansong::input::parse_script("0 x2\n1 none\n"));
  assert(temporary.state_for_cycle(1) == 0);
  assert(temporary.completed());

  swansong::input::Replay delayed(
      swansong::input::parse_script("100 x2\n200 none\n"));
  assert(delayed.state_for_cycle(0) == 0);
  assert(delayed.state_for_cycle(99) == 0);
  assert(delayed.applied_events() == 0);
  assert(!delayed.completed());
  assert(delayed.state_for_cycle(100) == swansong::input::X2);

  FakeTop top;
  swansong::input::apply(0x07ff, top);
  assert(top.KeyX1 && top.KeyX2 && top.KeyX3 && top.KeyX4);
  assert(top.KeyY1 && top.KeyY2 && top.KeyY3 && top.KeyY4);
  assert(top.KeyStart && top.KeyA && top.KeyB);
  swansong::input::apply(0, top);
  assert(!top.KeyX1 && !top.KeyX2 && !top.KeyX3 && !top.KeyX4);
  assert(!top.KeyY1 && !top.KeyY2 && !top.KeyY3 && !top.KeyY4);
  assert(!top.KeyStart && !top.KeyA && !top.KeyB);

  expect_failure(
      [] { swansong::input::parse_script(""); }, "has no events");
  expect_failure(
      [] { swansong::input::parse_script("0 none\n"); }, "never presses");
  expect_failure(
      [] { swansong::input::parse_script("0 x1\n"); }, "final event");
  expect_failure(
      [] { swansong::input::parse_script("0 x1\n0 none\n"); },
      "strictly increasing");
  expect_failure(
      [] { swansong::input::parse_script("2 x1\n1 none\n"); },
      "strictly increasing");
  expect_failure(
      [] { swansong::input::parse_script("0 x1,x1\n1 none\n"); },
      "duplicate button");
  expect_failure(
      [] { swansong::input::parse_script("0 x5\n1 none\n"); },
      "unknown button");
  expect_failure(
      [] { swansong::input::parse_script("0 X1\n1 none\n"); },
      "unknown button");
  expect_failure(
      [] { swansong::input::parse_script("0 none,x1\n1 none\n"); },
      "unknown button");
  expect_failure(
      [] { swansong::input::parse_script("0 x1,,a\n1 none\n"); },
      "empty button");
  expect_failure(
      [] { swansong::input::parse_script("0 x1,\n1 none\n"); },
      "must not be empty");
  expect_failure(
      [] { swansong::input::parse_script("-1 x1\n1 none\n"); },
      "invalid system cycle");
  expect_failure(
      [] { swansong::input::parse_script("1x x1\n2 none\n"); },
      "invalid system cycle");
  expect_failure(
      [] { swansong::input::parse_script("18446744073709551616 x1\n2 none\n"); },
      "invalid system cycle");
  expect_failure(
      [] { swansong::input::parse_script("0 x1 extra\n1 none\n"); },
      "expected SYSTEM_CYCLE");

  expect_failure(
      [] {
        swansong::input::parse_script(std::string(
            swansong::input::kMaxSourceSizeBytes + 1, ' '));
      },
      "byte limit");

  std::ostringstream too_many_events;
  for (size_t cycle = 0; cycle <= swansong::input::kMaxEvents; ++cycle) {
    too_many_events << cycle << " x1\n";
  }
  expect_failure(
      [&] { swansong::input::parse_script(too_many_events.str()); },
      "event limit");

  return 0;
}
