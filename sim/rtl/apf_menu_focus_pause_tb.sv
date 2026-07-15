`timescale 1ns/1ps

// End-to-end focus ownership test across the two intentionally independent
// CDCs.  Menu pause follows raw 00B0 state; physical input and Fast Forward do
// not rearm until a later fresh neutral PAD packet.
module apf_menu_focus_pause_tb;
  localparam [3:0] TYPE_POCKET = 4'h1;

  reg clk_74a = 1'b0;
  reg clk_sys = 1'b0;
  always #5 clk_74a = ~clk_74a;
  always #7 clk_sys = ~clk_sys;

  reg reset_n = 1'b0;
  reg osnotify_inmenu = 1'b0;
  reg key_word_updated = 1'b0;
  reg [31:0] key_word = 32'd0;

  wire [15:0] buttons_74a;
  wire input_blocked_74a;
  wire [15:0] buttons_sys;
  wire input_blocked_sys;
  wire menu_focus_sys;
  wire fast_forward;

  apf_gamepad_filter gamepad_filter (
      .clk(clk_74a),
      .reset_n(reset_n),
      .os_focus_lost(osnotify_inmenu),
      .key_word_updated(key_word_updated),
      .key_word(key_word),
      .buttons(buttons_74a),
      .input_blocked(input_blocked_74a)
  );

  apf_input_blocked_cdc input_state_system_cdc (
      .clk_source(clk_74a),
      .clk_destination(clk_sys),
      .reset_n_async(reset_n),
      .buttons_source(buttons_74a),
      .input_blocked_source(input_blocked_74a),
      .buttons_destination(buttons_sys),
      .input_blocked_destination(input_blocked_sys)
  );

  apf_menu_focus_cdc menu_focus_system_cdc (
      .clk_destination(clk_sys),
      .reset_n_async(reset_n),
      .menu_focus_source(osnotify_inmenu),
      .menu_focus_destination(menu_focus_sys)
  );

  apf_fast_forward_control #(
      .HOLD_CYCLES(8)
  ) fast_forward_control (
      .clk(clk_sys),
      .reset_n(reset_n),
      .clear_state(input_blocked_sys),
      .button_select(buttons_sys[14]),
      .fast_forward(fast_forward)
  );

  task automatic send_pad(input [15:0] buttons);
    begin
      @(negedge clk_74a);
      key_word = {TYPE_POCKET, 12'd0, buttons};
      key_word_updated = 1'b1;
      @(negedge clk_74a);
      key_word_updated = 1'b0;
    end
  endtask

  task automatic wait_sys_state(
      input bit expected_focus,
      input bit expected_blocked,
      input string message
  );
    integer edges;
    begin
      edges = 0;
      while ({menu_focus_sys, input_blocked_sys} !==
             {expected_focus, expected_blocked} && edges < 32) begin
        @(posedge clk_sys);
        #1ps;
        edges = edges + 1;
      end
      if ({menu_focus_sys, input_blocked_sys} !==
          {expected_focus, expected_blocked})
        $fatal(1, "%s: focus/blocked=%b%b", message,
               menu_focus_sys, input_blocked_sys);
    end
  endtask

  initial begin
    #3 reset_n = 1'b1;

    // Start from a fresh neutral sample, then hold Select to establish active
    // Fast Forward before PocketOS takes focus.
    send_pad(16'h0000);
    wait_sys_state(1'b0, 1'b0, "neutral startup did not rearm input");
    send_pad(16'h4000);
    repeat (8) @(posedge clk_sys);
    #1ps;
    if (!fast_forward)
      $fatal(1, "Select did not establish Fast Forward before menu entry");

    // 00B0 assertion drives both policies: the dedicated level pauses the
    // console, while the physical path atomically blocks/zeros controls.
    @(negedge clk_74a);
    osnotify_inmenu = 1'b1;
    wait_sys_state(1'b1, 1'b1, "menu entry did not pause and block input");
    if (buttons_sys !== 16'h0000 || fast_forward !== 1'b0)
      $fatal(1, "menu entry did not zero buttons and clear Fast Forward");

    // Menu exit must release pause even though the held Select sample is not a
    // valid neutral rearm. This is the product-critical independence property.
    @(negedge clk_74a);
    osnotify_inmenu = 1'b0;
    send_pad(16'h4000);
    wait_sys_state(1'b0, 1'b1,
                   "menu exit remained paused behind PAD neutral rearm");
    if (buttons_sys !== 16'h0000 || fast_forward !== 1'b0)
      $fatal(1, "held menu chord leaked through blocked input");

    repeat (12) begin
      @(posedge clk_sys);
      #1ps;
      if (menu_focus_sys || !input_blocked_sys || fast_forward)
        $fatal(1, "pause/input ownership paths recoupled after menu exit");
    end

    // Only a fresh neutral packet releases physical ownership; it is not
    // involved in releasing menu pause.
    send_pad(16'h0000);
    wait_sys_state(1'b0, 1'b0, "fresh neutral packet did not rearm controls");
    send_pad(16'h4000);
    repeat (8) @(posedge clk_sys);
    #1ps;
    if (!fast_forward)
      $fatal(1, "Fast Forward did not recover after explicit neutral rearm");

    $display("PASS 00B0 pause/resume independent of PAD neutral rearm; Fast Forward safe");
    $finish;
  end
endmodule
