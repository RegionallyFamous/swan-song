`default_nettype none

// Isolated memory-domain writer for the future Pocket Memories staging path.
//
// This module deliberately contains no CDC FIFO and is not a BRIDGE endpoint.
// Its ready/valid input must eventually be fed by a lossless clock crossing.
// One normalized 32-bit blob word is latched only when stage_word_ready is
// asserted, then split into two full-width x16 SDRAM writes. A logical commit
// is reported only after both requests complete successfully.
//
// Normalized byte order matches apf_crc64_ecma32: stage_word[31:24] is the
// byte at the lowest payload address. Since the x16 memory is little-endian at
// each word address, the two SDRAM values are {byte1, byte0} and
// {byte3, byte2}. Partial physical writes can exist after abort/backend error,
// but the transaction is then permanently invalid and no commit is emitted.
module apf_savestate_sdram_writer #(
    parameter integer SDRAM_ADDR_WIDTH = 25,
    parameter [31:0] STAGE_BASE_BYTE = 32'h0110_0000,
    parameter [31:0] STAGE_BYTES = 32'h0009_0300
) (
    input  wire                         clk,
    input  wire                         reset_n,

    // A new transaction can start only when transfer_start_ready is high.
    // Starting while quiescent invalidates the previous logical image and
    // clears its count/error state. abort has priority over transfer_start.
    input  wire                         transfer_start,
    output wire                         transfer_start_ready,
    input  wire                         abort,
    output reg                          transfer_active,
    output reg                          transfer_failed,
    output reg  [2:0]                   failure_reason,
    output wire                         busy,
    output wire                         quiescent,

    // Payload-relative byte offset. Invalid/misaligned words are consumed as
    // terminal transaction failures and never issue an SDRAM request.
    input  wire                         stage_word_valid,
    output wire                         stage_word_ready,
    input  wire [31:0]                  stage_word_offset,
    input  wire [31:0]                  stage_word,

    // Commit is a one-cycle pulse after the high x16 half completes. The
    // metadata and count refer only to fully committed 32-bit words.
    output reg                          commit_pulse,
    output reg  [31:0]                  committed_offset,
    output reg  [31:0]                  committed_word,
    output reg  [31:0]                  committed_bytes,

    // Edge-request interface matching the existing Swan Song SDRAM clients.
    // sdram_req is exactly one cycle. ready/error are sampled only while a
    // previously issued request is outstanding; error is meaningful with
    // ready. Both byte lanes are always written.
    output reg                          sdram_req,
    output reg  [SDRAM_ADDR_WIDTH-1:0]  sdram_addr,
    output reg  [15:0]                  sdram_data,
    output wire [1:0]                   sdram_be,
    input  wire                         sdram_ready,
    input  wire                         sdram_error
);
  localparam [2:0] FAILURE_NONE = 3'd0;
  localparam [2:0] FAILURE_ADDRESS = 3'd1;
  localparam [2:0] FAILURE_BACKEND_LOW = 3'd2;
  localparam [2:0] FAILURE_BACKEND_HIGH = 3'd3;
  localparam [2:0] FAILURE_ABORT = 3'd4;

  localparam [2:0] STATE_IDLE = 3'd0;
  localparam [2:0] STATE_ISSUE_LOW = 3'd1;
  localparam [2:0] STATE_WAIT_LOW = 3'd2;
  localparam [2:0] STATE_ISSUE_HIGH = 3'd3;
  localparam [2:0] STATE_WAIT_HIGH = 3'd4;
  localparam [2:0] STATE_ABORT_DRAIN = 3'd5;

  localparam [63:0] SDRAM_BYTES = 64'd1 << (SDRAM_ADDR_WIDTH + 1);
  localparam [63:0] STAGE_END_BYTE =
      {32'd0, STAGE_BASE_BYTE} + {32'd0, STAGE_BYTES};

  reg [2:0] state;
  reg [SDRAM_ADDR_WIDTH-1:0] pending_word_addr;
  reg [31:0] pending_offset;
  reg [31:0] pending_word;

  wire [63:0] candidate_byte_addr =
      {32'd0, STAGE_BASE_BYTE} + {32'd0, stage_word_offset};
  wire [63:0] candidate_end_addr = candidate_byte_addr + 64'd4;
  wire stage_offset_valid =
      stage_word_offset[1:0] == 2'b00 &&
      stage_word_offset <= STAGE_BYTES - 32'd4 &&
      candidate_byte_addr >= {32'd0, STAGE_BASE_BYTE} &&
      candidate_end_addr <= STAGE_END_BYTE &&
      candidate_end_addr <= SDRAM_BYTES;

  assign quiescent = state == STATE_IDLE;
  assign busy = !quiescent;
  assign transfer_start_ready = quiescent && !abort;
  assign stage_word_ready = quiescent && transfer_active &&
                            !transfer_failed && !transfer_start && !abort;
  assign sdram_be = 2'b11;

  always @(posedge clk or negedge reset_n) begin
    if (!reset_n) begin
      state <= STATE_IDLE;
      transfer_active <= 1'b0;
      transfer_failed <= 1'b0;
      failure_reason <= FAILURE_NONE;
      commit_pulse <= 1'b0;
      committed_offset <= 32'd0;
      committed_word <= 32'd0;
      committed_bytes <= 32'd0;
      sdram_req <= 1'b0;
      sdram_addr <= {SDRAM_ADDR_WIDTH{1'b0}};
      sdram_data <= 16'd0;
      pending_word_addr <= {SDRAM_ADDR_WIDTH{1'b0}};
      pending_offset <= 32'd0;
      pending_word <= 32'd0;
    end else begin
      sdram_req <= 1'b0;
      commit_pulse <= 1'b0;

      // Abort prevents a second half from being issued and poisons the entire
      // logical transaction. An already issued edge request must still drain
      // so that its later ready pulse cannot acknowledge a future transfer.
      if (abort) begin
        transfer_active <= 1'b0;
        transfer_failed <= 1'b1;
        failure_reason <= FAILURE_ABORT;
        if ((state == STATE_WAIT_LOW || state == STATE_WAIT_HIGH ||
             state == STATE_ABORT_DRAIN) && !sdram_ready)
          state <= STATE_ABORT_DRAIN;
        else
          state <= STATE_IDLE;
      end else if (transfer_start && transfer_start_ready) begin
        state <= STATE_IDLE;
        transfer_active <= 1'b1;
        transfer_failed <= 1'b0;
        failure_reason <= FAILURE_NONE;
        committed_offset <= 32'd0;
        committed_word <= 32'd0;
        committed_bytes <= 32'd0;
      end else begin
        case (state)
          STATE_IDLE: begin
            if (stage_word_valid && stage_word_ready) begin
              if (!stage_offset_valid) begin
                transfer_active <= 1'b0;
                transfer_failed <= 1'b1;
                failure_reason <= FAILURE_ADDRESS;
              end else begin
                pending_word_addr <=
                    candidate_byte_addr[SDRAM_ADDR_WIDTH:1];
                pending_offset <= stage_word_offset;
                pending_word <= stage_word;
                sdram_addr <= candidate_byte_addr[SDRAM_ADDR_WIDTH:1];
                sdram_data <= {stage_word[23:16], stage_word[31:24]};
                state <= STATE_ISSUE_LOW;
              end
            end
          end

          STATE_ISSUE_LOW: begin
            sdram_req <= 1'b1;
            state <= STATE_WAIT_LOW;
          end

          STATE_WAIT_LOW: begin
            if (sdram_ready) begin
              if (sdram_error) begin
                state <= STATE_IDLE;
                transfer_active <= 1'b0;
                transfer_failed <= 1'b1;
                failure_reason <= FAILURE_BACKEND_LOW;
              end else begin
                sdram_addr <= pending_word_addr + {{(SDRAM_ADDR_WIDTH-1){1'b0}}, 1'b1};
                sdram_data <= {pending_word[7:0], pending_word[15:8]};
                state <= STATE_ISSUE_HIGH;
              end
            end
          end

          STATE_ISSUE_HIGH: begin
            sdram_req <= 1'b1;
            state <= STATE_WAIT_HIGH;
          end

          STATE_WAIT_HIGH: begin
            if (sdram_ready) begin
              state <= STATE_IDLE;
              if (sdram_error) begin
                transfer_active <= 1'b0;
                transfer_failed <= 1'b1;
                failure_reason <= FAILURE_BACKEND_HIGH;
              end else begin
                commit_pulse <= 1'b1;
                committed_offset <= pending_offset;
                committed_word <= pending_word;
                committed_bytes <= committed_bytes + 32'd4;
              end
            end
          end

          STATE_ABORT_DRAIN: begin
            if (sdram_ready)
              state <= STATE_IDLE;
          end

          default: begin
            state <= STATE_IDLE;
            transfer_active <= 1'b0;
            transfer_failed <= 1'b1;
            failure_reason <= FAILURE_ABORT;
          end
        endcase
      end
    end
  end

  initial begin
    if (SDRAM_ADDR_WIDTH < 2 || SDRAM_ADDR_WIDTH > 31)
      $error("SDRAM_ADDR_WIDTH must be between 2 and 31");
    if (STAGE_BYTES < 32'd4 || STAGE_BYTES[1:0] != 2'b00)
      $error("STAGE_BYTES must be a nonzero multiple of four");
    if (STAGE_BASE_BYTE[1:0] != 2'b00)
      $error("STAGE_BASE_BYTE must be four-byte aligned");
    if (STAGE_END_BYTE > SDRAM_BYTES)
      $error("staging range exceeds the x16 SDRAM address space");
  end
endmodule

`default_nettype wire
