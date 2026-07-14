`timescale 1ns/1ps
`default_nettype none

module apf_savestate_v2_layout_tb;
  import apf_savestate_v2_layout_pkg::*;

  integer unsigned failures;
  integer unsigned index;
  integer unsigned fixed_payload_zero_count;
  integer unsigned fixed_header_zero_count;
  integer unsigned profile_zero_count;
  logic [31:0] identity;

  task automatic check(input logic condition, input string message);
    if (!condition) begin
      $display("FAIL %s", message);
      failures = failures + 1;
    end
  endtask

  task automatic count_profile_zero_bytes(
      input logic [7:0] model,
      input logic [7:0] ramtype,
      input logic [31:0] flags,
      output integer unsigned count
  );
    integer unsigned offset;
    begin
      count = 0;
      for (offset = 0; offset < V2_PAYLOAD_BYTES; offset = offset + 1)
        if (v2_payload_byte_requires_zero(offset, model, ramtype, flags))
          count = count + 1;
    end
  endtask

  initial begin
    failures = 0;

    check(V2_HEADER_BYTES == 32'h100, "header size");
    check(V2_PAYLOAD_BYTES == 32'h120000, "payload size");
    check(V2_TOTAL_BYTES == 32'h120100, "total size");
    check(V2_TOTAL_BYTES == V2_HEADER_BYTES + V2_PAYLOAD_BYTES,
          "header plus payload");
    check(V2_BRIDGE_WORDS * 4 == V2_TOTAL_BYTES, "bridge word count");

    // The top-level payload is contiguous and ends exactly at 0x120000.
    check(P_MACHINE == 0, "machine base");
    check(P_MACHINE + P_MACHINE_BYTES == P_PPU, "machine to PPU");
    check(P_PPU + P_PPU_BYTES == P_APU, "PPU to APU");
    check(P_APU + P_APU_BYTES == P_IO, "APU to I/O");
    check(P_IO + P_IO_BYTES == P_INTERNAL_EEPROM, "I/O to internal EEPROM");
    check(P_INTERNAL_EEPROM + P_INTERNAL_EEPROM_BYTES == P_CART_EEPROM,
          "internal to cart EEPROM");
    check(P_CART_EEPROM + P_CART_EEPROM_BYTES == P_RESERVE0,
          "cart EEPROM to reserve");
    check(P_RESERVE0 + P_RESERVE0_BYTES == P_IRAM, "reserve to IRAM");
    check(P_IRAM + P_IRAM_BYTES == P_SRAM, "IRAM to SRAM");
    check(P_SRAM + P_SRAM_BYTES == P_FLASH, "SRAM to flash");
    check(P_FLASH + P_FLASH_BYTES == V2_PAYLOAD_BYTES, "payload end");

    // Component subdivisions are also exact and gap-free through their
    // reserved tails.
    check(P_DIRECTORY + P_DIRECTORY_BYTES == P_CPU, "directory to CPU");
    check(P_CPU + P_CPU_BYTES == P_IRQ_INPUT_SERIAL, "CPU to IRQ/input");
    check(P_IRQ_INPUT_SERIAL + P_IRQ_INPUT_SERIAL_BYTES == P_DMA,
          "IRQ/input to DMA");
    check(P_DMA + P_DMA_BYTES == P_SCHEDULER, "DMA to scheduler");
    check(P_SCHEDULER + P_SCHEDULER_BYTES == P_MAPPER_CART,
          "scheduler to mapper");
    check(P_MAPPER_CART + P_MAPPER_CART_BYTES == P_RTC, "mapper to RTC");
    check(P_RTC + P_RTC_BYTES == P_INTERNAL_EEPROM_CTRL,
          "RTC to internal EEPROM controller");
    check(P_INTERNAL_EEPROM_CTRL + P_INTERNAL_EEPROM_CTRL_BYTES ==
          P_CART_EEPROM_CTRL, "EEPROM controller adjacency");
    check(P_CART_EEPROM_CTRL + P_CART_EEPROM_CTRL_BYTES == P_MACHINE_RESERVE,
          "controller to machine reserve");
    check(P_MACHINE_RESERVE + P_MACHINE_RESERVE_BYTES == P_PPU,
          "machine reserve end");
    check(P_PPU_RESERVE + P_PPU_RESERVE_BYTES == P_APU, "PPU reserve end");
    check(P_APU_RESERVE + P_APU_RESERVE_BYTES == P_IO, "APU reserve end");

    // Header compound fields and CRC coverage neither overlap nor escape.
    check(H_ROM_FOOTER + H_ROM_FOOTER_BYTES == H_ABI_ID, "footer to ABI ID");
    check(H_ABI_ID + H_ABI_ID_BYTES == H_CPU_SCHEMA, "ABI ID to schemas");
    check(H_RESERVED_TAIL + H_RESERVED_TAIL_BYTES == H_HEADER_CRC64,
          "header reserved tail");
    check(H_HEADER_CRC64 + 8 == V2_HEADER_BYTES, "header CRC end");
    check(H_HEADER_CRC_INPUT_BYTES == H_HEADER_CRC64, "header CRC coverage");
    check(V2_ABI_ID == 128'h5357_414e_534f_4e47_2d53_5441_5445_3200,
          "ABI ID bytes");
    check(V2_CPU_SCHEMA == 1 && V2_PPU_SCHEMA == 1 &&
          V2_APU_SCHEMA == 1 && V2_DEVICE_SCHEMA == 1,
          "component schemas");
    check(V2_SETTINGS_ALLOWED == 32'h0000_1fff,
          "13-bit settings snapshot mask");
    check(V2_SETTINGS_HARD_MATCH == 32'h0000_0400,
          "CPU-turbo settings hard-match bit");

    // The v1 tuple and every individual v1 length/version are unambiguously
    // rejected by the v2 static gate.
    check(v2_static_header_valid(V2_MAGIC, V2_ENVELOPE_VERSION,
          V2_HEADER_BYTES, V2_PAYLOAD_BYTES, V2_TOTAL_BYTES, V2_FORMAT_ID),
          "v2 static identity accepted");
    check(!v2_static_header_valid(V2_MAGIC, V1_ENVELOPE_VERSION,
          V1_HEADER_BYTES, V1_PAYLOAD_BYTES, V1_TOTAL_BYTES, V1_FORMAT_ID),
          "v1 tuple rejected");
    check(!v2_static_header_valid(V2_MAGIC, V1_ENVELOPE_VERSION,
          V2_HEADER_BYTES, V2_PAYLOAD_BYTES, V2_TOTAL_BYTES, V2_FORMAT_ID),
          "v1 envelope version rejected");
    check(!v2_static_header_valid(V2_MAGIC, V2_ENVELOPE_VERSION,
          V1_HEADER_BYTES, V2_PAYLOAD_BYTES, V2_TOTAL_BYTES, V2_FORMAT_ID),
          "v1 header size rejected");
    check(!v2_static_header_valid(V2_MAGIC, V2_ENVELOPE_VERSION,
          V2_HEADER_BYTES, V1_PAYLOAD_BYTES, V2_TOTAL_BYTES, V2_FORMAT_ID),
          "v1 payload size rejected");
    check(!v2_static_header_valid(V2_MAGIC, V2_ENVELOPE_VERSION,
          V2_HEADER_BYTES, V2_PAYLOAD_BYTES, V1_TOTAL_BYTES, V2_FORMAT_ID),
          "v1 total size rejected");
    check(!v2_static_header_valid(V2_MAGIC, V2_ENVELOPE_VERSION,
          V2_HEADER_BYTES, V2_PAYLOAD_BYTES, V2_TOTAL_BYTES, V1_FORMAT_ID),
          "v1 format rejected");

    // Identity/feature mask and cross-field rules.
    identity = {V2_MODEL_MONO, V2_MAPPER_2001, V2_RAM_NONE, V2_BIOS_MONO};
    check(v2_feature_identity_valid(0, identity), "mono identity accepted");
    identity = {V2_MODEL_COLOR, V2_MAPPER_2003,
                V2_RAM_EEPROM_2K, V2_BIOS_COLOR};
    check(v2_feature_identity_valid(V2_FEATURE_COLOR |
          V2_FEATURE_CART_EEPROM | V2_FEATURE_CART_RTC |
          V2_FEATURE_WALLCLOCK_VALID | V2_FEATURE_FLASH, identity),
          "Color mapper/RTC/flash identity accepted");
    check(!v2_feature_identity_valid(32'h40, identity),
          "unknown feature bit rejected");
    check(!v2_feature_identity_valid(V2_FEATURE_COLOR |
          V2_FEATURE_SRAM | V2_FEATURE_CART_EEPROM, identity),
          "SRAM plus EEPROM rejected");
    check(!v2_feature_identity_valid(V2_FEATURE_COLOR |
          V2_FEATURE_WALLCLOCK_VALID, identity),
          "wall clock without RTC rejected");
    identity = {V2_MODEL_COLOR, V2_MAPPER_2001,
                V2_RAM_NONE, V2_BIOS_COLOR};
    check(!v2_feature_identity_valid(V2_FEATURE_COLOR | V2_FEATURE_FLASH,
          identity), "flash on mapper 2001 rejected");
    check(!v2_feature_identity_valid(V2_FEATURE_COLOR |
          V2_FEATURE_CART_RTC, identity),
          "RTC on mapper 2001 rejected");
    identity = {V2_MODEL_COLOR, V2_MAPPER_2003,
                V2_RAM_NONE, V2_BIOS_COLOR};
    check(!v2_feature_identity_valid(V2_FEATURE_COLOR, identity),
          "mapper 2003 without RTC rejected");
    identity = {V2_MODEL_MONO, V2_MAPPER_2001,
                V2_RAM_NONE, V2_BIOS_MONO};
    check(!v2_feature_identity_valid(V2_FEATURE_COLOR, identity),
          "Color flag/model mismatch rejected");
    identity = {V2_MODEL_MONO, V2_MAPPER_2001,
                V2_RAM_SRAM_32K_A, V2_BIOS_MONO};
    check(!v2_feature_identity_valid(0, identity),
          "SRAM RAM-type without feature rejected");
    check(v2_feature_identity_valid(V2_FEATURE_SRAM, identity),
          "SRAM RAM-type with feature accepted");
    identity = {V2_MODEL_MONO, V2_MAPPER_2001,
                V2_RAM_NONE, V2_BIOS_MONO};
    check(!v2_feature_identity_valid(V2_FEATURE_SRAM, identity),
          "extra SRAM feature rejected");
    check(!v2_feature_identity_valid(V2_FEATURE_CART_EEPROM, identity),
          "extra cart-EEPROM feature rejected");
    identity = {V2_MODEL_COLOR, V2_MAPPER_2001,
                V2_RAM_EEPROM_128, V2_BIOS_COLOR};
    check(!v2_feature_identity_valid(V2_FEATURE_COLOR, identity),
          "cart-EEPROM RAM-type without feature rejected");
    check(v2_feature_identity_valid(V2_FEATURE_COLOR |
          V2_FEATURE_CART_EEPROM, identity),
          "cart-EEPROM RAM-type with feature accepted");
    identity = {V2_MODEL_COLOR, V2_MAPPER_2003,
                8'hff, V2_BIOS_COLOR};
    check(!v2_feature_identity_valid(V2_FEATURE_COLOR, identity),
          "unknown RAM type rejected");

    // Active-size tables freeze every supported footer RAM type.
    check(v2_expected_sram_bytes(V2_RAM_NONE) == 0, "no SRAM");
    check(v2_expected_sram_bytes(V2_RAM_SRAM_32K_A) == 32'h8000,
          "SRAM type 01");
    check(v2_expected_sram_bytes(V2_RAM_SRAM_32K_B) == 32'h8000,
          "SRAM type 02");
    check(v2_expected_sram_bytes(V2_RAM_SRAM_128K) == 32'h20000,
          "SRAM type 03");
    check(v2_expected_sram_bytes(V2_RAM_SRAM_256K) == 32'h40000,
          "SRAM type 04");
    check(v2_expected_sram_bytes(V2_RAM_SRAM_512K) == 32'h80000,
          "SRAM type 05");
    check(v2_expected_cart_eeprom_bytes(V2_RAM_EEPROM_128) == 32'h80,
          "EEPROM type 10");
    check(v2_expected_cart_eeprom_bytes(V2_RAM_EEPROM_2K) == 32'h800,
          "EEPROM type 20");
    check(v2_expected_cart_eeprom_bytes(V2_RAM_EEPROM_1K) == 32'h400,
          "EEPROM type 50");

    identity = {V2_MODEL_MONO, V2_MAPPER_2001,
                V2_RAM_NONE, V2_BIOS_MONO};
    check(v2_active_sizes_valid(0, identity, V2_MONO_IRAM_BYTES, 0, 0,
          V2_MONO_INTERNAL_BYTES, 0), "mono active sizes accepted");
    check(!v2_active_sizes_valid(0, identity, V2_COLOR_IRAM_BYTES, 0, 0,
          V2_MONO_INTERNAL_BYTES, 0), "wrong mono IRAM size rejected");
    check(!v2_active_sizes_valid(0, identity, V2_MONO_IRAM_BYTES, 0, 0,
          V2_COLOR_INTERNAL_BYTES, 0),
          "wrong mono internal EEPROM size rejected");
    identity = {V2_MODEL_COLOR, V2_MAPPER_2001,
                V2_RAM_SRAM_512K, V2_BIOS_COLOR};
    check(v2_active_sizes_valid(V2_FEATURE_COLOR | V2_FEATURE_SRAM,
          identity, V2_COLOR_IRAM_BYTES, P_SRAM_BYTES, 0,
          V2_COLOR_INTERNAL_BYTES, 0), "Color SRAM active sizes accepted");
    check(!v2_active_sizes_valid(V2_FEATURE_COLOR | V2_FEATURE_SRAM,
          identity, V2_COLOR_IRAM_BYTES, P_SRAM_BYTES - 1, 0,
          V2_COLOR_INTERNAL_BYTES, 0), "short SRAM size rejected");
    identity = {V2_MODEL_COLOR, V2_MAPPER_2003,
                V2_RAM_EEPROM_2K, V2_BIOS_COLOR};
    check(v2_active_sizes_valid(V2_FEATURE_COLOR |
          V2_FEATURE_CART_EEPROM | V2_FEATURE_CART_RTC |
          V2_FEATURE_FLASH, identity,
          V2_COLOR_IRAM_BYTES, 0, P_CART_EEPROM_BYTES,
          V2_COLOR_INTERNAL_BYTES, V2_FLASH_ACTIVE_BYTES),
          "Color EEPROM/flash active sizes accepted");
    check(!v2_active_sizes_valid(V2_FEATURE_COLOR |
          V2_FEATURE_CART_EEPROM | V2_FEATURE_CART_RTC |
          V2_FEATURE_FLASH, identity,
          V2_COLOR_IRAM_BYTES, 0, P_CART_EEPROM_BYTES,
          V2_COLOR_INTERNAL_BYTES, 0), "missing flash size rejected");

    // Fixed zero-padding byte ranges are exhaustive and boundary exact.
    fixed_payload_zero_count = 0;
    for (index = 0; index < V2_PAYLOAD_BYTES; index = index + 1)
      if (v2_fixed_zero_payload_byte(index))
        fixed_payload_zero_count = fixed_payload_zero_count + 1;
    check(fixed_payload_zero_count == 32'h9d00,
          "fixed payload zero-byte count");
    check(!v2_fixed_zero_payload_byte(P_MACHINE_RESERVE - 1),
          "machine padding lower boundary");
    check(v2_fixed_zero_payload_byte(P_MACHINE_RESERVE),
          "machine padding begins");
    check(v2_fixed_zero_payload_byte(P_IO + P_IO_ACTIVE_BYTES),
          "I/O padding begins");
    check(!v2_fixed_zero_payload_byte(P_IRAM), "IRAM is not fixed padding");
    check(!v2_fixed_zero_payload_byte(V2_PAYLOAD_BYTES),
          "outside payload is not padding");

    // Model/title-dependent zero rules add inactive EEPROM, mono-IRAM, SRAM
    // tail, and absent flash without overlapping the permanent reserve ranges.
    count_profile_zero_bytes(V2_MODEL_MONO, V2_RAM_NONE, 0,
                             profile_zero_count);
    check(profile_zero_count == fixed_payload_zero_count +
          (P_INTERNAL_EEPROM_BYTES - V2_MONO_INTERNAL_BYTES) +
          P_CART_EEPROM_BYTES +
          (P_IRAM_BYTES - V2_MONO_IRAM_BYTES) +
          P_SRAM_BYTES + P_FLASH_BYTES,
          "mono/no-cart complete zero-byte count");
    check(!v2_payload_byte_requires_zero(P_INTERNAL_MONO, V2_MODEL_MONO,
          V2_RAM_NONE, 0), "mono internal slice active");
    check(v2_payload_byte_requires_zero(P_INTERNAL_COLOR, V2_MODEL_MONO,
          V2_RAM_NONE, 0), "inactive Color internal slice zero");
    check(v2_payload_byte_requires_zero(P_IRAM + V2_MONO_IRAM_BYTES,
          V2_MODEL_MONO, V2_RAM_NONE, 0), "mono IRAM tail zero");

    count_profile_zero_bytes(V2_MODEL_COLOR, V2_RAM_SRAM_512K,
                             V2_FEATURE_COLOR | V2_FEATURE_SRAM,
                             profile_zero_count);
    check(profile_zero_count == fixed_payload_zero_count +
          (P_INTERNAL_EEPROM_BYTES - V2_COLOR_INTERNAL_BYTES) +
          P_CART_EEPROM_BYTES + P_FLASH_BYTES,
          "Color/512K-SRAM complete zero-byte count");
    check(!v2_payload_byte_requires_zero(P_SRAM + P_SRAM_BYTES - 1,
          V2_MODEL_COLOR, V2_RAM_SRAM_512K,
          V2_FEATURE_COLOR | V2_FEATURE_SRAM),
          "active 512K SRAM final byte not padding");
    check(v2_payload_byte_requires_zero(P_FLASH, V2_MODEL_COLOR,
          V2_RAM_SRAM_512K, V2_FEATURE_COLOR | V2_FEATURE_SRAM),
          "absent flash zero");

    count_profile_zero_bytes(V2_MODEL_COLOR, V2_RAM_EEPROM_2K,
                             V2_FEATURE_COLOR | V2_FEATURE_CART_EEPROM |
                             V2_FEATURE_FLASH, profile_zero_count);
    check(profile_zero_count == fixed_payload_zero_count +
          (P_INTERNAL_EEPROM_BYTES - V2_COLOR_INTERNAL_BYTES) +
          P_SRAM_BYTES,
          "Color/2K-EEPROM/flash complete zero-byte count");
    check(!v2_payload_byte_requires_zero(P_CART_EEPROM +
          P_CART_EEPROM_BYTES - 1, V2_MODEL_COLOR, V2_RAM_EEPROM_2K,
          V2_FEATURE_COLOR | V2_FEATURE_CART_EEPROM | V2_FEATURE_FLASH),
          "active cart EEPROM final byte not padding");
    check(!v2_payload_byte_requires_zero(P_FLASH, V2_MODEL_COLOR,
          V2_RAM_EEPROM_2K,
          V2_FEATURE_COLOR | V2_FEATURE_CART_EEPROM | V2_FEATURE_FLASH),
          "active flash not padding");

    fixed_header_zero_count = 0;
    for (index = 0; index < V2_HEADER_BYTES; index = index + 1)
      if (v2_fixed_zero_header_byte(index))
        fixed_header_zero_count = fixed_header_zero_count + 1;
    check(fixed_header_zero_count == 32'h50,
          "fixed header zero-byte count");
    check(v2_fixed_zero_header_byte(H_RESERVED_ZERO),
          "reserved header word begins");
    check(v2_fixed_zero_header_byte(H_HEADER_CRC64 - 1),
          "reserved header tail ends");
    check(!v2_fixed_zero_header_byte(H_HEADER_CRC64),
          "header CRC is not padding");

    // Physical and APF address bounds are inclusive and exact.
    check(V2_BRIDGE_LAST - V2_BRIDGE_BASE + 1 == V2_TOTAL_BYTES,
          "bridge address range");
    check(V2_STAGE_LAST - V2_STAGE_BASE + 1 == V2_STAGE_BYTES,
          "staging byte range");
    check((V2_STAGE_X16_LAST - V2_STAGE_X16_BASE + 1) * 2 ==
          V2_STAGE_BYTES, "staging x16 range");
    check(V2_GUARD_BASE == V2_CART_SRAM_LAST + 1, "guard starts after SRAM");
    check(V2_STAGE_BASE == V2_GUARD_LAST + 1, "staging starts after guard");

    if (failures != 0)
      $fatal(1, "APF savestate v2 layout failures=%0d", failures);

    $display("PASS APF savestate v2 layout total=0x%0x payload=0x%0x fixed_zero=0x%0x",
             V2_TOTAL_BYTES, V2_PAYLOAD_BYTES, fixed_payload_zero_count);
    $finish;
  end
endmodule

`default_nettype wire
