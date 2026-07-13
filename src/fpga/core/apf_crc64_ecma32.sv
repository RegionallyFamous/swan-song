`default_nettype none

// Streaming CRC-64/ECMA-182 for normalized APF blob words.
//
// Byte order is part of this module's interface contract: blob_word[31:24]
// is the byte at the lowest blob address, followed by [23:16], [15:8], and
// [7:0].  byte_count consumes that contiguous prefix (0 through 4 bytes).
// This matches the byte order visible at the current big-endian APF bridge
// after the state/SDRAM adapter has normalized its data.
//
// CRC parameters:
//   width   = 64
//   poly    = 0x42f0e1eba9ea3693
//   init    = 0
//   refin   = false
//   refout  = false
//   xorout  = 0
//
// reset_n asserts asynchronously. clear is synchronous and has priority over
// enable. When enable is low, byte_count is zero, or byte_count is outside the
// legal 0..4 range, crc_value holds. Because xorout is zero, crc_value is also
// the final CRC immediately after the clock edge that accepts the last bytes;
// no separate finalize transform is needed.
module apf_crc64_ecma32 (
    input  wire        clk,
    input  wire        reset_n,
    input  wire        clear,
    input  wire        enable,
    input  wire [31:0] blob_word,
    input  wire [ 2:0] byte_count,
    output reg  [63:0] crc_value
);
  localparam [63:0] POLYNOMIAL = 64'h42f0_e1eb_a9ea_3693;

  function automatic [63:0] update_byte;
    input [63:0] crc_in;
    input [7:0] data_byte;
    integer bit_index;
    reg [63:0] next_crc;
    begin
      next_crc = crc_in ^ {data_byte, 56'd0};
      for (bit_index = 0; bit_index < 8; bit_index = bit_index + 1) begin
        if (next_crc[63])
          next_crc = {next_crc[62:0], 1'b0} ^ POLYNOMIAL;
        else
          next_crc = {next_crc[62:0], 1'b0};
      end
      update_byte = next_crc;
    end
  endfunction

  function automatic [63:0] update_word;
    input [63:0] crc_in;
    input [31:0] data_word;
    input [2:0] valid_bytes;
    reg [63:0] next_crc;
    begin
      next_crc = crc_in;
      if (valid_bytes >= 3'd1)
        next_crc = update_byte(next_crc, data_word[31:24]);
      if (valid_bytes >= 3'd2)
        next_crc = update_byte(next_crc, data_word[23:16]);
      if (valid_bytes >= 3'd3)
        next_crc = update_byte(next_crc, data_word[15:8]);
      if (valid_bytes >= 3'd4)
        next_crc = update_byte(next_crc, data_word[7:0]);
      update_word = next_crc;
    end
  endfunction

  always @(posedge clk or negedge reset_n) begin
    if (!reset_n)
      crc_value <= 64'd0;
    else if (clear)
      crc_value <= 64'd0;
    else if (enable && byte_count <= 3'd4)
      crc_value <= update_word(crc_value, blob_word, byte_count);
  end

`ifndef SYNTHESIS
  always @(posedge clk) begin
    if (reset_n && enable && !clear && byte_count > 3'd4)
      $warning("apf_crc64_ecma32 ignored byte_count outside 0..4: %0d",
               byte_count);
  end
`endif
endmodule

`default_nettype wire
