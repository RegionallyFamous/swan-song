`timescale 1ns/1ps

// Select implements the inherited hold-or-tap Fast Forward gesture, with an
// explicit lifecycle clear.  The physical-input guard holds clear_state high
// through PocketOS focus loss and until PAD has returned to neutral.
module apf_fast_forward_control #(
    parameter integer HOLD_CYCLES = 6_400_000
) (
    input  wire clk,
    input  wire reset_n,
    input  wire clear_state,
    input  wire button_select,
    output wire fast_forward
);

  localparam integer COUNTER_WIDTH =
      HOLD_CYCLES < 2 ? 1 : $clog2(HOLD_CYCLES + 1);
  localparam [COUNTER_WIDTH-1:0] HOLD_THRESHOLD =
      COUNTER_WIDTH'(HOLD_CYCLES - 1);

  reg [COUNTER_WIDTH-1:0] press_cycles;
  reg button_was_down;
  reg press_was_long;
  reg suppress_short_latch;
  reg fast_forward_latched;

  wire hold_threshold_reached = press_cycles >= HOLD_THRESHOLD;

  always @(posedge clk) begin
    if (!reset_n || clear_state) begin
      press_cycles <= {COUNTER_WIDTH{1'b0}};
      button_was_down <= 1'b0;
      press_was_long <= 1'b0;
      suppress_short_latch <= 1'b0;
      fast_forward_latched <= 1'b0;
    end else begin
      button_was_down <= button_select;

      if (!button_was_down && button_select) begin
        press_cycles <= {{(COUNTER_WIDTH-1){1'b0}}, 1'b1};
        press_was_long <= HOLD_CYCLES <= 1;
        suppress_short_latch <= fast_forward_latched;
        fast_forward_latched <= 1'b0;
      end else if (button_select) begin
        if (!press_was_long) begin
          if (hold_threshold_reached)
            press_was_long <= 1'b1;
          else
            press_cycles <= press_cycles + 1'b1;
        end
      end else if (button_was_down) begin
        if (!press_was_long && !suppress_short_latch)
          fast_forward_latched <= 1'b1;
        press_cycles <= {COUNTER_WIDTH{1'b0}};
        press_was_long <= 1'b0;
        suppress_short_latch <= 1'b0;
      end
    end
  end

  assign fast_forward = reset_n && !clear_state &&
                        (button_select || fast_forward_latched);

endmodule
