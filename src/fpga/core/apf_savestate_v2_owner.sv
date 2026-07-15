`timescale 1ns/1ps
`default_nettype none

// Atomic control-plane owner for the future Memories-v2 data path.
//
// This module is intentionally isolated from ap_core.qsf. All inputs are
// synchronous to clk; production CDC adapters must provide level/toggle
// handshakes. The owner establishes the only legal window in which a validated
// staged image may touch live emulated state:
//
//   pause at an instruction/HALT boundary -> observe one full SDRAM drain ->
//   freeze devices -> acquire the staging channel -> run one data-plane op.
//
// Global sdram_quiescent is deliberately sampled only before stage ownership.
// Legitimate staging traffic and refresh deassert it later. The data plane has
// its own quiescent acknowledgement, which must cover every issued physical
// request and late completion before ownership is released.
//
// Capture failures are recoverable because only isolated staging storage was
// changed. Restore apply_start is the irreversible barrier: any error, cancel,
// timeout, or validated-generation change after that point asserts
// fatal_reset_hold until lifecycle_reset_n is cleared by a clean title/PLL
// lifecycle reset. Never feed fatal_reset_hold back into lifecycle_reset_n.
module apf_savestate_v2_owner #(
    parameter integer DEVICE_COUNT = 3,
    // The one-cycle default is deliberately unusable for production.
    // Integration must replace it with a bound derived from the complete
    // walkers, SDRAM refresh/arbitration, CDC latency, and abort drains.
    parameter integer MAX_PHASE_CYCLES = 1
) (
    input  wire                    clk,
    input  wire                    lifecycle_reset_n,

    input  wire                    capture_request,
    input  wire                    restore_request,
    input  wire                    staged_image_valid,
    input  wire [31:0]             staged_image_generation,
    input  wire                    cancel,

    output reg                     capture_busy,
    output reg                     capture_done,
    output reg                     capture_failed,
    output reg                     restore_busy,
    output reg                     restore_done,
    output reg                     restore_failed,
    output reg                     protocol_error,
    output reg                     fatal_reset_hold,

    // Blocks offset-zero replacement and every host stage write while either
    // operation owns the payload. For restore it also protects the captured
    // staged_image_generation. The bridge frontend must enforce this level.
    output wire                    staged_image_lock,

    // runtime_pause_ack must remain high until runtime_pause_request falls,
    // and must fall only after the gated runtime is ready to execute again.
    output wire                    runtime_pause_request,
    input  wire                    runtime_pause_ack,

    // Full physical drain before exclusive stage ownership. This is not a
    // continuous invariant once the staging client starts issuing requests.
    input  wire                    sdram_quiescent,

    // RTC plus internal/cartridge EEPROM controller boundaries.  Raw frozen
    // acknowledgements are never forged.  device_settling may retain an
    // already-acquired device only while a proved load-settle guard covers an
    // intentional raw-ack gap; release still requires every raw ack high and
    // every settling bit low.  device_protocol_fault is sticky at its source.
    output wire                    device_freeze,
    input  wire [DEVICE_COUNT-1:0] device_frozen,
    input  wire [DEVICE_COUNT-1:0] device_settling,
    input  wire                    device_protocol_fault,

    // Exclusive ownership of the payload staging SDRAM range.
    output wire                    stage_acquire,
    input  wire                    stage_granted,

    // Data-plane starts are one-cycle pulses. Terminal inputs may pulse or be
    // held, but must be low before start and cannot arise combinationally from
    // start. datapath_quiescent covers all physical requests and late replies.
    output reg                     capture_start,
    input  wire                    capture_complete,
    input  wire                    capture_error,
    output reg                     restore_apply_start,
    input  wire                    restore_apply_complete,
    input  wire                    restore_apply_error,
    output wire                    datapath_abort,
    input  wire                    datapath_quiescent
);
  localparam [3:0] STATE_IDLE            = 4'd0;
  localparam [3:0] STATE_WAIT_PAUSE      = 4'd1;
  localparam [3:0] STATE_WAIT_QUIESCE    = 4'd2;
  localparam [3:0] STATE_WAIT_STAGE      = 4'd3;
  localparam [3:0] STATE_ACTIVE          = 4'd4;
  localparam [3:0] STATE_FINISH_DRAIN    = 4'd5;
  localparam [3:0] STATE_ABORT_DRAIN     = 4'd6;
  localparam [3:0] STATE_RELEASE_STAGE   = 4'd7;
  localparam [3:0] STATE_RELEASE_DEVICES = 4'd8;
  localparam [3:0] STATE_RELEASE_RUNTIME = 4'd9;
  localparam [3:0] STATE_FATAL_RELEASE   = 4'd10;
  localparam [3:0] STATE_FATAL           = 4'd11;

  reg [3:0] state;
  reg restore_operation;
  reg datapath_started;
  reg pending_failure;
  reg fatal_after_apply;
  reg [31:0] accepted_generation;
  integer wait_cycles;

  wire all_devices_frozen = &device_frozen;
  wire any_device_settling = |device_settling;
  wire all_devices_retained = &(device_frozen | device_settling);
  wire all_devices_settled = all_devices_frozen && !any_device_settling;
  wire no_devices_frozen = ~|device_frozen;
  wire generation_current = staged_image_valid &&
                            staged_image_generation == accepted_generation;
  wire wait_timeout = MAX_PHASE_CYCLES > 0 &&
                      wait_cycles >= MAX_PHASE_CYCLES - 1;
  wire any_terminal = capture_complete || capture_error ||
                      restore_apply_complete || restore_apply_error;
  wire prestart_terminal = (state == STATE_WAIT_PAUSE ||
                            state == STATE_WAIT_QUIESCE ||
                            state == STATE_WAIT_STAGE) && any_terminal;
  wire current_error = restore_operation ? restore_apply_error : capture_error;
  wire current_complete = restore_operation ? restore_apply_complete :
                                                capture_complete;
  wire wrong_operation_terminal = restore_operation ?
      (capture_complete || capture_error) :
      (restore_apply_complete || restore_apply_error);

  assign staged_image_lock = state != STATE_IDLE;
  assign runtime_pause_request = state != STATE_IDLE &&
                                 state != STATE_RELEASE_RUNTIME;
  assign device_freeze = state == STATE_WAIT_QUIESCE ||
                         state == STATE_WAIT_STAGE ||
                         state == STATE_ACTIVE ||
                         state == STATE_FINISH_DRAIN ||
                         state == STATE_ABORT_DRAIN ||
                         state == STATE_RELEASE_STAGE ||
                         state == STATE_FATAL_RELEASE ||
                         state == STATE_FATAL;
  assign stage_acquire = state == STATE_WAIT_STAGE ||
                         state == STATE_ACTIVE ||
                         state == STATE_FINISH_DRAIN ||
                         state == STATE_ABORT_DRAIN;
  assign datapath_abort = state == STATE_ABORT_DRAIN;

  always @(posedge clk or negedge lifecycle_reset_n) begin
    if (!lifecycle_reset_n) begin
      state <= STATE_IDLE;
      restore_operation <= 1'b0;
      datapath_started <= 1'b0;
      pending_failure <= 1'b0;
      fatal_after_apply <= 1'b0;
      accepted_generation <= 32'd0;
      wait_cycles <= 0;
      capture_busy <= 1'b0;
      capture_done <= 1'b0;
      capture_failed <= 1'b0;
      restore_busy <= 1'b0;
      restore_done <= 1'b0;
      restore_failed <= 1'b0;
      protocol_error <= 1'b0;
      fatal_reset_hold <= 1'b0;
      capture_start <= 1'b0;
      restore_apply_start <= 1'b0;
    end else begin
      capture_start <= 1'b0;
      restore_apply_start <= 1'b0;

      // Commands while another transaction owns the machine are ignored and
      // recorded; they never replace the captured generation or active op.
      if (state != STATE_IDLE && (capture_request || restore_request))
        protocol_error <= 1'b1;

      if (state != STATE_IDLE && device_protocol_fault)
        protocol_error <= 1'b1;

      // A pulse from a prior transaction cannot be allowed to disappear while
      // the new transaction is still acquiring its atomic window. Likewise,
      // a terminal for the inactive operation is proof that the data-plane/CDC
      // contract has been violated. The state-specific branches below abort
      // the transaction; this decode makes the diagnostic sticky even when a
      // simultaneous cancel or timeout wins the main failure branch.
      if (prestart_terminal ||
          ((state == STATE_ACTIVE || state == STATE_FINISH_DRAIN ||
            state == STATE_ABORT_DRAIN) && wrong_operation_terminal))
        protocol_error <= 1'b1;

      case (state)
        STATE_IDLE: begin
          wait_cycles <= 0;
          capture_busy <= 1'b0;
          restore_busy <= 1'b0;
          datapath_started <= 1'b0;
          pending_failure <= 1'b0;
          fatal_after_apply <= 1'b0;

          if (capture_request && restore_request) begin
            protocol_error <= 1'b1;
            capture_done <= 1'b0;
            restore_done <= 1'b0;
            capture_failed <= 1'b1;
            restore_failed <= 1'b1;
          end else if (capture_request) begin
            capture_done <= 1'b0;
            capture_failed <= 1'b0;
            restore_done <= 1'b0;
            restore_failed <= 1'b0;
            restore_operation <= 1'b0;
            if (any_terminal || device_protocol_fault ||
                any_device_settling) begin
              protocol_error <= 1'b1;
              capture_failed <= 1'b1;
            end else begin
              capture_busy <= 1'b1;
              state <= STATE_WAIT_PAUSE;
            end
          end else if (restore_request) begin
            capture_done <= 1'b0;
            capture_failed <= 1'b0;
            restore_done <= 1'b0;
            restore_failed <= 1'b0;
            restore_operation <= 1'b1;
            accepted_generation <= staged_image_generation;
            if (any_terminal || device_protocol_fault ||
                any_device_settling) begin
              protocol_error <= 1'b1;
              restore_failed <= 1'b1;
            end else if (!staged_image_valid) begin
              restore_failed <= 1'b1;
            end else begin
              restore_busy <= 1'b1;
              state <= STATE_WAIT_PAUSE;
            end
          end
        end

        STATE_WAIT_PAUSE: begin
          wait_cycles <= wait_cycles + 1;
          if (prestart_terminal || device_protocol_fault ||
              any_device_settling || cancel ||
              (restore_operation && !generation_current) ||
              wait_timeout) begin
            pending_failure <= 1'b1;
            fatal_after_apply <= 1'b0;
            wait_cycles <= 0;
            // A device guard fault/settle indication is categorically
            // different from a stale terminal, cancel, or staged-generation
            // change: it means a live device may already have accepted a
            // load/reset.  Never resume that machine, even though the normal
            // data-plane start barrier has not yet been crossed.
            if (device_protocol_fault || any_device_settling) begin
              if (restore_operation) begin
                restore_busy <= 1'b0;
                restore_failed <= 1'b1;
              end else begin
                capture_busy <= 1'b0;
                capture_failed <= 1'b1;
              end
              fatal_reset_hold <= 1'b1;
            end
            state <= STATE_ABORT_DRAIN;
          end else if (runtime_pause_ack) begin
            wait_cycles <= 0;
            state <= STATE_WAIT_QUIESCE;
          end
        end

        STATE_WAIT_QUIESCE: begin
          wait_cycles <= wait_cycles + 1;
          if (prestart_terminal || device_protocol_fault ||
              any_device_settling || cancel ||
              (restore_operation && !generation_current) ||
              !runtime_pause_ack || wait_timeout) begin
            pending_failure <= 1'b1;
            fatal_after_apply <= 1'b0;
            wait_cycles <= 0;
            if (device_protocol_fault || any_device_settling) begin
              if (restore_operation) begin
                restore_busy <= 1'b0;
                restore_failed <= 1'b1;
              end else begin
                capture_busy <= 1'b0;
                capture_failed <= 1'b1;
              end
              fatal_reset_hold <= 1'b1;
            end
            state <= STATE_ABORT_DRAIN;
          end else if (sdram_quiescent && all_devices_frozen) begin
            wait_cycles <= 0;
            state <= STATE_WAIT_STAGE;
          end
        end

        STATE_WAIT_STAGE: begin
          wait_cycles <= wait_cycles + 1;
          if (prestart_terminal || device_protocol_fault ||
              any_device_settling || cancel ||
              (restore_operation && !generation_current) ||
              !runtime_pause_ack || !all_devices_frozen || wait_timeout) begin
            pending_failure <= 1'b1;
            fatal_after_apply <= 1'b0;
            wait_cycles <= 0;
            if (device_protocol_fault || any_device_settling) begin
              if (restore_operation) begin
                restore_busy <= 1'b0;
                restore_failed <= 1'b1;
              end else begin
                capture_busy <= 1'b0;
                capture_failed <= 1'b1;
              end
              fatal_reset_hold <= 1'b1;
            end
            state <= STATE_ABORT_DRAIN;
          end else if (stage_granted && datapath_quiescent) begin
            wait_cycles <= 0;
            if (restore_operation) begin
              restore_apply_start <= 1'b1;
              fatal_after_apply <= 1'b1;
            end else begin
              capture_start <= 1'b1;
            end
            datapath_started <= 1'b1;
            state <= STATE_ACTIVE;
          end
        end

        STATE_ACTIVE: begin
          wait_cycles <= wait_cycles + 1;
          if (!runtime_pause_ack || !all_devices_retained || !stage_granted ||
              device_protocol_fault ||
              (!restore_operation && any_device_settling) ||
              (restore_operation && !generation_current) || cancel ||
              wrong_operation_terminal || wait_timeout) begin
            pending_failure <= 1'b1;
            wait_cycles <= 0;
            if ((restore_operation && fatal_after_apply) ||
                device_protocol_fault ||
                (!restore_operation && any_device_settling)) begin
              if (restore_operation) begin
                restore_busy <= 1'b0;
                restore_failed <= 1'b1;
              end else begin
                capture_busy <= 1'b0;
                capture_failed <= 1'b1;
              end
              fatal_reset_hold <= 1'b1;
            end
            state <= STATE_ABORT_DRAIN;
          end else if (current_error) begin
            pending_failure <= 1'b1;
            wait_cycles <= 0;
            if (restore_operation) begin
              restore_busy <= 1'b0;
              restore_failed <= 1'b1;
              fatal_reset_hold <= 1'b1;
            end
            state <= STATE_ABORT_DRAIN;
          end else if (current_complete) begin
            wait_cycles <= 0;
            if (datapath_quiescent && all_devices_settled)
              state <= STATE_RELEASE_STAGE;
            else
              state <= STATE_FINISH_DRAIN;
          end
        end

        STATE_FINISH_DRAIN: begin
          wait_cycles <= wait_cycles + 1;
          if (!runtime_pause_ack || !all_devices_retained || !stage_granted ||
              device_protocol_fault ||
              (!restore_operation && any_device_settling) ||
              (restore_operation && !generation_current) || cancel ||
              wrong_operation_terminal || wait_timeout) begin
            pending_failure <= 1'b1;
            wait_cycles <= 0;
            if ((restore_operation && fatal_after_apply) ||
                device_protocol_fault ||
                (!restore_operation && any_device_settling)) begin
              if (restore_operation) begin
                restore_busy <= 1'b0;
                restore_failed <= 1'b1;
              end else begin
                capture_busy <= 1'b0;
                capture_failed <= 1'b1;
              end
              fatal_reset_hold <= 1'b1;
            end
            state <= STATE_ABORT_DRAIN;
          end else if (current_error) begin
            // A completion may legally precede the last physical response.
            // Any error reported during that final drain supersedes success,
            // including an error coincident with datapath_quiescent.
            pending_failure <= 1'b1;
            wait_cycles <= 0;
            if (restore_operation) begin
              restore_busy <= 1'b0;
              restore_failed <= 1'b1;
              fatal_reset_hold <= 1'b1;
            end
            state <= STATE_ABORT_DRAIN;
          end else if (datapath_quiescent && all_devices_settled) begin
            wait_cycles <= 0;
            state <= STATE_RELEASE_STAGE;
          end
        end

        STATE_ABORT_DRAIN: begin
          wait_cycles <= wait_cycles + 1;
          // A pre-start raw-ack drop can move WAIT_STAGE into abort on the
          // same edge that its guard registers the causal reset fault.  Catch
          // that one-cycle-later proof here: once device ownership acquisition
          // has begun, a guard fault/settle window can never be downgraded to a
          // recoverable abort or followed by runtime release.
          if (device_protocol_fault || any_device_settling) begin
            protocol_error <= 1'b1;
            pending_failure <= 1'b1;
            capture_busy <= 1'b0;
            restore_busy <= 1'b0;
            if (restore_operation)
              restore_failed <= 1'b1;
            else
              capture_failed <= 1'b1;
            fatal_reset_hold <= 1'b1;
          end
          // datapath_abort remains asserted by state decode until every
          // outstanding request and late completion has drained.
          if (datapath_quiescent) begin
            wait_cycles <= 0;
            if (fatal_reset_hold || device_protocol_fault ||
                any_device_settling)
              state <= STATE_FATAL_RELEASE;
            else
              state <= STATE_RELEASE_STAGE;
          end else if (wait_timeout) begin
            // Do not revoke routing for a request that may still complete.
            // A restore is already fatal; a capture becomes fatal because the
            // physical ownership boundary itself can no longer be proven.
            capture_busy <= 1'b0;
            restore_busy <= 1'b0;
            if (restore_operation)
              restore_failed <= 1'b1;
            else
              capture_failed <= 1'b1;
            fatal_reset_hold <= 1'b1;
            wait_cycles <= 0;
          end
        end

        STATE_RELEASE_STAGE: begin
          wait_cycles <= wait_cycles + 1;
          if (device_protocol_fault || any_device_settling ||
              (datapath_started && !all_devices_settled)) begin
            // stage_acquire is already low in this state. A completion racing
            // EEPROM reset therefore must never jump back to ABORT_DRAIN and
            // reassert acquisition after the mux has started releasing. The
            // data plane was proven quiescent before entry: keep runtime and
            // devices frozen, continue requesting stage release, and enter
            // the fatal hold without a release/reacquire pulse.
            protocol_error <= 1'b1;
            pending_failure <= 1'b1;
            capture_busy <= 1'b0;
            restore_busy <= 1'b0;
            if (restore_operation)
              restore_failed <= 1'b1;
            else
              capture_failed <= 1'b1;
            fatal_reset_hold <= 1'b1;
            wait_cycles <= 0;
            state <= STATE_FATAL_RELEASE;
          end else if (!stage_granted) begin
            wait_cycles <= 0;
            state <= STATE_RELEASE_DEVICES;
          end else if (wait_timeout) begin
            capture_busy <= 1'b0;
            restore_busy <= 1'b0;
            if (restore_operation)
              restore_failed <= 1'b1;
            else
              capture_failed <= 1'b1;
            fatal_reset_hold <= 1'b1;
            state <= STATE_FATAL;
          end
        end

        STATE_RELEASE_DEVICES: begin
          wait_cycles <= wait_cycles + 1;
          if (no_devices_frozen) begin
            wait_cycles <= 0;
            state <= STATE_RELEASE_RUNTIME;
          end else if (wait_timeout) begin
            capture_busy <= 1'b0;
            restore_busy <= 1'b0;
            if (restore_operation)
              restore_failed <= 1'b1;
            else
              capture_failed <= 1'b1;
            fatal_reset_hold <= 1'b1;
            state <= STATE_FATAL;
          end
        end

        STATE_RELEASE_RUNTIME: begin
          wait_cycles <= wait_cycles + 1;
          if (!runtime_pause_ack) begin
            wait_cycles <= 0;
            if (restore_operation) begin
              restore_busy <= 1'b0;
              if (pending_failure)
                restore_failed <= 1'b1;
              else
                restore_done <= 1'b1;
            end else begin
              capture_busy <= 1'b0;
              if (pending_failure)
                capture_failed <= 1'b1;
              else
                capture_done <= 1'b1;
            end
            state <= STATE_IDLE;
          end else if (wait_timeout) begin
            capture_busy <= 1'b0;
            restore_busy <= 1'b0;
            if (restore_operation)
              restore_failed <= 1'b1;
            else
              capture_failed <= 1'b1;
            fatal_reset_hold <= 1'b1;
            state <= STATE_FATAL;
          end
        end

        STATE_FATAL_RELEASE: begin
          wait_cycles <= wait_cycles + 1;
          // Runtime and devices stay frozen forever, but release a proven-idle
          // stage channel so the physical mux cannot route a late response to
          // a future transaction after lifecycle reset.
          if (!stage_granted) begin
            wait_cycles <= 0;
            state <= STATE_FATAL;
          end else if (wait_timeout) begin
            wait_cycles <= 0;
            state <= STATE_FATAL;
          end
        end

        STATE_FATAL: begin
          wait_cycles <= 0;
          fatal_reset_hold <= 1'b1;
          capture_busy <= 1'b0;
          restore_busy <= 1'b0;
        end

        default: begin
          protocol_error <= 1'b1;
          fatal_reset_hold <= 1'b1;
          capture_busy <= 1'b0;
          restore_busy <= 1'b0;
          state <= STATE_FATAL;
        end
      endcase
    end
  end

  initial begin
    if (DEVICE_COUNT < 1)
      $error("DEVICE_COUNT must be positive");
    if (MAX_PHASE_CYCLES < 1)
      $error("MAX_PHASE_CYCLES must be set from a derived positive bound");
  end
endmodule

`default_nettype wire
