// SPDX-License-Identifier: GPL-2.0-only
#pragma once

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <ios>
#include <memory>
#include <optional>
#include <ostream>
#include <sstream>
#include <stdexcept>
#include <string>

namespace swansong::trace {

enum class EventType : uint8_t { Cpu = 1, Bank = 2, Vram = 4 };
enum class Format { Auto, Csv, Jsonl };

struct PcRange {
  uint32_t first;
  uint32_t last;

  bool contains(uint32_t pc) const { return pc >= first && pc <= last; }
};

struct Config {
  std::filesystem::path output;
  uint8_t events = static_cast<uint8_t>(EventType::Cpu) |
                   static_cast<uint8_t>(EventType::Bank) |
                   static_cast<uint8_t>(EventType::Vram);
  std::optional<PcRange> cpu_pc;
  Format format = Format::Auto;

  bool enabled() const { return !output.empty(); }
  bool includes(EventType type) const {
    return (events & static_cast<uint8_t>(type)) != 0;
  }
};

inline std::string trim(std::string value) {
  const auto not_space = [](unsigned char c) { return !std::isspace(c); };
  value.erase(value.begin(),
              std::find_if(value.begin(), value.end(), not_space));
  value.erase(std::find_if(value.rbegin(), value.rend(), not_space).base(),
              value.end());
  return value;
}

inline std::string lower(std::string value) {
  std::transform(value.begin(), value.end(), value.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  return value;
}

inline uint32_t parse_number(const std::string& text, uint32_t maximum,
                             const char* description) {
  const std::string value = trim(text);
  if (value.empty() || value.front() == '-') {
    throw std::runtime_error(std::string("invalid ") + description + ": " + text);
  }
  size_t parsed = 0;
  unsigned long long number = 0;
  try {
    number = std::stoull(value, &parsed, 0);
  } catch (const std::exception&) {
    throw std::runtime_error(std::string("invalid ") + description + ": " + text);
  }
  if (parsed != value.size() || number > maximum) {
    throw std::runtime_error(std::string("invalid ") + description + ": " + text);
  }
  return static_cast<uint32_t>(number);
}

inline PcRange parse_pc_range(const std::string& text) {
  const size_t separator = text.find('-');
  if (separator == std::string::npos || text.find('-', separator + 1) != std::string::npos) {
    throw std::runtime_error("CPU PC range must be START-END: " + text);
  }
  PcRange range{parse_number(text.substr(0, separator), 0x0f'ffff, "CPU PC"),
                parse_number(text.substr(separator + 1), 0x0f'ffff, "CPU PC")};
  if (range.first > range.last) {
    throw std::runtime_error("CPU PC range start exceeds end: " + text);
  }
  return range;
}

inline uint8_t parse_events(const std::string& text) {
  uint8_t result = 0;
  std::istringstream stream(text);
  std::string token;
  while (std::getline(stream, token, ',')) {
    token = lower(trim(token));
    if (token == "all") {
      result |= static_cast<uint8_t>(EventType::Cpu) |
                static_cast<uint8_t>(EventType::Bank) |
                static_cast<uint8_t>(EventType::Vram);
    } else if (token == "cpu") {
      result |= static_cast<uint8_t>(EventType::Cpu);
    } else if (token == "bank") {
      result |= static_cast<uint8_t>(EventType::Bank);
    } else if (token == "vram") {
      result |= static_cast<uint8_t>(EventType::Vram);
    } else {
      throw std::runtime_error("unknown trace event type: " + token);
    }
  }
  if (result == 0) throw std::runtime_error("trace event list must not be empty");
  return result;
}

inline Format parse_format(const std::string& text) {
  const std::string value = lower(trim(text));
  if (value == "auto") return Format::Auto;
  if (value == "csv") return Format::Csv;
  if (value == "jsonl") return Format::Jsonl;
  throw std::runtime_error("trace format must be csv or jsonl: " + text);
}

inline void parse_config(std::istream& input, Config& config,
                         const std::string& source = "trace config") {
  std::string line;
  unsigned line_number = 0;
  while (std::getline(input, line)) {
    ++line_number;
    const size_t comment = line.find('#');
    if (comment != std::string::npos) line.erase(comment);
    line = trim(line);
    if (line.empty()) continue;
    const size_t separator = line.find('=');
    if (separator == std::string::npos) {
      throw std::runtime_error(source + ":" + std::to_string(line_number) +
                               ": expected KEY=VALUE");
    }
    const std::string key = lower(trim(line.substr(0, separator)));
    const std::string value = trim(line.substr(separator + 1));
    try {
      if (key == "output") config.output = value;
      else if (key == "events") config.events = parse_events(value);
      else if (key == "cpu_pc") config.cpu_pc = parse_pc_range(value);
      else if (key == "format") config.format = parse_format(value);
      else throw std::runtime_error("unknown key: " + key);
    } catch (const std::exception& error) {
      throw std::runtime_error(source + ":" + std::to_string(line_number) +
                               ": " + error.what());
    }
  }
}

inline void parse_config_file(const std::filesystem::path& path, Config& config) {
  std::ifstream input(path);
  if (!input) throw std::runtime_error("cannot open trace config " + path.string());
  parse_config(input, config, path.string());
}

inline Format resolved_format(const Config& config) {
  if (config.format != Format::Auto) return config.format;
  const std::string extension = lower(config.output.extension().string());
  return (extension == ".jsonl" || extension == ".ndjson") ? Format::Jsonl
                                                              : Format::Csv;
}

struct Event {
  uint64_t cycle;
  EventType type;
  std::optional<uint32_t> physical_pc;
  std::optional<uint32_t> cs;
  std::optional<uint32_t> ip;
  std::optional<uint32_t> address;
  std::optional<uint32_t> value;
};

inline const char* event_name(EventType type) {
  switch (type) {
    case EventType::Cpu: return "cpu";
    case EventType::Bank: return "bank";
    case EventType::Vram: return "vram";
  }
  return "unknown";
}

class Writer {
 public:
  Writer(std::ostream& output, Format format) : output_(output), format_(format) {
    if (format_ == Format::Csv) {
      output_ << "cycle,event,physical_pc,cs,ip,address,value\n";
    }
  }

  void write(const Event& event) {
    if (format_ == Format::Csv) write_csv(event);
    else write_jsonl(event);
    if (!output_) throw std::runtime_error("failed to write structured trace");
  }

 private:
  static void csv_optional(std::ostream& output,
                           const std::optional<uint32_t>& value) {
    if (value) output << *value;
  }

  static void json_optional(std::ostream& output, const char* key,
                            const std::optional<uint32_t>& value) {
    output << ",\"" << key << "\":";
    if (value) output << *value;
    else output << "null";
  }

  void write_csv(const Event& event) {
    output_ << event.cycle << ',' << event_name(event.type) << ',';
    csv_optional(output_, event.physical_pc);
    output_ << ',';
    csv_optional(output_, event.cs);
    output_ << ',';
    csv_optional(output_, event.ip);
    output_ << ',';
    csv_optional(output_, event.address);
    output_ << ',';
    csv_optional(output_, event.value);
    output_ << '\n';
  }

  void write_jsonl(const Event& event) {
    output_ << "{\"cycle\":" << event.cycle << ",\"event\":\""
            << event_name(event.type) << '"';
    json_optional(output_, "physical_pc", event.physical_pc);
    json_optional(output_, "cs", event.cs);
    json_optional(output_, "ip", event.ip);
    json_optional(output_, "address", event.address);
    json_optional(output_, "value", event.value);
    output_ << "}\n";
  }

  std::ostream& output_;
  Format format_;
};

class Logger {
 public:
  explicit Logger(const Config& config) : config_(config) {
    if (!config_.enabled()) throw std::runtime_error("trace output path is empty");
    if (config_.output.has_parent_path()) {
      std::filesystem::create_directories(config_.output.parent_path());
    }
    output_.open(config_.output, std::ios::out | std::ios::trunc);
    if (!output_) throw std::runtime_error("cannot write " + config_.output.string());
    writer_ = std::make_unique<Writer>(output_, resolved_format(config_));
  }

  void cpu(uint64_t cycle, uint32_t physical_pc, uint16_t cs, uint16_t ip) {
    if (!config_.includes(EventType::Cpu)) return;
    if (config_.cpu_pc && !config_.cpu_pc->contains(physical_pc)) return;
    writer_->write({cycle, EventType::Cpu, physical_pc, cs, ip,
                    std::nullopt, std::nullopt});
  }

  void bank(uint64_t cycle, uint8_t address, uint8_t value) {
    if (!config_.includes(EventType::Bank)) return;
    writer_->write({cycle, EventType::Bank, std::nullopt, std::nullopt,
                    std::nullopt, address, value});
  }

  void vram(uint64_t cycle, uint16_t address) {
    if (!config_.includes(EventType::Vram)) return;
    writer_->write({cycle, EventType::Vram, std::nullopt, std::nullopt,
                    std::nullopt, address, std::nullopt});
  }

 private:
  Config config_;
  std::ofstream output_;
  std::unique_ptr<Writer> writer_;
};

}  // namespace swansong::trace
