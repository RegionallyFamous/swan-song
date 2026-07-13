// Swan Song save-state compatibility envelope.
//
// Analogue's APF runtime writes the complete A4 blob before requesting the
// load.  A state blob therefore needs a format contract that can be rejected
// before any bytes are applied to the emulated machine.  This module owns the
// 32-byte bridge-word header and validates an exact, sequential
// transfer.  The MiSTer payload is exposed without the envelope for a future
// full-size staging-memory writer.  It MUST NOT be connected directly to the
// live MiSTer state bus: APF writes the complete blob before Request Load.
//
// 32-bit APF bridge words by byte-addressed offset (SD byte serialization is
// owned by the framework and is not assumed here):
//   00  "SWAN" magic
//   04  envelope version (1)
//   08  header length in bytes (32)
//   0c  MiSTer payload length in bytes
//   10  total blob length in bytes
//   14  payload format id ("WS" + 16-bit revision)
//   18  compatibility flags (must be zero for version 1)
//   1c  reserved (must be zero)
module apf_savestate_envelope #(
    parameter [31:0] PAYLOAD_BYTES = 32'h0009_0300,
    parameter [31:0] FORMAT_ID = 32'h5753_0001
) (
    input  wire        clk,
    input  wire        reset_n,

    input  wire        load_write,
    input  wire [27:0] load_offset,
    input  wire [31:0] load_data,
    input  wire        load_finalize,

    output reg         payload_write,
    output reg  [27:0] payload_offset,
    output reg  [31:0] payload_data,
    output reg         load_active,
    output reg         load_complete,
    output reg         load_ready,
    output reg         load_error,

    input  wire [27:0] save_offset,
    output reg  [31:0] save_header_data,
    output wire        save_header_select
);
  localparam [31:0] MAGIC = 32'h5357_414e;  // "SWAN"
  localparam [31:0] VERSION = 32'd1;
  localparam [31:0] HEADER_BYTES = 32'd32;
  localparam [31:0] TOTAL_BYTES = PAYLOAD_BYTES + HEADER_BYTES;

  reg [27:0] expected_offset;

  assign save_header_select = (save_offset < HEADER_BYTES[27:0]) &&
                              (save_offset[1:0] == 2'b00);

  always @(*) begin
    case (save_offset)
      28'h0000000: save_header_data = MAGIC;
      28'h0000004: save_header_data = VERSION;
      28'h0000008: save_header_data = HEADER_BYTES;
      28'h000000c: save_header_data = PAYLOAD_BYTES;
      28'h0000010: save_header_data = TOTAL_BYTES;
      28'h0000014: save_header_data = FORMAT_ID;
      28'h0000018: save_header_data = 32'd0;
      28'h000001c: save_header_data = 32'd0;
      default: save_header_data = 32'd0;
    endcase
  end

  always @(posedge clk or negedge reset_n) begin
    if (!reset_n) begin
      payload_write  <= 1'b0;
      payload_offset <= 28'd0;
      payload_data   <= 32'd0;
      load_active    <= 1'b0;
      load_complete  <= 1'b0;
      load_ready     <= 1'b0;
      load_error     <= 1'b0;
      expected_offset <= 28'd0;
    end else begin
      payload_write <= 1'b0;

      // Offset zero is the only legal beginning of a new blob.  It also
      // recovers cleanly after a rejected or previously finalized transfer.
      if (load_write && load_offset == 28'd0) begin
        load_active     <= 1'b1;
        load_complete   <= 1'b0;
        load_ready      <= 1'b0;
        load_error      <= (load_data != MAGIC);
        expected_offset <= 28'd4;
      end else if (load_write) begin
        if (!load_active || load_ready || load_error ||
            load_offset[1:0] != 2'b00 ||
            load_offset != expected_offset ||
            load_offset >= TOTAL_BYTES[27:0]) begin
          load_error <= 1'b1;
          load_ready <= 1'b0;
        end else begin
          expected_offset <= expected_offset + 28'd4;

          case (load_offset)
            28'h0000004: if (load_data != VERSION) load_error <= 1'b1;
            28'h0000008: if (load_data != HEADER_BYTES) load_error <= 1'b1;
            28'h000000c: if (load_data != PAYLOAD_BYTES) load_error <= 1'b1;
            28'h0000010: if (load_data != TOTAL_BYTES) load_error <= 1'b1;
            28'h0000014: if (load_data != FORMAT_ID) load_error <= 1'b1;
            28'h0000018: if (load_data != 32'd0) load_error <= 1'b1;
            28'h000001c: if (load_data != 32'd0) load_error <= 1'b1;
            default: begin
              if (load_offset >= HEADER_BYTES[27:0]) begin
                payload_write  <= 1'b1;
                payload_offset <= load_offset - HEADER_BYTES[27:0];
                payload_data   <= load_data;
              end
            end
          endcase

          if (load_offset == TOTAL_BYTES[27:0] - 28'd4)
            load_complete <= 1'b1;
        end
      end

      // A4 Request Load is the transfer boundary supplied by APF.  A short,
      // malformed, out-of-order, or overlong blob is rejected before ss_load.
      if (load_finalize) begin
        if (load_active && load_complete && !load_error &&
            expected_offset == TOTAL_BYTES[27:0]) begin
          load_ready <= 1'b1;
        end else begin
          load_ready <= 1'b0;
          load_error <= 1'b1;
        end
      end
    end
  end
endmodule
