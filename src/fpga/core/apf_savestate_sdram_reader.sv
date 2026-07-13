`default_nettype none

// Isolated memory-domain reader for the future Pocket Memories staging path.
//
// A checked payload-relative x32 request becomes two ordered x16 SDRAM reads.
// The normalized result is retained in a one-entry output cache until the
// consumer accepts it. This module deliberately contains neither the future
// CDC FIFO nor the APF BRIDGE timing wrapper and is not a production client.
module apf_savestate_sdram_reader #(
    parameter integer SDRAM_ADDR_WIDTH = 25,
    parameter [31:0] STAGE_BASE_BYTE = 32'h0110_0000,
    parameter [31:0] STAGE_BYTES = 32'h0009_0300
) (
    input  wire                         clk,
    input  wire                         reset_n,

    // Starting a transaction invalidates the previous cache and counters.
    // abort has priority and poisons the entire logical transaction.
    input  wire                         transfer_start,
    output wire                         transfer_start_ready,
    input  wire                         abort,
    output reg                          transfer_active,
    output reg                          transfer_failed,
    output reg  [2:0]                   failure_reason,
    output wire                         busy,
    output wire                         quiescent,

    // One four-byte-aligned payload-relative offset per request. A new
    // request may turn over on the same edge that the cached word is consumed.
    input  wire                         read_request_valid,
    output wire                         read_request_ready,
    input  wire [31:0]                  read_request_offset,

    // Normalized blob byte order: read_word[31:24] is the byte at the lowest
    // requested address. Offset/data remain stable while valid and not ready.
    output wire                         read_word_valid,
    input  wire                         read_word_ready,
    output reg  [31:0]                  read_word_offset,
    output reg  [31:0]                  read_word,
    output reg  [31:0]                  fetched_bytes,
    output reg  [31:0]                  delivered_bytes,

    // Edge-request interface matching the inherited Swan SDRAM clients.
    // sdram_req is exactly one cycle. Data/error are sampled only with the
    // single ready completion for a previously issued request.
    output reg                          sdram_req,
    output reg  [SDRAM_ADDR_WIDTH-1:0]  sdram_addr,
    output wire                         sdram_rnw,
    input  wire [15:0]                  sdram_data,
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
  reg cache_valid;
  reg [SDRAM_ADDR_WIDTH-1:0] pending_word_addr;
  reg [31:0] pending_offset;
  reg [15:0] pending_low_data;

  wire [63:0] candidate_byte_addr =
      {32'd0, STAGE_BASE_BYTE} + {32'd0, read_request_offset};
  wire [63:0] candidate_end_addr = candidate_byte_addr + 64'd4;
  wire request_offset_valid =
      read_request_offset[1:0] == 2'b00 &&
      read_request_offset <= STAGE_BYTES - 32'd4 &&
      candidate_byte_addr >= {32'd0, STAGE_BASE_BYTE} &&
      candidate_end_addr <= STAGE_END_BYTE &&
      candidate_end_addr <= SDRAM_BYTES;

  assign quiescent = state == STATE_IDLE;
  assign busy = !quiescent;
  assign transfer_start_ready = quiescent && !abort;
  assign read_word_valid = cache_valid && transfer_active &&
                           !transfer_failed && !transfer_start && !abort;
  assign read_request_ready = quiescent && transfer_active &&
                              !transfer_failed && !transfer_start && !abort &&
                              (!cache_valid || read_word_ready);
  assign sdram_rnw = 1'b1;

  always @(posedge clk or negedge reset_n) begin
    if (!reset_n) begin
      state <= STATE_IDLE;
      cache_valid <= 1'b0;
      transfer_active <= 1'b0;
      transfer_failed <= 1'b0;
      failure_reason <= FAILURE_NONE;
      read_word_offset <= 32'd0;
      read_word <= 32'd0;
      fetched_bytes <= 32'd0;
      delivered_bytes <= 32'd0;
      sdram_req <= 1'b0;
      sdram_addr <= {SDRAM_ADDR_WIDTH{1'b0}};
      pending_word_addr <= {SDRAM_ADDR_WIDTH{1'b0}};
      pending_offset <= 32'd0;
      pending_low_data <= 16'd0;
    end else begin
      sdram_req <= 1'b0;

      // Keep draining while abort is held. This prevents a late completion
      // from being accepted by a restarted logical transaction.
      if (abort) begin
        cache_valid <= 1'b0;
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
        cache_valid <= 1'b0;
        transfer_active <= 1'b1;
        transfer_failed <= 1'b0;
        failure_reason <= FAILURE_NONE;
        read_word_offset <= 32'd0;
        read_word <= 32'd0;
        fetched_bytes <= 32'd0;
        delivered_bytes <= 32'd0;
      end else begin
        case (state)
          STATE_IDLE: begin
            // A cached word can be consumed and its successor accepted on the
            // same edge. read_request_ready advertises exactly that capacity.
            if (cache_valid && read_word_ready) begin
              cache_valid <= 1'b0;
              delivered_bytes <= delivered_bytes + 32'd4;
            end

            if (read_request_valid && read_request_ready) begin
              cache_valid <= 1'b0;
              if (!request_offset_valid) begin
                transfer_active <= 1'b0;
                transfer_failed <= 1'b1;
                failure_reason <= FAILURE_ADDRESS;
              end else begin
                pending_word_addr <=
                    candidate_byte_addr[SDRAM_ADDR_WIDTH:1];
                pending_offset <= read_request_offset;
                sdram_addr <= candidate_byte_addr[SDRAM_ADDR_WIDTH:1];
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
                pending_low_data <= sdram_data;
                sdram_addr <= pending_word_addr +
                    {{(SDRAM_ADDR_WIDTH-1){1'b0}}, 1'b1};
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
                cache_valid <= 1'b1;
                read_word_offset <= pending_offset;
                read_word <= {
                    pending_low_data[7:0],
                    pending_low_data[15:8],
                    sdram_data[7:0],
                    sdram_data[15:8]
                };
                fetched_bytes <= fetched_bytes + 32'd4;
              end
            end
          end

          STATE_ABORT_DRAIN: begin
            if (sdram_ready)
              state <= STATE_IDLE;
          end

          default: begin
            state <= STATE_IDLE;
            cache_valid <= 1'b0;
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
