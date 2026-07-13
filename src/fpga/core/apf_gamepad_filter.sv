// Fail-closed APF controller classification.
//
// The official PAD key word carries its device class in bits [31:28].  Only
// Pocket buttons (1), a digital Dock gamepad (2), and an analog-capable Dock
// gamepad (3) share the digital gamepad layout in bits [15:0].  Keyboard,
// mouse, absent, and reserved packet classes must never reach console input.
module apf_gamepad_filter (
    input  wire        clk,
    input  wire        reset_n,
    input  wire [31:0] key_word,
    output reg  [15:0] buttons
);

  localparam [3:0] TYPE_POCKET = 4'h1;
  localparam [3:0] TYPE_DOCK_DIGITAL = 4'h2;
  localparam [3:0] TYPE_DOCK_ANALOG = 4'h3;

  always @(posedge clk) begin
    if (!reset_n) begin
      buttons <= 16'd0;
    end else begin
      case (key_word[31:28])
        TYPE_POCKET,
        TYPE_DOCK_DIGITAL,
        TYPE_DOCK_ANALOG: buttons <= key_word[15:0];
        default: buttons <= 16'd0;
      endcase
    end
  end

endmodule
