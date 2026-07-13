`timescale 1ns/1ps

module apf_gamepad_filter_tb;
  reg clk = 1'b0;
  always #5 clk = ~clk;

  reg reset_n = 1'b0;
  reg [31:0] key_word = 32'd0;
  wire [15:0] buttons;

  tri pad_1wire;
  wire [31:0] cont1_key;
  wire [31:0] cont2_key;
  wire [31:0] cont3_key;
  wire [31:0] cont4_key;
  wire [31:0] cont1_joy;
  wire [31:0] cont2_joy;
  wire [31:0] cont3_joy;
  wire [31:0] cont4_joy;
  wire [15:0] cont1_trig;
  wire [15:0] cont2_trig;
  wire [15:0] cont3_trig;
  wire [15:0] cont4_trig;
  wire pad_rx_timed_out;

  integer errors = 0;
  integer controller_type;

  apf_gamepad_filter dut (
      .clk(clk),
      .reset_n(reset_n),
      .key_word(key_word),
      .buttons(buttons)
  );

  io_pad_controller pad_dut (
      .clk(clk),
      .reset_n(reset_n),
      .pad_1wire(pad_1wire),
      .cont1_key(cont1_key),
      .cont2_key(cont2_key),
      .cont3_key(cont3_key),
      .cont4_key(cont4_key),
      .cont1_joy(cont1_joy),
      .cont2_joy(cont2_joy),
      .cont3_joy(cont3_joy),
      .cont4_joy(cont4_joy),
      .cont1_trig(cont1_trig),
      .cont2_trig(cont2_trig),
      .cont3_trig(cont3_trig),
      .cont4_trig(cont4_trig),
      .rx_timed_out(pad_rx_timed_out)
  );

  task automatic fail(input string message);
    begin
      $display("FAIL: %s", message);
      errors = errors + 1;
    end
  endtask

  task automatic apply_word(
      input [3:0] device_type,
      input [15:0] digital_bits,
      input [15:0] expected_bits
  );
    begin
      @(negedge clk);
      key_word = {device_type, 12'ha5c, digital_bits};
      @(posedge clk);
      #1;
      if (buttons !== expected_bits)
        fail($sformatf("type %0h produced %04h, expected %04h",
                       device_type, buttons, expected_bits));
    end
  endtask

  // The serialized wire engine is independent of the controller-word latch.
  // Drive the latter's completed-word boundary directly so this focused bench
  // can prove all 32 type/data bits survive each of the four official slots
  // without spending millions of clocks on one-wire polling delays.
  task automatic inject_pad_word(
      input [3:0] word_index,
      input [31:0] word_value
  );
    begin
      force pad_dut.cnt = word_index;
      force pad_dut.rx_word = word_value;
      @(posedge clk);
      #1;
      release pad_dut.cnt;
      release pad_dut.rx_word;
    end
  endtask

  initial begin
    // Reset dominates even a valid, fully asserted Pocket packet.
    key_word = {4'h1, 12'hfff, 16'hffff};
    repeat (5) @(posedge clk);
    #1;
    if (buttons !== 16'h0000)
      fail("reset exposed Pocket buttons");

    @(negedge clk);
    reset_n = 1'b1;

    // Sweep the complete type space.  Only the three official gamepad
    // classes may expose the shared digital bitmap.
    for (controller_type = 0; controller_type < 16; controller_type++) begin
      if (controller_type >= 1 && controller_type <= 3)
        apply_word(controller_type[3:0], 16'ha55a, 16'ha55a);
      else
        apply_word(controller_type[3:0], 16'hffff, 16'h0000);
    end

    // Every digital bit is preserved for both Pocket and Dock gamepads.
    apply_word(4'h1, 16'hffff, 16'hffff);
    apply_word(4'h2, 16'h5aa5, 16'h5aa5);
    apply_word(4'h3, 16'h8001, 16'h8001);

    // A keyboard, mouse, or disconnect packet must clear a previously held
    // button set on the first source-domain edge that accepts the new word.
    apply_word(4'h3, 16'hffff, 16'hffff);
    apply_word(4'h4, 16'hffff, 16'h0000);
    apply_word(4'h2, 16'hffff, 16'hffff);
    apply_word(4'h5, 16'hffff, 16'h0000);
    apply_word(4'h1, 16'hffff, 16'hffff);
    apply_word(4'h0, 16'hffff, 16'h0000);

    // Import one complete APF PAD snapshot.  Key words deliberately set their
    // high type nibble and all otherwise-unused bits, catching any recurrence
    // of the legacy [15:0] truncation at the actual wrapper boundary.
    force pad_dut.state = 4'd3;  // ST_RX_BUTTON_2
    force pad_dut.rx_word_done = 1'b1;
    inject_pad_word(4'd0, 32'h1abc_55aa);
    inject_pad_word(4'd1, 32'h0123_4567);
    inject_pad_word(4'd2, 32'h89ab_cdef);
    inject_pad_word(4'd3, 32'h2def_aa55);
    inject_pad_word(4'd4, 32'h7654_3210);
    inject_pad_word(4'd5, 32'h1357_2468);
    inject_pad_word(4'd6, 32'h3fed_0f0f);
    inject_pad_word(4'd7, 32'h89ab_cdef);
    inject_pad_word(4'd8, 32'h55aa_33cc);
    inject_pad_word(4'd9, 32'h4cba_f0f0);
    inject_pad_word(4'd10, 32'h0bad_f00d);
    inject_pad_word(4'd11, 32'hbeef_5a5a);
    release pad_dut.rx_word_done;
    release pad_dut.state;

    if (cont1_key !== 32'h1abc_55aa ||
        cont2_key !== 32'h2def_aa55 ||
        cont3_key !== 32'h3fed_0f0f ||
        cont4_key !== 32'h4cba_f0f0)
      fail("PAD wrapper truncated or misrouted a 32-bit key word");
    if (cont1_joy !== 32'h0123_4567 ||
        cont2_joy !== 32'h7654_3210 ||
        cont3_joy !== 32'h89ab_cdef ||
        cont4_joy !== 32'h0bad_f00d)
      fail("PAD wrapper misrouted an analog word");
    if (cont1_trig !== 16'hcdef || cont2_trig !== 16'h2468 ||
        cont3_trig !== 16'h33cc || cont4_trig !== 16'h5a5a)
      fail("PAD wrapper misrouted a trigger word");

    // Link timeout invalidates the entire snapshot immediately rather than
    // leaving the last held key visible while the one-wire FSM recovers.
    @(negedge clk);
    force pad_dut.rx_timeout = 21'h1f_ffff;
    @(posedge clk);
    #1;
    if ({cont1_key, cont2_key, cont3_key, cont4_key,
         cont1_joy, cont2_joy, cont3_joy, cont4_joy,
         cont1_trig, cont2_trig, cont3_trig, cont4_trig} !== 320'd0)
      fail("PAD timeout did not clear the complete controller snapshot");
    if (pad_rx_timed_out !== 1'b1)
      fail("PAD timeout did not report its event");
    release pad_dut.rx_timeout;

    // Reset also clears an already accepted held state immediately.
    apply_word(4'h1, 16'h0001, 16'h0001);
    @(negedge clk);
    reset_n = 1'b0;
    repeat (5) @(posedge clk);
    #1;
    if (buttons !== 16'h0000)
      fail("reset did not clear a held gamepad state");
    if ({cont1_key, cont2_key, cont3_key, cont4_key,
         cont1_joy, cont2_joy, cont3_joy, cont4_joy,
         cont1_trig, cont2_trig, cont3_trig, cont4_trig} !== 320'd0)
      fail("PAD reset did not clear the complete controller snapshot");

    if (errors != 0)
      $fatal(1, "APF gamepad filter failed with %0d errors", errors);

    $display("PASS APF PAD 32-bit transport, type safety, disconnect, timeout, and reset");
    $finish;
  end

endmodule
