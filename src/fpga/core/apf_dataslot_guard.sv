// APF 0x0080/0x0082 request policy and readiness guard.
//
// The command handler holds request_valid until ack.  This block snapshots one
// request, exposes its ID to a combinational slot-policy lookup, and returns an
// acknowledgement only after policy and loader readiness have been evaluated.
// Official APF result values are: 0 ready, 1 never allowed, 2 check later.
module apf_dataslot_guard (
    input  wire        clk,
    input  wire        reset_n,

    input  wire        request_valid,
    input  wire        request_write,  // 0 = 0x0080 read, 1 = 0x0082 write
    input  wire [15:0] request_id,
    input  wire [47:0] request_size,   // 0x0082 supports a 48-bit byte count

    output reg         request_ack,
    output reg  [ 1:0] request_result,
    output wire        request_busy,

    // Drive these inputs from a combinational lookup keyed by policy_slot_id.
    output reg  [15:0] policy_slot_id,
    input  wire        policy_slot_known,
    input  wire        policy_allow_read,
    input  wire        policy_allow_write,
    input  wire        policy_bounds_ready,
    // 0: no write-size restriction, 1: exact size, 2: inclusive min/max.
    input  wire [ 1:0] policy_size_mode,
    input  wire [47:0] policy_exact_size,
    input  wire [47:0] policy_min_size,
    input  wire [47:0] policy_max_size,
    // Assert for the nonvolatile-save policy entry.  Its offered host length
    // is recorded even when the request must retry or is rejected by bounds.
    input  wire        policy_capture_length,

    input  wire        read_loader_ready,
    input  wire        write_loader_ready,

    input  wire        captured_length_clear,
    output reg         captured_save_length_valid,
    output reg  [15:0] captured_save_id,
    output reg  [47:0] captured_save_length,
    output reg         captured_save_length_updated
);

  localparam [1:0] RESULT_READY = 2'd0;
  localparam [1:0] RESULT_NOT_ALLOWED = 2'd1;
  localparam [1:0] RESULT_CHECK_LATER = 2'd2;

  localparam [1:0] SIZE_UNRESTRICTED = 2'd0;
  localparam [1:0] SIZE_EXACT = 2'd1;
  localparam [1:0] SIZE_RANGE = 2'd2;

  localparam [1:0] STATE_IDLE = 2'd0;
  localparam [1:0] STATE_EVALUATE = 2'd1;
  localparam [1:0] STATE_WAIT_RELEASE = 2'd2;

  reg [1:0] state;
  reg latched_write;
  reg [47:0] latched_size;

  wire direction_allowed = latched_write ? policy_allow_write
                                         : policy_allow_read;
  wire selected_loader_ready = latched_write ? write_loader_ready
                                             : read_loader_ready;
  wire exact_size_valid = latched_size == policy_exact_size;
  wire range_size_valid = (latched_size >= policy_min_size) &&
                          (latched_size <= policy_max_size);
  wire write_size_valid = (policy_size_mode == SIZE_UNRESTRICTED) ||
                          ((policy_size_mode == SIZE_EXACT) &&
                           exact_size_valid) ||
                          ((policy_size_mode == SIZE_RANGE) &&
                           range_size_valid);
  wire size_mode_valid = policy_size_mode != 2'd3;

  assign request_busy = state != STATE_IDLE;

  always @(posedge clk) begin
    request_ack <= 1'b0;
    captured_save_length_updated <= 1'b0;

    if (!reset_n) begin
      state <= STATE_IDLE;
      latched_write <= 1'b0;
      latched_size <= 48'd0;
      policy_slot_id <= 16'd0;
      request_result <= RESULT_READY;
      captured_save_length_valid <= 1'b0;
      captured_save_id <= 16'd0;
      captured_save_length <= 48'd0;
    end else begin
      case (state)
        STATE_IDLE: begin
          if (request_valid) begin
            policy_slot_id <= request_id;
            latched_write <= request_write;
            latched_size <= request_size;
            state <= STATE_EVALUATE;
          end
        end

        STATE_EVALUATE: begin
          // Capture the offered save length independently of acceptance.  This
          // lets later cartridge-header validation distinguish absent, exact,
          // legacy, truncated, and oversized host files.
          if (latched_write && policy_slot_known && policy_capture_length) begin
            captured_save_length_valid <= 1'b1;
            captured_save_id <= policy_slot_id;
            captured_save_length <= latched_size;
            captured_save_length_updated <= 1'b1;
          end

          if (!policy_slot_known || !direction_allowed) begin
            request_result <= RESULT_NOT_ALLOWED;
          end else if (!policy_bounds_ready) begin
            request_result <= RESULT_CHECK_LATER;
          end else if (!size_mode_valid ||
                       (latched_write && !write_size_valid)) begin
            request_result <= RESULT_NOT_ALLOWED;
          end else if (!selected_loader_ready) begin
            request_result <= RESULT_CHECK_LATER;
          end else begin
            request_result <= RESULT_READY;
          end

          request_ack <= 1'b1;
          state <= STATE_WAIT_RELEASE;
        end

        STATE_WAIT_RELEASE: begin
          // A level-held command must not be accepted a second time after its
          // one-cycle acknowledgement.  Re-arm only after the handler drops it.
          if (!request_valid)
            state <= STATE_IDLE;
        end

        default: begin
          state <= STATE_IDLE;
          request_result <= RESULT_CHECK_LATER;
        end
      endcase

      if (captured_length_clear) begin
        // Clear only the prior title's diagnostic length. The request FSM must
        // keep running because Chip32 holds cart_download high around LOADF,
        // including while Pocket's slot-0 0082 request awaits acknowledgement.
        // These final assignments also dominate a coincident save capture.
        captured_save_length_valid <= 1'b0;
        captured_save_id <= 16'd0;
        captured_save_length <= 48'd0;
        captured_save_length_updated <= 1'b0;
      end
    end
  end

endmodule
