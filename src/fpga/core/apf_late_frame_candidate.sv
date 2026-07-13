`timescale 1ns/1ps

// Isolated Phase-4 experiment; deliberately not instantiated by the core.
//
// The cadence places the 224x144 active image at the end of an exact-60-Hz
// 256x400 raster.  A completed-frame candidate is considered at y=256/x=0,
// nine pixel clocks before the first active pixel.  Only complete banks can
// enter this interface; unlike the rejected beam-race experiment, no future
// producer progress is assumed.
//
// APF scaler-slot commands carried after an active line take effect on the
// next frame.  `expected_applied_slot` therefore describes this frame, while
// `command_for_next_frame` is the value that must be emitted by this frame's
// end-of-line words.  A candidate with a different slot is reserved for the
// next frame and the current matching presentation is repeated.  Upstream
// must hold candidate_valid/data until candidate_take, and must not recycle a
// bank while scheduled_protect_valid names it.
module apf_late_frame_candidate #(
    parameter [8:0] H_TOTAL = 9'd256,
    parameter [8:0] V_TOTAL = 9'd400,
    parameter [8:0] ACTIVE_Y = 9'd256,
    parameter [8:0] ACTIVE_X = 9'd9,
    parameter [8:0] ACTIVE_WIDTH = 9'd224,
    parameter [8:0] ACTIVE_HEIGHT = 9'd144,
    parameter [8:0] HS_X = 9'd7,
    parameter [2:0] RESET_SLOT = 3'd0
) (
    input  wire       clk,
    input  wire       reset,
    input  wire       pixel_enable,

    input  wire       candidate_valid,
    input  wire [2:0] candidate_bank,
    input  wire [2:0] candidate_slot,
    output reg        candidate_take,

    output reg        presentation_valid,
    output reg  [2:0] presentation_bank,
    output reg  [2:0] presentation_slot,
    output reg  [2:0] expected_applied_slot,
    output reg  [2:0] command_for_next_frame,

    output reg        scheduled_valid,
    output reg  [2:0] scheduled_bank,
    output reg  [2:0] scheduled_slot,
    output wire       scheduled_protect_valid,
    output wire [2:0] scheduled_protect_bank,

    output reg        promotion_pulse,
    output reg        repeat_pulse,
    output reg        blank_pulse,
    output reg        orientation_deferred_pulse,

    output reg  [8:0] x,
    output reg  [8:0] y,
    output wire       line_end,
    output wire       frame_boundary,
    output wire       apf_vs_phase,
    output wire       apf_hs_phase,
    output wire       apf_de_phase,
    output wire       apf_eol_phase,
    output wire       late_selection
);
  localparam [8:0] H_LAST = H_TOTAL - 1'd1;
  localparam [8:0] V_LAST = V_TOTAL - 1'd1;
  localparam [8:0] ACTIVE_X_END = ACTIVE_X + ACTIVE_WIDTH;
  localparam [8:0] ACTIVE_Y_END = ACTIVE_Y + ACTIVE_HEIGHT;

  assign line_end = x == H_LAST;
  assign frame_boundary = pixel_enable && line_end && y == V_LAST;
  assign apf_vs_phase = pixel_enable && x == 9'd0 && y == 9'd0;
  assign apf_hs_phase = pixel_enable && x == HS_X;
  assign apf_de_phase = pixel_enable &&
      x >= ACTIVE_X && x < ACTIVE_X_END &&
      y >= ACTIVE_Y && y < ACTIVE_Y_END;
  assign apf_eol_phase = pixel_enable &&
      x == ACTIVE_X_END && y >= ACTIVE_Y && y < ACTIVE_Y_END;
  assign late_selection = pixel_enable && x == 9'd0 && y == ACTIVE_Y;

  assign scheduled_protect_valid = scheduled_valid;
  assign scheduled_protect_bank = scheduled_bank;

  // The exact cadence is intentionally local to the experiment.  Production
  // remains on apf_scanout_cadence until the Pocket/Dock hardware gates pass.
  always @(posedge clk) begin
    if (reset) begin
      x <= 9'd0;
      y <= 9'd0;
    end else if (pixel_enable) begin
      if (line_end) begin
        x <= 9'd0;
        if (y == V_LAST)
          y <= 9'd0;
        else
          y <= y + 1'd1;
      end else begin
        x <= x + 1'd1;
      end
    end
  end

  // Complete-frame selection and APF next-frame slot scheduling.
  always @(posedge clk) begin
    if (reset) begin
      candidate_take <= 1'b0;
      presentation_valid <= 1'b0;
      presentation_bank <= 3'd0;
      presentation_slot <= RESET_SLOT;
      expected_applied_slot <= RESET_SLOT;
      command_for_next_frame <= RESET_SLOT;
      scheduled_valid <= 1'b0;
      scheduled_bank <= 3'd0;
      scheduled_slot <= RESET_SLOT;
      promotion_pulse <= 1'b0;
      repeat_pulse <= 1'b0;
      blank_pulse <= 1'b0;
      orientation_deferred_pulse <= 1'b0;
    end else begin
      candidate_take <= 1'b0;
      promotion_pulse <= 1'b0;
      repeat_pulse <= 1'b0;
      blank_pulse <= 1'b0;
      orientation_deferred_pulse <= 1'b0;

      // The command emitted during the previous APF frame becomes the slot
      // expected to be applied after this boundary.
      if (frame_boundary)
        expected_applied_slot <= command_for_next_frame;

      if (late_selection) begin
        if (scheduled_valid) begin
          // A mismatched candidate was claimed one frame earlier and its slot
          // command has now had one complete APF frame in which to take effect.
          if (scheduled_slot == expected_applied_slot) begin
            presentation_valid <= 1'b1;
            presentation_bank <= scheduled_bank;
            presentation_slot <= scheduled_slot;
            scheduled_valid <= 1'b0;
            promotion_pulse <= 1'b1;
          end else begin
            // Fail closed if the expected-slot pipeline did not advance. Keep
            // the scheduled bank protected and issue its command once more.
            command_for_next_frame <= scheduled_slot;
            orientation_deferred_pulse <= 1'b1;
            if (presentation_valid &&
                presentation_slot == expected_applied_slot)
              repeat_pulse <= 1'b1;
            else
              blank_pulse <= 1'b1;
          end
        end else if (candidate_valid) begin
          candidate_take <= 1'b1;
          if (candidate_slot == expected_applied_slot) begin
            presentation_valid <= 1'b1;
            presentation_bank <= candidate_bank;
            presentation_slot <= candidate_slot;
            command_for_next_frame <= candidate_slot;
            promotion_pulse <= 1'b1;
          end else begin
            // Claim and protect the complete candidate while its slot command
            // is scheduled for the following APF frame.
            scheduled_valid <= 1'b1;
            scheduled_bank <= candidate_bank;
            scheduled_slot <= candidate_slot;
            command_for_next_frame <= candidate_slot;
            orientation_deferred_pulse <= 1'b1;
            if (presentation_valid &&
                presentation_slot == expected_applied_slot)
              repeat_pulse <= 1'b1;
            else
              blank_pulse <= 1'b1;
          end
        end else begin
          // No completion is normal when a 75.47-Hz producer is converted to
          // 60 Hz or while production is paused. Repeat only a slot-matched,
          // complete presentation; otherwise output must remain blank.
          if (presentation_valid &&
              presentation_slot == expected_applied_slot)
            repeat_pulse <= 1'b1;
          else
            blank_pulse <= 1'b1;
        end
      end
    end
  end
endmodule
