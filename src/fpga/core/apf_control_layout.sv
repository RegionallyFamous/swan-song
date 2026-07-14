`timescale 1ns/1ps

// Pocket button-to-WonderSwan keypad mapping. The display pipeline continues
// to consume native_vertical directly; this override changes controls only.
module apf_control_layout (
    input  wire [1:0] configured_layout,
    input  wire       native_vertical,
    input  wire       button_a,
    input  wire       button_b,
    input  wire       button_x,
    input  wire       button_y,
    input  wire       button_trig_l,
    input  wire       button_trig_r,
    output wire       key_y1,
    output wire       key_y2,
    output wire       key_y3,
    output wire       key_y4,
    output wire       key_a,
    output wire       key_b
);
  // 0=Auto, 1=Horizontal, 2=Vertical. Treat every unadvertised encoding as
  // Auto so a stale or corrupt persisted value cannot force the wrong layout.
  wire controls_vertical =
      configured_layout == 2'd1 ? 1'b0 :
      configured_layout == 2'd2 ? 1'b1 :
      native_vertical;

  assign key_y1 = controls_vertical ? button_x : button_trig_l;
  assign key_y2 = controls_vertical ? button_a : button_trig_r;
  assign key_y3 = controls_vertical ? button_b : button_x;
  assign key_y4 = button_y;
  assign key_a = controls_vertical ? button_trig_l : button_a;
  assign key_b = controls_vertical ? button_trig_r : button_b;
endmodule
