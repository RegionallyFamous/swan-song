`default_nettype none

// Isolated backing-memory walker for the two fixed Memories v2 EEPROM payload
// sections. This module is not a production RAM arbiter and is deliberately
// absent from ap_core.qsf. A future global owner must freeze both EEPROM
// controllers, grant this walker exclusive access to their second RAM ports,
// and keep staging immutable throughout a restore.
//
// The backing interface is the physical x16 word view used by eeprom.vhd:
//   internal Color words 0..1023, internal mono words 1024..1087,
//   cartridge words 0..1023.
// The staging interface uses normalized 32-bit v2 words: bits 31:24 contain
// the byte at the lowest payload offset. Requests are one-cycle edge pulses;
// ready/error complete exactly one previously issued request.
//
// Restore first reads and validates the complete fixed section, including all
// deterministic zero padding, before issuing any backing write. An abort or
// backend failure never reports done and stops all new requests. If a restore
// has already committed backing writes, writes_committed remains asserted so
// the future atomic owner can fail closed rather than resume partial state.
module apf_savestate_v2_eeprom_walker #(
    parameter integer MAX_WAIT_CYCLES = 1024
) (
    input  wire         clk,
    input  wire         reset_n,

    input  wire         freeze,
    output reg          frozen_ack,
    input  wire         start,
    output wire         start_ready,
    input  wire         abort_request,
    input  wire         restore,
    input  wire         select_internal,
    input  wire [7:0]   model,
    input  wire [7:0]   ramtype,

    output reg          busy,
    output reg          done,
    output reg          failed,
    output reg  [3:0]   failure_reason,
    output reg          writes_committed,
    // Conservative poison bit: asserted as soon as any restore write request
    // is issued. Unlike writes_committed, this remains true if that request
    // times out and its eventual physical outcome is unknowable.
    output reg          write_may_have_committed,
    output wire         poisoned,
    // High whenever the backing/staging grant must remain routed here.  A
    // timeout or tainted restore keeps this asserted through lifecycle reset,
    // even though busy has ended and the failed pulse has already retired.
    output wire         ownership_retained,

    // Absolute payload-relative byte offset in the fixed v2 payload.
    output wire         stage_req,
    output wire         stage_write,
    output wire [31:0]  stage_offset,
    output wire [31:0]  stage_write_data,
    input  wire [31:0]  stage_read_data,
    input  wire         stage_ready,
    input  wire         stage_error,

    // Physical EEPROM x16 word port. mem_req is exactly one cycle.
    output wire         mem_req,
    output wire         mem_write,
    output wire [10:0]  mem_addr,
    output wire [15:0]  mem_write_data,
    input  wire [15:0]  mem_read_data,
    input  wire         mem_ready,
    input  wire         mem_error
);
  // Kept local so this boundary remains directly synthesizable even in tools
  // that do not implement SystemVerilog package imports. The focused contract
  // test compares every emitted address and accepted identity against
  // apf_savestate_v2_layout_pkg.
  localparam logic [31:0] P_INTERNAL_EEPROM = 32'h0000_d000;
  localparam logic [31:0] P_CART_EEPROM = 32'h0000_e000;
  localparam logic [7:0] V2_MODEL_MONO = 8'd0;
  localparam logic [7:0] V2_MODEL_COLOR = 8'd1;
  localparam logic [7:0] V2_RAM_NONE = 8'h00;
  localparam logic [7:0] V2_RAM_SRAM_32K_A = 8'h01;
  localparam logic [7:0] V2_RAM_SRAM_32K_B = 8'h02;
  localparam logic [7:0] V2_RAM_SRAM_128K = 8'h03;
  localparam logic [7:0] V2_RAM_SRAM_256K = 8'h04;
  localparam logic [7:0] V2_RAM_SRAM_512K = 8'h05;
  localparam logic [7:0] V2_RAM_EEPROM_128 = 8'h10;
  localparam logic [7:0] V2_RAM_EEPROM_2K = 8'h20;
  localparam logic [7:0] V2_RAM_EEPROM_1K = 8'h50;
  localparam logic [3:0] EEPROM_WALK_FAILURE_NONE = 4'd0;
  localparam logic [3:0] EEPROM_WALK_FAILURE_CONFIG = 4'd1;
  localparam logic [3:0] EEPROM_WALK_FAILURE_ABORT = 4'd2;
  localparam logic [3:0] EEPROM_WALK_FAILURE_STAGE_BACKEND = 4'd3;
  localparam logic [3:0] EEPROM_WALK_FAILURE_MEMORY_BACKEND = 4'd4;
  localparam logic [3:0] EEPROM_WALK_FAILURE_PADDING = 4'd5;
  localparam logic [3:0] EEPROM_WALK_FAILURE_STAGE_TIMEOUT = 4'd6;
  localparam logic [3:0] EEPROM_WALK_FAILURE_MEMORY_TIMEOUT = 4'd7;
  localparam logic [3:0] EEPROM_WALK_FAILURE_INTERNAL = 4'd8;

  localparam integer WAIT_WIDTH =
      MAX_WAIT_CYCLES <= 1 ? 1 : $clog2(MAX_WAIT_CYCLES + 1);
  localparam logic [WAIT_WIDTH-1:0] WAIT_LAST =
      WAIT_WIDTH'(MAX_WAIT_CYCLES - 1);

  localparam logic [4:0] STATE_IDLE                 = 5'd0;
  localparam logic [4:0] STATE_CAPTURE_DISPATCH     = 5'd1;
  localparam logic [4:0] STATE_CAPTURE_MEM0_ISSUE   = 5'd2;
  localparam logic [4:0] STATE_CAPTURE_MEM0_WAIT    = 5'd3;
  localparam logic [4:0] STATE_CAPTURE_MEM1_ISSUE   = 5'd4;
  localparam logic [4:0] STATE_CAPTURE_MEM1_WAIT    = 5'd5;
  localparam logic [4:0] STATE_CAPTURE_STAGE_ISSUE  = 5'd6;
  localparam logic [4:0] STATE_CAPTURE_STAGE_WAIT   = 5'd7;
  localparam logic [4:0] STATE_VALIDATE_STAGE_ISSUE = 5'd8;
  localparam logic [4:0] STATE_VALIDATE_STAGE_WAIT  = 5'd9;
  localparam logic [4:0] STATE_LOAD_STAGE_ISSUE     = 5'd10;
  localparam logic [4:0] STATE_LOAD_STAGE_WAIT      = 5'd11;
  localparam logic [4:0] STATE_LOAD_MEM0_ISSUE      = 5'd12;
  localparam logic [4:0] STATE_LOAD_MEM0_WAIT       = 5'd13;
  localparam logic [4:0] STATE_LOAD_MEM1_ISSUE      = 5'd14;
  localparam logic [4:0] STATE_LOAD_MEM1_WAIT       = 5'd15;
  localparam logic [4:0] STATE_DRAIN_STAGE          = 5'd16;
  localparam logic [4:0] STATE_DRAIN_MEMORY         = 5'd17;
  localparam logic [4:0] STATE_POISONED             = 5'd18;

  logic [4:0] state;
  logic operation_restore;
  logic target_internal;
  logic [7:0] target_model;
  logic [9:0] word_index;
  logic [9:0] section_last_word;
  logic [9:0] active_first_word;
  logic [9:0] active_word_count;
  logic [15:0] first_memory_word;
  logic [31:0] transfer_word;
  logic [WAIT_WIDTH-1:0] wait_count;

  function automatic logic known_ramtype(input logic [7:0] value);
    case (value)
      V2_RAM_NONE,
      V2_RAM_SRAM_32K_A,
      V2_RAM_SRAM_32K_B,
      V2_RAM_SRAM_128K,
      V2_RAM_SRAM_256K,
      V2_RAM_SRAM_512K,
      V2_RAM_EEPROM_128,
      V2_RAM_EEPROM_2K,
      V2_RAM_EEPROM_1K: known_ramtype = 1'b1;
      default: known_ramtype = 1'b0;
    endcase
  endfunction

  function automatic logic [9:0] cart_active_word_count(
      input logic [7:0] value
  );
    case (value)
      V2_RAM_EEPROM_128: cart_active_word_count = 10'd32;
      V2_RAM_EEPROM_2K:  cart_active_word_count = 10'd512;
      V2_RAM_EEPROM_1K:  cart_active_word_count = 10'd256;
      default:            cart_active_word_count = 10'd0;
    endcase
  endfunction

  function automatic logic word_is_active(input logic [9:0] index);
    logic [10:0] active_end;
    begin
      active_end = {1'b0, active_first_word} +
                   {1'b0, active_word_count};
      word_is_active = active_word_count != 0 &&
                       index >= active_first_word &&
                       {1'b0, index} < active_end;
    end
  endfunction

  wire model_valid = model == V2_MODEL_MONO || model == V2_MODEL_COLOR;
  wire config_valid = model_valid && known_ramtype(ramtype);
  wire restore_tainted = operation_restore && write_may_have_committed;
  wire current_word_active = word_is_active(word_index);
  wire [10:0] active_end_word = {1'b0, active_first_word} +
                                {1'b0, active_word_count};
  wire current_word_is_last_active = active_word_count != 0 &&
      {1'b0, word_index} + 11'd1 == active_end_word;

  wire stage_issue = state == STATE_CAPTURE_STAGE_ISSUE ||
                     state == STATE_VALIDATE_STAGE_ISSUE ||
                     state == STATE_LOAD_STAGE_ISSUE;
  wire memory_issue = state == STATE_CAPTURE_MEM0_ISSUE ||
                      state == STATE_CAPTURE_MEM1_ISSUE ||
                      state == STATE_LOAD_MEM0_ISSUE ||
                      state == STATE_LOAD_MEM1_ISSUE;
  wire load_memory_issue = state == STATE_LOAD_MEM0_ISSUE ||
                           state == STATE_LOAD_MEM1_ISSUE;
  wire second_memory_half = state == STATE_CAPTURE_MEM1_ISSUE ||
                            state == STATE_CAPTURE_MEM1_WAIT ||
                            state == STATE_LOAD_MEM1_ISSUE ||
                            state == STATE_LOAD_MEM1_WAIT;

  wire [10:0] pair_local_address = {word_index, 1'b0};
  wire [10:0] mono_local_address =
      {word_index - 10'd512, 1'b0};
  wire [10:0] mapped_memory_address =
      target_internal && target_model == V2_MODEL_MONO ?
          11'd1024 + mono_local_address + second_memory_half :
          pair_local_address + second_memory_half;

  assign start_ready = state == STATE_IDLE && !busy && freeze && frozen_ack &&
                       !abort_request;
  assign poisoned = state == STATE_POISONED;
  assign ownership_retained = busy || poisoned;

  assign stage_req = stage_issue && busy && freeze && !abort_request;
  assign stage_write = stage_req && state == STATE_CAPTURE_STAGE_ISSUE;
  assign stage_offset =
      (target_internal ? P_INTERNAL_EEPROM : P_CART_EEPROM) +
      {20'd0, word_index, 2'b00};
  assign stage_write_data = transfer_word;

  assign mem_req = memory_issue && busy && freeze && !abort_request;
  assign mem_write = mem_req && load_memory_issue;
  assign mem_addr = mapped_memory_address;
  assign mem_write_data = second_memory_half ?
      {transfer_word[7:0], transfer_word[15:8]} :
      {transfer_word[23:16], transfer_word[31:24]};

  always @(posedge clk or negedge reset_n) begin
    if (!reset_n) begin
      frozen_ack <= 1'b0;
      busy <= 1'b0;
      done <= 1'b0;
      failed <= 1'b0;
      failure_reason <= EEPROM_WALK_FAILURE_NONE;
      writes_committed <= 1'b0;
      write_may_have_committed <= 1'b0;
      state <= STATE_IDLE;
      operation_restore <= 1'b0;
      target_internal <= 1'b0;
      target_model <= V2_MODEL_MONO;
      word_index <= 10'd0;
      section_last_word <= 10'd0;
      active_first_word <= 10'd0;
      active_word_count <= 10'd0;
      first_memory_word <= 16'd0;
      transfer_word <= 32'd0;
      wait_count <= {WAIT_WIDTH{1'b0}};
    end else begin
      done <= 1'b0;
      failed <= 1'b0;

      // Once a request is outstanding, acknowledgement is also the ownership
      // hold.  A caller may withdraw freeze to request cancellation, but must
      // not observe release until the request drains.  Poisoned transactions
      // retain the grant until reset because a timed-out response can arrive
      // arbitrarily late and a partial restore must never be resumed.
      if (freeze || ownership_retained)
        frozen_ack <= 1'b1;
      else
        frozen_ack <= 1'b0;

      // Abort/freeze release cancels before any not-yet-issued request. An
      // outstanding edge request is drained so its completion can never be
      // mistaken for a future operation.
      if (busy && (abort_request || !freeze) &&
          state != STATE_DRAIN_STAGE && state != STATE_DRAIN_MEMORY) begin
        failure_reason <= EEPROM_WALK_FAILURE_ABORT;
        wait_count <= {WAIT_WIDTH{1'b0}};
        if (state == STATE_CAPTURE_STAGE_WAIT ||
            state == STATE_VALIDATE_STAGE_WAIT ||
            state == STATE_LOAD_STAGE_WAIT) begin
          if (stage_ready) begin
            busy <= 1'b0;
            failed <= 1'b1;
            state <= restore_tainted ? STATE_POISONED : STATE_IDLE;
          end else begin
            state <= STATE_DRAIN_STAGE;
          end
        end else if (state == STATE_CAPTURE_MEM0_WAIT ||
                     state == STATE_CAPTURE_MEM1_WAIT ||
                     state == STATE_LOAD_MEM0_WAIT ||
                     state == STATE_LOAD_MEM1_WAIT) begin
          if (mem_ready) begin
            if ((state == STATE_LOAD_MEM0_WAIT ||
                 state == STATE_LOAD_MEM1_WAIT) && !mem_error)
              writes_committed <= 1'b1;
            busy <= 1'b0;
            failed <= 1'b1;
            state <= restore_tainted ? STATE_POISONED : STATE_IDLE;
          end else begin
            state <= STATE_DRAIN_MEMORY;
          end
        end else begin
          busy <= 1'b0;
          failed <= 1'b1;
          state <= restore_tainted ? STATE_POISONED : STATE_IDLE;
        end
      end else if (start && start_ready) begin
        failure_reason <= EEPROM_WALK_FAILURE_NONE;
        writes_committed <= 1'b0;
        write_may_have_committed <= 1'b0;
        wait_count <= {WAIT_WIDTH{1'b0}};
        if (!config_valid) begin
          busy <= 1'b0;
          failed <= 1'b1;
          failure_reason <= EEPROM_WALK_FAILURE_CONFIG;
          state <= STATE_IDLE;
        end else begin
          busy <= 1'b1;
          operation_restore <= restore;
          target_internal <= select_internal;
          target_model <= model;
          word_index <= 10'd0;
          section_last_word <= select_internal ? 10'd1023 : 10'd511;
          active_first_word <=
              select_internal && model == V2_MODEL_MONO ? 10'd512 : 10'd0;
          active_word_count <= select_internal ?
              (model == V2_MODEL_COLOR ? 10'd512 : 10'd32) :
              cart_active_word_count(ramtype);
          first_memory_word <= 16'd0;
          transfer_word <= 32'd0;
          state <= restore ? STATE_VALIDATE_STAGE_ISSUE :
                             STATE_CAPTURE_DISPATCH;
        end
      end else begin
        case (state)
          STATE_IDLE: begin
            busy <= 1'b0;
          end

          STATE_CAPTURE_DISPATCH: begin
            wait_count <= {WAIT_WIDTH{1'b0}};
            if (current_word_active) begin
              state <= STATE_CAPTURE_MEM0_ISSUE;
            end else begin
              transfer_word <= 32'd0;
              state <= STATE_CAPTURE_STAGE_ISSUE;
            end
          end

          STATE_CAPTURE_MEM0_ISSUE: begin
            wait_count <= {WAIT_WIDTH{1'b0}};
            state <= STATE_CAPTURE_MEM0_WAIT;
          end

          STATE_CAPTURE_MEM0_WAIT: begin
            if (mem_ready) begin
              wait_count <= {WAIT_WIDTH{1'b0}};
              if (mem_error) begin
                busy <= 1'b0;
                failed <= 1'b1;
                failure_reason <= EEPROM_WALK_FAILURE_MEMORY_BACKEND;
                state <= STATE_IDLE;
              end else begin
                first_memory_word <= mem_read_data;
                state <= STATE_CAPTURE_MEM1_ISSUE;
              end
            end else if (wait_count == WAIT_LAST) begin
              busy <= 1'b0;
              failed <= 1'b1;
              failure_reason <= EEPROM_WALK_FAILURE_MEMORY_TIMEOUT;
              state <= STATE_POISONED;
            end else begin
              wait_count <= wait_count + 1'b1;
            end
          end

          STATE_CAPTURE_MEM1_ISSUE: begin
            wait_count <= {WAIT_WIDTH{1'b0}};
            state <= STATE_CAPTURE_MEM1_WAIT;
          end

          STATE_CAPTURE_MEM1_WAIT: begin
            if (mem_ready) begin
              wait_count <= {WAIT_WIDTH{1'b0}};
              if (mem_error) begin
                busy <= 1'b0;
                failed <= 1'b1;
                failure_reason <= EEPROM_WALK_FAILURE_MEMORY_BACKEND;
                state <= STATE_IDLE;
              end else begin
                transfer_word <= {
                    first_memory_word[7:0], first_memory_word[15:8],
                    mem_read_data[7:0], mem_read_data[15:8]
                };
                state <= STATE_CAPTURE_STAGE_ISSUE;
              end
            end else if (wait_count == WAIT_LAST) begin
              busy <= 1'b0;
              failed <= 1'b1;
              failure_reason <= EEPROM_WALK_FAILURE_MEMORY_TIMEOUT;
              state <= STATE_POISONED;
            end else begin
              wait_count <= wait_count + 1'b1;
            end
          end

          STATE_CAPTURE_STAGE_ISSUE: begin
            wait_count <= {WAIT_WIDTH{1'b0}};
            state <= STATE_CAPTURE_STAGE_WAIT;
          end

          STATE_CAPTURE_STAGE_WAIT: begin
            if (stage_ready) begin
              wait_count <= {WAIT_WIDTH{1'b0}};
              if (stage_error) begin
                busy <= 1'b0;
                failed <= 1'b1;
                failure_reason <= EEPROM_WALK_FAILURE_STAGE_BACKEND;
                state <= STATE_IDLE;
              end else if (word_index == section_last_word) begin
                busy <= 1'b0;
                done <= 1'b1;
                state <= STATE_IDLE;
              end else begin
                word_index <= word_index + 1'b1;
                state <= STATE_CAPTURE_DISPATCH;
              end
            end else if (wait_count == WAIT_LAST) begin
              busy <= 1'b0;
              failed <= 1'b1;
              failure_reason <= EEPROM_WALK_FAILURE_STAGE_TIMEOUT;
              state <= STATE_POISONED;
            end else begin
              wait_count <= wait_count + 1'b1;
            end
          end

          STATE_VALIDATE_STAGE_ISSUE: begin
            wait_count <= {WAIT_WIDTH{1'b0}};
            state <= STATE_VALIDATE_STAGE_WAIT;
          end

          STATE_VALIDATE_STAGE_WAIT: begin
            if (stage_ready) begin
              wait_count <= {WAIT_WIDTH{1'b0}};
              if (stage_error) begin
                busy <= 1'b0;
                failed <= 1'b1;
                failure_reason <= EEPROM_WALK_FAILURE_STAGE_BACKEND;
                state <= STATE_IDLE;
              end else if (!current_word_active && stage_read_data != 0) begin
                busy <= 1'b0;
                failed <= 1'b1;
                failure_reason <= EEPROM_WALK_FAILURE_PADDING;
                state <= STATE_IDLE;
              end else if (word_index == section_last_word) begin
                if (active_word_count == 0) begin
                  busy <= 1'b0;
                  done <= 1'b1;
                  state <= STATE_IDLE;
                end else begin
                  word_index <= active_first_word;
                  state <= STATE_LOAD_STAGE_ISSUE;
                end
              end else begin
                word_index <= word_index + 1'b1;
                state <= STATE_VALIDATE_STAGE_ISSUE;
              end
            end else if (wait_count == WAIT_LAST) begin
              busy <= 1'b0;
              failed <= 1'b1;
              failure_reason <= EEPROM_WALK_FAILURE_STAGE_TIMEOUT;
              state <= STATE_POISONED;
            end else begin
              wait_count <= wait_count + 1'b1;
            end
          end

          STATE_LOAD_STAGE_ISSUE: begin
            wait_count <= {WAIT_WIDTH{1'b0}};
            state <= STATE_LOAD_STAGE_WAIT;
          end

          STATE_LOAD_STAGE_WAIT: begin
            if (stage_ready) begin
              wait_count <= {WAIT_WIDTH{1'b0}};
              if (stage_error) begin
                busy <= 1'b0;
                failed <= 1'b1;
                failure_reason <= EEPROM_WALK_FAILURE_STAGE_BACKEND;
                state <= restore_tainted ? STATE_POISONED : STATE_IDLE;
              end else begin
                transfer_word <= stage_read_data;
                state <= STATE_LOAD_MEM0_ISSUE;
              end
            end else if (wait_count == WAIT_LAST) begin
              busy <= 1'b0;
              failed <= 1'b1;
              failure_reason <= EEPROM_WALK_FAILURE_STAGE_TIMEOUT;
              state <= STATE_POISONED;
            end else begin
              wait_count <= wait_count + 1'b1;
            end
          end

          STATE_LOAD_MEM0_ISSUE: begin
            wait_count <= {WAIT_WIDTH{1'b0}};
            write_may_have_committed <= 1'b1;
            state <= STATE_LOAD_MEM0_WAIT;
          end

          STATE_LOAD_MEM0_WAIT: begin
            if (mem_ready) begin
              wait_count <= {WAIT_WIDTH{1'b0}};
              if (mem_error) begin
                busy <= 1'b0;
                failed <= 1'b1;
                failure_reason <= EEPROM_WALK_FAILURE_MEMORY_BACKEND;
                state <= STATE_POISONED;
              end else begin
                writes_committed <= 1'b1;
                state <= STATE_LOAD_MEM1_ISSUE;
              end
            end else if (wait_count == WAIT_LAST) begin
              busy <= 1'b0;
              failed <= 1'b1;
              failure_reason <= EEPROM_WALK_FAILURE_MEMORY_TIMEOUT;
              state <= STATE_POISONED;
            end else begin
              wait_count <= wait_count + 1'b1;
            end
          end

          STATE_LOAD_MEM1_ISSUE: begin
            wait_count <= {WAIT_WIDTH{1'b0}};
            write_may_have_committed <= 1'b1;
            state <= STATE_LOAD_MEM1_WAIT;
          end

          STATE_LOAD_MEM1_WAIT: begin
            if (mem_ready) begin
              wait_count <= {WAIT_WIDTH{1'b0}};
              if (mem_error) begin
                busy <= 1'b0;
                failed <= 1'b1;
                failure_reason <= EEPROM_WALK_FAILURE_MEMORY_BACKEND;
                state <= STATE_POISONED;
              end else begin
                writes_committed <= 1'b1;
                if (current_word_is_last_active) begin
                  busy <= 1'b0;
                  done <= 1'b1;
                  state <= STATE_IDLE;
                end else begin
                  word_index <= word_index + 1'b1;
                  state <= STATE_LOAD_STAGE_ISSUE;
                end
              end
            end else if (wait_count == WAIT_LAST) begin
              busy <= 1'b0;
              failed <= 1'b1;
              failure_reason <= EEPROM_WALK_FAILURE_MEMORY_TIMEOUT;
              state <= STATE_POISONED;
            end else begin
              wait_count <= wait_count + 1'b1;
            end
          end

          STATE_DRAIN_STAGE: begin
            if (stage_ready) begin
              busy <= 1'b0;
              failed <= 1'b1;
              wait_count <= {WAIT_WIDTH{1'b0}};
              state <= restore_tainted ? STATE_POISONED : STATE_IDLE;
            end else if (wait_count == WAIT_LAST) begin
              busy <= 1'b0;
              failed <= 1'b1;
              failure_reason <= EEPROM_WALK_FAILURE_STAGE_TIMEOUT;
              state <= STATE_POISONED;
            end else begin
              wait_count <= wait_count + 1'b1;
            end
          end

          STATE_DRAIN_MEMORY: begin
            if (mem_ready) begin
              if ((operation_restore) && !mem_error)
                writes_committed <= 1'b1;
              busy <= 1'b0;
              failed <= 1'b1;
              wait_count <= {WAIT_WIDTH{1'b0}};
              state <= restore_tainted ? STATE_POISONED : STATE_IDLE;
            end else if (wait_count == WAIT_LAST) begin
              busy <= 1'b0;
              failed <= 1'b1;
              failure_reason <= EEPROM_WALK_FAILURE_MEMORY_TIMEOUT;
              state <= STATE_POISONED;
            end else begin
              wait_count <= wait_count + 1'b1;
            end
          end

          STATE_POISONED: begin
            busy <= 1'b0;
          end

          default: begin
            busy <= 1'b0;
            failed <= 1'b1;
            failure_reason <= EEPROM_WALK_FAILURE_INTERNAL;
            state <= STATE_POISONED;
          end
        endcase
      end
    end
  end

  initial begin
    if (MAX_WAIT_CYCLES < 1)
      $error("MAX_WAIT_CYCLES must be at least one");
  end
endmodule

`default_nettype wire
