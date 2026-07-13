`timescale 1ns/1ps

// Frame/slot atomicity guard for APF scaler transitions.
//
// APF Set Scaler Slot EOL commands take effect on the next frame.  The slot
// emitted during the outgoing frame (`command_slot`) is therefore the slot
// expected on the frame beginning at the next scanout boundary.  A completed
// buffered candidate that needs another slot is deferred and protected for
// one frame: immutable history repeats while the new command is emitted, then
// the protected candidate is promoted at the following boundary.
//
// Direct mode has no immutable frame to repeat.  It fails closed to black from
// the instant the live/requested orientation no longer matches the applied
// slot until a matching command has crossed a complete APF frame boundary.
module apf_orientation_transition_guard (
    input  wire       clk,
    input  wire       reset,
    input  wire       frame_boundary,

    input  wire       buffered_mode,
    input  wire       current_frame_valid,
    input  wire       current_orientation,
    input  wire       producer_orientation,
    input  wire       candidate_valid,
    input  wire       candidate_orientation,

    input  wire [1:0] configured_orientation,
    input  wire       landscape_180,

    output wire       defer_candidate,
    output reg        protect_pending,
    output reg  [2:0] command_slot,
    output reg  [2:0] expected_applied_slot,
    output reg  [2:0] presentation_slot,
    output wire       blank_presentation
);
  localparam [2:0] SLOT_LANDSCAPE = 3'd0;
  localparam [2:0] SLOT_PORTRAIT = 3'd1;
  localparam [2:0] SLOT_LANDSCAPE_180 = 3'd2;

  function automatic [2:0] desired_slot;
    input intrinsic_vertical;
    input [1:0] orientation_setting;
    input flip_landscape;
    reg effective_vertical;
    begin
      effective_vertical =
          orientation_setting == 2'd2 ? 1'b1 :
          orientation_setting == 2'd1 ? 1'b0 : intrinsic_vertical;
      desired_slot = effective_vertical ? SLOT_PORTRAIT :
          flip_landscape ? SLOT_LANDSCAPE_180 : SLOT_LANDSCAPE;
    end
  endfunction

  wire [2:0] current_target_slot = desired_slot(
      current_orientation,
      configured_orientation,
      landscape_180
  );
  wire [2:0] producer_target_slot = desired_slot(
      producer_orientation,
      configured_orientation,
      landscape_180
  );
  wire [2:0] candidate_target_slot = desired_slot(
      candidate_orientation,
      configured_orientation,
      landscape_180
  );

  // This combinational decision is consumed by the framebank arbiter on the
  // same edge. The candidate is already complete, and command_slot is the EOL
  // command emitted throughout the outgoing APF frame.
  assign defer_candidate = frame_boundary && buffered_mode &&
      !protect_pending && candidate_valid &&
      candidate_target_slot != command_slot;

  reg frame_blank;
  // A direct->buffered transition may temporarily keep showing the live bank
  // while immutable history primes. Treat that interval like direct scanout:
  // if live orientation moves ahead of the applied slot, fail closed.
  assign blank_presentation = frame_blank ||
      ((!buffered_mode || !current_frame_valid) &&
       producer_target_slot != expected_applied_slot);

  always @(posedge clk) begin
    if (reset) begin
      protect_pending <= 1'b0;
      command_slot <= SLOT_LANDSCAPE;
      expected_applied_slot <= SLOT_LANDSCAPE;
      presentation_slot <= SLOT_LANDSCAPE;
      frame_blank <= 1'b1;
    end else if (frame_boundary) begin
      // The command sent during the outgoing frame is expected to own the
      // incoming frame. A new command assigned below cannot apply until the
      // boundary after that.
      expected_applied_slot <= command_slot;

      if (buffered_mode) begin
        if (protect_pending) begin
          if (candidate_valid) begin
            // The arbiter presents the protected pending bank while this state
            // is set. Its reserved slot is command_slot by construction.
            presentation_slot <= command_slot;
            protect_pending <= 1'b0;
            frame_blank <= 1'b0;
          end else begin
            // Ownership contract failure: retain protection and never expose
            // pixels whose bank/slot association cannot be proven.
            protect_pending <= 1'b1;
            frame_blank <= 1'b1;
          end
        end else if (candidate_valid) begin
          if (candidate_target_slot == command_slot) begin
            // The ordinary arbiter promotion and its applied scaler slot agree
            // on this edge, so the complete candidate is immediately safe.
            presentation_slot <= command_slot;
            protect_pending <= 1'b0;
            frame_blank <= 1'b0;
          end else begin
            // The arbiter holds the newest completed candidate. Existing
            // immutable history may adopt a previously scheduled setting slot
            // on this boundary, but the candidate waits for its own command.
            command_slot <= candidate_target_slot;
            protect_pending <= 1'b1;
            if (current_frame_valid) begin
              presentation_slot <= command_slot;
              frame_blank <= 1'b0;
            end else begin
              frame_blank <= 1'b1;
            end
          end
        end else begin
          // No completion: repeat immutable history. A menu-only transform can
          // use the same pixels, so adopt the command arriving on this boundary
          // and schedule the newest requested transform for the next one.
          if (current_frame_valid) begin
            presentation_slot <= command_slot;
            frame_blank <= 1'b0;
          end else begin
            frame_blank <= 1'b1;
          end
          if (current_target_slot != command_slot)
            command_slot <= current_target_slot;
        end
      end else begin
        // Direct scanout cannot reserve yesterday's pixels. Keep a valid APF
        // raster but make it black for the mismatched transition frame.
        protect_pending <= 1'b0;
        if (producer_target_slot == command_slot) begin
          presentation_slot <= command_slot;
          frame_blank <= 1'b0;
        end else begin
          command_slot <= producer_target_slot;
          frame_blank <= 1'b1;
        end
      end
    end
  end
endmodule
