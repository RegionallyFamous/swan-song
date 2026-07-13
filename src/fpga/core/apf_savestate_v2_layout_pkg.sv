`default_nettype none

// Fixed binary ABI for the future production WonderSwan Memories v2 image.
//
// This package is deliberately not in ap_core.qsf and does not enable the
// Pocket save-state flags.  It freezes sizes, offsets, identities, and padding
// rules for the v2 implementation without changing the isolated v1 transport.
// Structured scalar bytes are big-endian at the APF bridge: the byte at the
// lowest blob offset occupies bits [31:24] of a normalized 32-bit word.  Raw
// emulated memories are byte arrays in ascending emulated-address order.
package apf_savestate_v2_layout_pkg;
  // Envelope identity and exact lengths.
  localparam logic [31:0] V2_MAGIC              = 32'h5357_414e; // "SWAN"
  localparam logic [31:0] V2_ENVELOPE_VERSION   = 32'd2;
  localparam logic [31:0] V2_HEADER_BYTES       = 32'h0000_0100;
  localparam logic [31:0] V2_PAYLOAD_BYTES      = 32'h0012_0000;
  localparam logic [31:0] V2_TOTAL_BYTES        = 32'h0012_0100;
  localparam logic [31:0] V2_FORMAT_ID          = 32'h5753_0002;
  localparam logic [31:0] V2_BRIDGE_WORDS       = 32'h0004_8040;

  // The isolated v1 experiment is intentionally not a migration source.
  localparam logic [31:0] V1_ENVELOPE_VERSION   = 32'd1;
  localparam logic [31:0] V1_HEADER_BYTES       = 32'h0000_0020;
  localparam logic [31:0] V1_PAYLOAD_BYTES      = 32'h0009_0300;
  localparam logic [31:0] V1_TOTAL_BYTES        = 32'h0009_0320;
  localparam logic [31:0] V1_FORMAT_ID          = 32'h5753_0001;

  // Header byte offsets.  The CRC at 0xf8 covers bytes 0x00 through 0xf7.
  localparam logic [31:0] H_MAGIC                = 32'h0000_0000;
  localparam logic [31:0] H_ENVELOPE_VERSION     = 32'h0000_0004;
  localparam logic [31:0] H_HEADER_BYTES         = 32'h0000_0008;
  localparam logic [31:0] H_PAYLOAD_BYTES        = 32'h0000_000c;
  localparam logic [31:0] H_TOTAL_BYTES          = 32'h0000_0010;
  localparam logic [31:0] H_FORMAT_ID            = 32'h0000_0014;
  localparam logic [31:0] H_FEATURE_FLAGS        = 32'h0000_0018;
  localparam logic [31:0] H_RESERVED_ZERO        = 32'h0000_001c;
  localparam logic [31:0] H_ROM_BYTES            = 32'h0000_0020;
  localparam logic [31:0] H_MACHINE_IDENTITY     = 32'h0000_0024;
  localparam logic [31:0] H_SETTINGS_MATCH_MASK  = 32'h0000_0028;
  localparam logic [31:0] H_SETTINGS_SNAPSHOT    = 32'h0000_002c;
  localparam logic [31:0] H_ROM_CRC64            = 32'h0000_0030;
  localparam logic [31:0] H_ACTIVE_BIOS_CRC64    = 32'h0000_0038;
  localparam logic [31:0] H_MONO_BIOS_CRC64      = 32'h0000_0040;
  localparam logic [31:0] H_COLOR_BIOS_CRC64     = 32'h0000_0048;
  localparam logic [31:0] H_CAPTURE_EPOCH        = 32'h0000_0050;
  localparam logic [31:0] H_PAYLOAD_CRC64        = 32'h0000_0058;
  localparam logic [31:0] H_ACTIVE_IRAM_BYTES    = 32'h0000_0060;
  localparam logic [31:0] H_ACTIVE_SRAM_BYTES    = 32'h0000_0064;
  localparam logic [31:0] H_CART_EEPROM_BYTES    = 32'h0000_0068;
  localparam logic [31:0] H_INTERNAL_EEPROM_BYTES = 32'h0000_006c;
  localparam logic [31:0] H_FLASH_BYTES          = 32'h0000_0070;
  localparam logic [31:0] H_ROM_FOOTER            = 32'h0000_0074;
  localparam logic [31:0] H_ROM_FOOTER_BYTES      = 32'h0000_0010;
  localparam logic [31:0] H_ABI_ID                = 32'h0000_0084;
  localparam logic [31:0] H_ABI_ID_BYTES          = 32'h0000_0010;
  localparam logic [31:0] H_CPU_SCHEMA            = 32'h0000_0094;
  localparam logic [31:0] H_PPU_SCHEMA            = 32'h0000_0098;
  localparam logic [31:0] H_APU_SCHEMA            = 32'h0000_009c;
  localparam logic [31:0] H_DEVICE_SCHEMA         = 32'h0000_00a0;
  localparam logic [31:0] H_CAPTURE_POLICY        = 32'h0000_00a4;
  localparam logic [31:0] H_RTC_POLICY            = 32'h0000_00a8;
  localparam logic [31:0] H_RESERVED_TAIL         = 32'h0000_00ac;
  localparam logic [31:0] H_RESERVED_TAIL_BYTES   = 32'h0000_004c;
  localparam logic [31:0] H_HEADER_CRC64          = 32'h0000_00f8;
  localparam logic [31:0] H_HEADER_CRC_INPUT_BYTES = 32'h0000_00f8;

  // Exact ABI/schema/policy identities.
  localparam logic [127:0] V2_ABI_ID =
      128'h5357_414e_534f_4e47_2d53_5441_5445_3200; // "SWANSONG-STATE2\0"
  localparam logic [31:0] V2_CPU_SCHEMA      = 32'd1;
  localparam logic [31:0] V2_PPU_SCHEMA      = 32'd1;
  localparam logic [31:0] V2_APU_SCHEMA      = 32'd1;
  localparam logic [31:0] V2_DEVICE_SCHEMA   = 32'd1;
  localparam logic [31:0] V2_CAPTURE_POLICY  = 32'd1;
  localparam logic [31:0] V2_RTC_EXACT       = 32'd0;
  localparam logic [31:0] V2_RTC_ADVANCE     = 32'd1;

  // Feature flags.  Every bit outside V2_FEATURE_ALLOWED must be zero.
  localparam logic [31:0] V2_FEATURE_SRAM             = 32'h0000_0001;
  localparam logic [31:0] V2_FEATURE_CART_EEPROM      = 32'h0000_0002;
  localparam logic [31:0] V2_FEATURE_CART_RTC         = 32'h0000_0004;
  localparam logic [31:0] V2_FEATURE_FLASH            = 32'h0000_0008;
  localparam logic [31:0] V2_FEATURE_COLOR            = 32'h0000_0010;
  localparam logic [31:0] V2_FEATURE_WALLCLOCK_VALID  = 32'h0000_0020;
  localparam logic [31:0] V2_FEATURE_ALLOWED          = 32'h0000_003f;

  // H_MACHINE_IDENTITY bytes are {model, mapper, ramtype, active_bios}.
  localparam logic [7:0] V2_MODEL_MONO        = 8'd0;
  localparam logic [7:0] V2_MODEL_COLOR       = 8'd1;
  localparam logic [7:0] V2_MAPPER_2001       = 8'd0;
  localparam logic [7:0] V2_MAPPER_2003       = 8'd1;
  localparam logic [7:0] V2_BIOS_MONO         = 8'd0;
  localparam logic [7:0] V2_BIOS_COLOR        = 8'd1;

  // The current 11-bit settings package has only CPU turbo as a hard match.
  localparam logic [31:0] V2_SETTINGS_ALLOWED     = 32'h0000_07ff;
  localparam logic [31:0] V2_SETTINGS_HARD_MATCH  = 32'h0000_0100;

  // Fixed top-level payload regions.
  localparam logic [31:0] P_MACHINE             = 32'h0000_0000;
  localparam logic [31:0] P_MACHINE_BYTES       = 32'h0000_4000;
  localparam logic [31:0] P_PPU                 = 32'h0000_4000;
  localparam logic [31:0] P_PPU_BYTES           = 32'h0000_4000;
  localparam logic [31:0] P_APU                 = 32'h0000_8000;
  localparam logic [31:0] P_APU_BYTES           = 32'h0000_4000;
  localparam logic [31:0] P_IO                  = 32'h0000_c000;
  localparam logic [31:0] P_IO_BYTES            = 32'h0000_1000;
  localparam logic [31:0] P_IO_ACTIVE_BYTES     = 32'h0000_0100;
  localparam logic [31:0] P_INTERNAL_EEPROM     = 32'h0000_d000;
  localparam logic [31:0] P_INTERNAL_EEPROM_BYTES = 32'h0000_1000;
  localparam logic [31:0] P_INTERNAL_COLOR      = 32'h0000_d000;
  localparam logic [31:0] P_INTERNAL_COLOR_BYTES = 32'h0000_0800;
  localparam logic [31:0] P_INTERNAL_MONO       = 32'h0000_d800;
  localparam logic [31:0] P_INTERNAL_MONO_BYTES = 32'h0000_0080;
  localparam logic [31:0] P_CART_EEPROM         = 32'h0000_e000;
  localparam logic [31:0] P_CART_EEPROM_BYTES   = 32'h0000_0800;
  localparam logic [31:0] P_RESERVE0            = 32'h0000_e800;
  localparam logic [31:0] P_RESERVE0_BYTES      = 32'h0000_1800;
  localparam logic [31:0] P_IRAM                = 32'h0001_0000;
  localparam logic [31:0] P_IRAM_BYTES          = 32'h0001_0000;
  localparam logic [31:0] P_SRAM                = 32'h0002_0000;
  localparam logic [31:0] P_SRAM_BYTES          = 32'h0008_0000;
  localparam logic [31:0] P_FLASH               = 32'h000a_0000;
  localparam logic [31:0] P_FLASH_BYTES         = 32'h0008_0000;

  // Machine-state subregions.
  localparam logic [31:0] P_DIRECTORY           = 32'h0000_0000;
  localparam logic [31:0] P_DIRECTORY_BYTES     = 32'h0000_0100;
  localparam logic [31:0] P_CPU                 = 32'h0000_0100;
  localparam logic [31:0] P_CPU_BYTES           = 32'h0000_0300;
  localparam logic [31:0] P_IRQ_INPUT_SERIAL    = 32'h0000_0400;
  localparam logic [31:0] P_IRQ_INPUT_SERIAL_BYTES = 32'h0000_0100;
  localparam logic [31:0] P_DMA                 = 32'h0000_0500;
  localparam logic [31:0] P_DMA_BYTES           = 32'h0000_0200;
  localparam logic [31:0] P_SCHEDULER           = 32'h0000_0700;
  localparam logic [31:0] P_SCHEDULER_BYTES     = 32'h0000_0100;
  localparam logic [31:0] P_MAPPER_CART         = 32'h0000_0800;
  localparam logic [31:0] P_MAPPER_CART_BYTES   = 32'h0000_0100;
  localparam logic [31:0] P_RTC                 = 32'h0000_0900;
  localparam logic [31:0] P_RTC_BYTES           = 32'h0000_0100;
  localparam logic [31:0] P_INTERNAL_EEPROM_CTRL = 32'h0000_0a00;
  localparam logic [31:0] P_INTERNAL_EEPROM_CTRL_BYTES = 32'h0000_0100;
  localparam logic [31:0] P_CART_EEPROM_CTRL    = 32'h0000_0b00;
  localparam logic [31:0] P_CART_EEPROM_CTRL_BYTES = 32'h0000_0100;
  localparam logic [31:0] P_MACHINE_RESERVE     = 32'h0000_0c00;
  localparam logic [31:0] P_MACHINE_RESERVE_BYTES = 32'h0000_3400;

  // PPU subregions.
  localparam logic [31:0] P_PPU_REGS            = 32'h0000_4000;
  localparam logic [31:0] P_PPU_REGS_BYTES      = 32'h0000_0400;
  localparam logic [31:0] P_PPU_BACKGROUNDS     = 32'h0000_4400;
  localparam logic [31:0] P_PPU_BACKGROUNDS_BYTES = 32'h0000_0800;
  localparam logic [31:0] P_PPU_SPRITE_PIPE     = 32'h0000_4c00;
  localparam logic [31:0] P_PPU_SPRITE_PIPE_BYTES = 32'h0000_0800;
  localparam logic [31:0] P_PPU_SPRITE_RAM      = 32'h0000_5400;
  localparam logic [31:0] P_PPU_SPRITE_RAM_BYTES = 32'h0000_0200;
  localparam logic [31:0] P_PPU_SPRITE_CACHE    = 32'h0000_5600;
  localparam logic [31:0] P_PPU_SPRITE_CACHE_BYTES = 32'h0000_0800;
  localparam logic [31:0] P_PPU_OUTPUT          = 32'h0000_5e00;
  localparam logic [31:0] P_PPU_OUTPUT_BYTES    = 32'h0000_0400;
  localparam logic [31:0] P_PPU_RESERVE         = 32'h0000_6200;
  localparam logic [31:0] P_PPU_RESERVE_BYTES   = 32'h0000_1e00;

  // APU subregions.
  localparam logic [31:0] P_APU_GLOBAL          = 32'h0000_8000;
  localparam logic [31:0] P_APU_GLOBAL_BYTES    = 32'h0000_0400;
  localparam logic [31:0] P_APU_CH1             = 32'h0000_8400;
  localparam logic [31:0] P_APU_CH1_BYTES       = 32'h0000_0400;
  localparam logic [31:0] P_APU_CH2             = 32'h0000_8800;
  localparam logic [31:0] P_APU_CH2_BYTES       = 32'h0000_0400;
  localparam logic [31:0] P_APU_CH3             = 32'h0000_8c00;
  localparam logic [31:0] P_APU_CH3_BYTES       = 32'h0000_0400;
  localparam logic [31:0] P_APU_CH4             = 32'h0000_9000;
  localparam logic [31:0] P_APU_CH4_BYTES       = 32'h0000_0400;
  localparam logic [31:0] P_APU_CH5             = 32'h0000_9400;
  localparam logic [31:0] P_APU_CH5_BYTES       = 32'h0000_0400;
  localparam logic [31:0] P_APU_SDMA_IF         = 32'h0000_9800;
  localparam logic [31:0] P_APU_SDMA_IF_BYTES   = 32'h0000_0400;
  localparam logic [31:0] P_APU_RESERVE         = 32'h0000_9c00;
  localparam logic [31:0] P_APU_RESERVE_BYTES   = 32'h0000_2400;

  // Active memory lengths and footer RAM-type identities.
  localparam logic [31:0] V2_MONO_IRAM_BYTES    = 32'h0000_4000;
  localparam logic [31:0] V2_COLOR_IRAM_BYTES   = 32'h0001_0000;
  localparam logic [31:0] V2_MONO_INTERNAL_BYTES = 32'h0000_0080;
  localparam logic [31:0] V2_COLOR_INTERNAL_BYTES = 32'h0000_0800;
  localparam logic [31:0] V2_FLASH_ACTIVE_BYTES = 32'h0008_0000;

  localparam logic [7:0] V2_RAM_NONE       = 8'h00;
  localparam logic [7:0] V2_RAM_SRAM_32K_A = 8'h01;
  localparam logic [7:0] V2_RAM_SRAM_32K_B = 8'h02;
  localparam logic [7:0] V2_RAM_SRAM_128K  = 8'h03;
  localparam logic [7:0] V2_RAM_SRAM_256K  = 8'h04;
  localparam logic [7:0] V2_RAM_SRAM_512K  = 8'h05;
  localparam logic [7:0] V2_RAM_EEPROM_128 = 8'h10;
  localparam logic [7:0] V2_RAM_EEPROM_2K  = 8'h20;
  localparam logic [7:0] V2_RAM_EEPROM_1K  = 8'h50;

  // Bridge and physical SDRAM reservation.
  localparam logic [31:0] V2_BRIDGE_BASE       = 32'h4000_0000;
  localparam logic [31:0] V2_BRIDGE_LAST       = 32'h4012_00ff;
  localparam logic [31:0] V2_STAGE_BASE        = 32'h0110_0000;
  localparam logic [31:0] V2_STAGE_BYTES       = V2_PAYLOAD_BYTES;
  localparam logic [31:0] V2_STAGE_LAST        = 32'h0121_ffff;
  localparam logic [31:0] V2_STAGE_X16_BASE    = 32'h0088_0000;
  localparam logic [31:0] V2_STAGE_X16_LAST    = 32'h0090_ffff;
  localparam logic [31:0] V2_CART_SRAM_LAST    = 32'h0107_ffff;
  localparam logic [31:0] V2_GUARD_BASE        = 32'h0108_0000;
  localparam logic [31:0] V2_GUARD_LAST        = 32'h010f_ffff;

  function automatic logic range_contains(
      input logic [31:0] offset,
      input logic [31:0] base,
      input logic [31:0] bytes
  );
    range_contains = (bytes != 0) && (offset >= base) &&
                     (offset < base + bytes);
  endfunction

  // These bytes are zero for every valid v2 image.  Model/title-dependent
  // padding (mono IRAM, inactive EEPROM, SRAM and flash tails) is additional.
  function automatic logic v2_fixed_zero_payload_byte(
      input logic [31:0] offset
  );
    v2_fixed_zero_payload_byte =
        range_contains(offset, P_MACHINE_RESERVE, P_MACHINE_RESERVE_BYTES) ||
        range_contains(offset, P_PPU_RESERVE, P_PPU_RESERVE_BYTES) ||
        range_contains(offset, P_APU_RESERVE, P_APU_RESERVE_BYTES) ||
        range_contains(offset, P_IO + P_IO_ACTIVE_BYTES,
                       P_IO_BYTES - P_IO_ACTIVE_BYTES) ||
        range_contains(offset, P_RESERVE0, P_RESERVE0_BYTES);
  endfunction

  function automatic logic v2_fixed_zero_header_byte(
      input logic [31:0] offset
  );
    v2_fixed_zero_header_byte =
        range_contains(offset, H_RESERVED_ZERO, 32'd4) ||
        range_contains(offset, H_RESERVED_TAIL, H_RESERVED_TAIL_BYTES);
  endfunction

  function automatic logic [31:0] v2_expected_sram_bytes(
      input logic [7:0] ramtype
  );
    case (ramtype)
      V2_RAM_SRAM_32K_A,
      V2_RAM_SRAM_32K_B: v2_expected_sram_bytes = 32'h0000_8000;
      V2_RAM_SRAM_128K:  v2_expected_sram_bytes = 32'h0002_0000;
      V2_RAM_SRAM_256K:  v2_expected_sram_bytes = 32'h0004_0000;
      V2_RAM_SRAM_512K:  v2_expected_sram_bytes = 32'h0008_0000;
      default:            v2_expected_sram_bytes = 32'd0;
    endcase
  endfunction

  function automatic logic [31:0] v2_expected_cart_eeprom_bytes(
      input logic [7:0] ramtype
  );
    case (ramtype)
      V2_RAM_EEPROM_128: v2_expected_cart_eeprom_bytes = 32'h0000_0080;
      V2_RAM_EEPROM_2K:  v2_expected_cart_eeprom_bytes = 32'h0000_0800;
      V2_RAM_EEPROM_1K:  v2_expected_cart_eeprom_bytes = 32'h0000_0400;
      default:            v2_expected_cart_eeprom_bytes = 32'd0;
    endcase
  endfunction

  // Complete payload padding rule for a header that has already passed model,
  // RAM-type, and feature validation.  The active internal EEPROM occupies its
  // canonical model-specific slice; the inactive model is encoded as zero and
  // is not applied on restore.  Memory bytes above every active length are
  // likewise zero and are rejected if nonzero before live mutation.
  function automatic logic v2_payload_byte_requires_zero(
      input logic [31:0] offset,
      input logic [7:0] model,
      input logic [7:0] ramtype,
      input logic [31:0] flags
  );
    logic [31:0] sram_bytes;
    logic [31:0] cart_eeprom_bytes;
    logic internal_in_active_slice;
    begin
      sram_bytes = v2_expected_sram_bytes(ramtype);
      cart_eeprom_bytes = v2_expected_cart_eeprom_bytes(ramtype);
      internal_in_active_slice =
          (model == V2_MODEL_COLOR &&
           range_contains(offset, P_INTERNAL_COLOR,
                          P_INTERNAL_COLOR_BYTES)) ||
          (model == V2_MODEL_MONO &&
           range_contains(offset, P_INTERNAL_MONO,
                          P_INTERNAL_MONO_BYTES));

      v2_payload_byte_requires_zero =
          v2_fixed_zero_payload_byte(offset) ||
          (range_contains(offset, P_INTERNAL_EEPROM,
                          P_INTERNAL_EEPROM_BYTES) &&
           !internal_in_active_slice) ||
          (range_contains(offset, P_CART_EEPROM, P_CART_EEPROM_BYTES) &&
           offset >= P_CART_EEPROM + cart_eeprom_bytes) ||
          (model == V2_MODEL_MONO &&
           range_contains(offset, P_IRAM + V2_MONO_IRAM_BYTES,
                          P_IRAM_BYTES - V2_MONO_IRAM_BYTES)) ||
          (range_contains(offset, P_SRAM, P_SRAM_BYTES) &&
           offset >= P_SRAM + sram_bytes) ||
          (!flags[3] && range_contains(offset, P_FLASH, P_FLASH_BYTES));
    end
  endfunction

  function automatic logic v2_static_header_valid(
      input logic [31:0] magic,
      input logic [31:0] envelope_version,
      input logic [31:0] header_bytes,
      input logic [31:0] payload_bytes,
      input logic [31:0] total_bytes,
      input logic [31:0] format_id
  );
    v2_static_header_valid =
        magic == V2_MAGIC &&
        envelope_version == V2_ENVELOPE_VERSION &&
        header_bytes == V2_HEADER_BYTES &&
        payload_bytes == V2_PAYLOAD_BYTES &&
        total_bytes == V2_TOTAL_BYTES &&
        format_id == V2_FORMAT_ID;
  endfunction

  function automatic logic v2_feature_identity_valid(
      input logic [31:0] flags,
      input logic [31:0] identity
  );
    logic [7:0] model;
    logic [7:0] mapper;
    logic [7:0] ramtype;
    logic [7:0] bios;
    logic has_sram;
    logic has_cart_eeprom;
    logic known_ramtype;
    begin
      model = identity[31:24];
      mapper = identity[23:16];
      ramtype = identity[15:8];
      bios = identity[7:0];
      has_sram = v2_expected_sram_bytes(ramtype) != 0;
      has_cart_eeprom = v2_expected_cart_eeprom_bytes(ramtype) != 0;
      known_ramtype = ramtype == V2_RAM_NONE || has_sram || has_cart_eeprom;
      v2_feature_identity_valid =
          (flags & ~V2_FEATURE_ALLOWED) == 0 &&
          !(flags[0] && flags[1]) &&
          !(flags[5] && !flags[2]) &&
          !(flags[3] && mapper != V2_MAPPER_2003) &&
          (flags[2] == (mapper == V2_MAPPER_2003)) &&
          (model == V2_MODEL_MONO || model == V2_MODEL_COLOR) &&
          (mapper == V2_MAPPER_2001 || mapper == V2_MAPPER_2003) &&
          (bios == V2_BIOS_MONO || bios == V2_BIOS_COLOR) &&
          known_ramtype &&
          (flags[0] == has_sram) &&
          (flags[1] == has_cart_eeprom) &&
          (flags[4] == (model == V2_MODEL_COLOR)) &&
          (bios == model);
    end
  endfunction

  function automatic logic v2_active_sizes_valid(
      input logic [31:0] flags,
      input logic [31:0] identity,
      input logic [31:0] iram_bytes,
      input logic [31:0] sram_bytes,
      input logic [31:0] cart_eeprom_bytes,
      input logic [31:0] internal_eeprom_bytes,
      input logic [31:0] flash_bytes
  );
    logic [7:0] model;
    logic [7:0] ramtype;
    begin
      model = identity[31:24];
      ramtype = identity[15:8];
      v2_active_sizes_valid =
          v2_feature_identity_valid(flags, identity) &&
          iram_bytes == (model == V2_MODEL_COLOR ?
                         V2_COLOR_IRAM_BYTES : V2_MONO_IRAM_BYTES) &&
          sram_bytes == v2_expected_sram_bytes(ramtype) &&
          cart_eeprom_bytes == v2_expected_cart_eeprom_bytes(ramtype) &&
          internal_eeprom_bytes == (model == V2_MODEL_COLOR ?
                                    V2_COLOR_INTERNAL_BYTES :
                                    V2_MONO_INTERNAL_BYTES) &&
          flash_bytes == (flags[3] ? V2_FLASH_ACTIVE_BYTES : 32'd0);
    end
  endfunction
endpackage

`default_nettype wire
