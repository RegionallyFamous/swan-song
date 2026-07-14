// Fail-closed APF controller classification.
//
// The official PAD key word carries its device class in bits [31:28].  Only
// Pocket buttons (1), a digital Dock gamepad (2), and an analog-capable Dock
// gamepad (3) share the digital gamepad layout in bits [15:0].  Keyboard,
// mouse, absent, and reserved packet classes must never reach console input.
module apf_gamepad_filter (
    input  wire        clk,
    input  wire        reset_n,
    input  wire        os_focus_lost,
    input  wire        key_word_updated,
    input  wire [31:0] key_word,
    output reg  [15:0] buttons,
    output reg         input_blocked
);

  localparam [3:0] TYPE_POCKET = 4'h1;
  localparam [3:0] TYPE_DOCK_DIGITAL = 4'h2;
  localparam [3:0] TYPE_DOCK_ANALOG = 4'h3;

  reg wait_for_neutral;

  wire valid_gamepad = key_word[31:28] == TYPE_POCKET ||
                       key_word[31:28] == TYPE_DOCK_DIGITAL ||
                       key_word[31:28] == TYPE_DOCK_ANALOG;
  wire neutral_gamepad = valid_gamepad && key_word[15:0] == 16'd0;

  always @(posedge clk) begin
    if (!reset_n) begin
      buttons <= 16'd0;
      wait_for_neutral <= 1'b0;
      input_blocked <= 1'b1;
    end else if (os_focus_lost) begin
      // PocketOS owns every physical control while its menu has focus.  Keep
      // the guard armed until a real type-1/2/3 PAD packet reports neutral;
      // disconnect, keyboard, mouse, and reserved packets cannot rearm it.
      buttons <= 16'd0;
      wait_for_neutral <= 1'b1;
      input_blocked <= 1'b1;
    end else if (wait_for_neutral) begin
      buttons <= 16'd0;
      if (key_word_updated && neutral_gamepad) begin
        wait_for_neutral <= 1'b0;
        input_blocked <= 1'b0;
      end else begin
        input_blocked <= 1'b1;
      end
    end else begin
      case (key_word[31:28])
        TYPE_POCKET,
        TYPE_DOCK_DIGITAL,
        TYPE_DOCK_ANALOG: begin
          buttons <= key_word[15:0];
          input_blocked <= 1'b0;
        end
        default: begin
          buttons <= 16'd0;
          input_blocked <= 1'b0;
        end
      endcase
    end
  end

endmodule
