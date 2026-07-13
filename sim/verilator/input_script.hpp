// SPDX-License-Identifier: GPL-2.0-only
#pragma once

#include <algorithm>
#include <cctype>
#include <cstddef>
#include <cstdint>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace swansong::input {

constexpr const char* kSchema = "swan-song-input-script-v1";
constexpr size_t kMaxSourceSizeBytes = 4u * 1024u * 1024u;
constexpr size_t kMaxEvents = 65'536u;

enum Button : uint16_t {
  X1 = 1u << 0,
  X2 = 1u << 1,
  X3 = 1u << 2,
  X4 = 1u << 3,
  Y1 = 1u << 4,
  Y2 = 1u << 5,
  Y3 = 1u << 6,
  Y4 = 1u << 7,
  Start = 1u << 8,
  A = 1u << 9,
  B = 1u << 10,
};

struct Event {
  uint64_t cycle;
  uint16_t buttons;
};

inline std::string fnv1a64(const std::string& bytes) {
  uint64_t hash = UINT64_C(0xcbf29ce484222325);
  for (const unsigned char byte : bytes) {
    hash ^= byte;
    hash *= UINT64_C(0x100000001b3);
  }
  constexpr char digits[] = "0123456789abcdef";
  std::string result(16, '0');
  for (int index = 15; index >= 0; --index) {
    result[static_cast<size_t>(index)] = digits[hash & 0xf];
    hash >>= 4;
  }
  return result;
}

inline std::string trim(std::string value) {
  const auto not_space = [](unsigned char character) {
    return !std::isspace(character);
  };
  value.erase(value.begin(),
              std::find_if(value.begin(), value.end(), not_space));
  value.erase(std::find_if(value.rbegin(), value.rend(), not_space).base(),
              value.end());
  return value;
}

inline uint64_t parse_cycle(const std::string& text,
                            const std::string& context) {
  if (text.empty() ||
      !std::all_of(text.begin(), text.end(), [](unsigned char character) {
        return std::isdigit(character);
      })) {
    throw std::runtime_error(context + ": invalid system cycle: " + text);
  }
  size_t parsed = 0;
  unsigned long long value = 0;
  try {
    value = std::stoull(text, &parsed, 10);
  } catch (const std::exception&) {
    throw std::runtime_error(context + ": invalid system cycle: " + text);
  }
  if (parsed != text.size()) {
    throw std::runtime_error(context + ": invalid system cycle: " + text);
  }
  return static_cast<uint64_t>(value);
}

inline uint16_t button_mask(const std::string& name,
                            const std::string& context) {
  if (name == "x1") return X1;
  if (name == "x2") return X2;
  if (name == "x3") return X3;
  if (name == "x4") return X4;
  if (name == "y1") return Y1;
  if (name == "y2") return Y2;
  if (name == "y3") return Y3;
  if (name == "y4") return Y4;
  if (name == "start") return Start;
  if (name == "a") return A;
  if (name == "b") return B;
  throw std::runtime_error(context + ": unknown button: " + name);
}

inline uint16_t parse_state(const std::string& text,
                            const std::string& context) {
  if (text == "none") return 0;
  if (text.empty() || text.back() == ',') {
    throw std::runtime_error(context + ": button state must not be empty");
  }
  uint16_t result = 0;
  std::istringstream stream(text);
  std::string token;
  while (std::getline(stream, token, ',')) {
    if (token.empty()) {
      throw std::runtime_error(context + ": empty button name");
    }
    const uint16_t bit = button_mask(token, context);
    if (result & bit) {
      throw std::runtime_error(context + ": duplicate button: " + token);
    }
    result |= bit;
  }
  return result;
}

struct Script {
  std::vector<Event> events;
  size_t source_size_bytes = 0;
  std::string source_fnv1a64;
  std::string normalized_fnv1a64;
};

inline Script parse_script(const std::string& source,
                           const std::string& source_name = "input script") {
  if (source.size() > kMaxSourceSizeBytes) {
    throw std::runtime_error(
        source_name + ": input script exceeds " +
        std::to_string(kMaxSourceSizeBytes) + "-byte limit");
  }
  Script result;
  result.source_size_bytes = source.size();
  result.source_fnv1a64 = fnv1a64(source);

  std::istringstream input(source);
  std::ostringstream normalized;
  std::string line;
  uint32_t line_number = 0;
  bool asserted = false;
  while (std::getline(input, line)) {
    ++line_number;
    const size_t comment = line.find('#');
    if (comment != std::string::npos) line.erase(comment);
    line = trim(line);
    if (line.empty()) continue;

    const std::string context =
        source_name + ":" + std::to_string(line_number);
    std::istringstream fields(line);
    std::string cycle_text;
    std::string state_text;
    std::string extra;
    if (!(fields >> cycle_text >> state_text) || (fields >> extra)) {
      throw std::runtime_error(context + ": expected SYSTEM_CYCLE STATE");
    }
    const uint64_t cycle = parse_cycle(cycle_text, context);
    if (!result.events.empty() && cycle <= result.events.back().cycle) {
      throw std::runtime_error(
          context + ": event cycles must be strictly increasing");
    }
    const uint16_t buttons = parse_state(state_text, context);
    if (result.events.size() >= kMaxEvents) {
      throw std::runtime_error(
          context + ": input script exceeds " + std::to_string(kMaxEvents) +
          "-event limit");
    }
    asserted |= buttons != 0;
    result.events.push_back({cycle, buttons});
    normalized << cycle << ' ' << std::hex << std::setw(4)
               << std::setfill('0') << buttons << std::dec << '\n';
  }
  if (result.events.empty()) {
    throw std::runtime_error(source_name + ": input script has no events");
  }
  if (!asserted) {
    throw std::runtime_error(source_name + ": input script never presses a button");
  }
  if (result.events.back().buttons != 0) {
    throw std::runtime_error(source_name +
                             ": final event must release all buttons with none");
  }
  result.normalized_fnv1a64 = fnv1a64(normalized.str());
  return result;
}

class Replay {
 public:
  explicit Replay(const Script& script) : events_(script.events) {}

  uint16_t state_for_cycle(uint64_t cycle) {
    if (started_ && cycle < last_cycle_) {
      throw std::runtime_error("input replay cycles must not move backwards");
    }
    started_ = true;
    last_cycle_ = cycle;
    while (next_ < events_.size() && events_[next_].cycle <= cycle) {
      state_ = events_[next_].buttons;
      ++next_;
    }
    return state_;
  }

  size_t applied_events() const { return next_; }
  bool completed() const {
    return next_ == events_.size() && state_ == 0;
  }

 private:
  std::vector<Event> events_;
  size_t next_ = 0;
  uint16_t state_ = 0;
  bool started_ = false;
  uint64_t last_cycle_ = 0;
};

template <typename Top>
inline void apply(uint16_t buttons, Top& top) {
  top.KeyX1 = (buttons & X1) != 0;
  top.KeyX2 = (buttons & X2) != 0;
  top.KeyX3 = (buttons & X3) != 0;
  top.KeyX4 = (buttons & X4) != 0;
  top.KeyY1 = (buttons & Y1) != 0;
  top.KeyY2 = (buttons & Y2) != 0;
  top.KeyY3 = (buttons & Y3) != 0;
  top.KeyY4 = (buttons & Y4) != 0;
  top.KeyStart = (buttons & Start) != 0;
  top.KeyA = (buttons & A) != 0;
  top.KeyB = (buttons & B) != 0;
}

}  // namespace swansong::input
