`timescale 1ns/1ps

module apf_rtc_save_loader_tb;
  reg clk = 1'b0;
  always #5 clk = ~clk;

  reg reset_title = 1'b0;
  reg has_rtc = 1'b0;
  reg legacy_padded_type = 1'b0;
  reg [19:0] save_size_bytes = 20'd0;
  reg sd_buff_wr = 1'b0;
  reg [20:0] sd_buff_addr = 21'd0;
  reg [15:0] sd_buff_dout = 16'd0;

  wire extra_data_addr;
  wire extra_write_complete;
  wire rtc_trailer_begin;
  wire rtc_payload_write;
  wire [2:0] rtc_payload_index;
  wire [15:0] rtc_payload_data;
  wire rtc_trailer_complete;

  integer errors = 0;
  integer begin_count = 0;
  integer payload_count = 0;
  integer complete_count = 0;
  reg [15:0] captured_payload [0:4];
  integer index;

  apf_rtc_save_loader dut (
      .clk(clk),
      .reset_title(reset_title),
      .has_rtc(has_rtc),
      .legacy_padded_type(legacy_padded_type),
      .save_size_bytes(save_size_bytes),
      .sd_buff_wr(sd_buff_wr),
      .sd_buff_addr(sd_buff_addr),
      .sd_buff_dout(sd_buff_dout),
      .extra_data_addr(extra_data_addr),
      .extra_write_complete(extra_write_complete),
      .rtc_trailer_begin(rtc_trailer_begin),
      .rtc_payload_write(rtc_payload_write),
      .rtc_payload_index(rtc_payload_index),
      .rtc_payload_data(rtc_payload_data),
      .rtc_trailer_complete(rtc_trailer_complete)
  );

  task automatic fail(input string message);
    begin
      $display("FAIL: %s", message);
      errors = errors + 1;
    end
  endtask

  task automatic reset_loader;
    begin
      @(negedge clk);
      sd_buff_wr = 1'b0;
      reset_title = 1'b1;
      @(posedge clk);
      #1;
      reset_title = 1'b0;
      begin_count = 0;
      payload_count = 0;
      complete_count = 0;
      for (index = 0; index < 5; index = index + 1)
        captured_payload[index] = 16'h0000;
    end
  endtask

  task automatic write_word(input [20:0] address, input [15:0] data);
    reg expected_extra;
    begin
      expected_extra = address >= save_size_bytes;
      @(negedge clk);
      sd_buff_addr = address;
      sd_buff_dout = data;
      sd_buff_wr = 1'b1;
      #1;
      if (extra_data_addr !== expected_extra)
        fail($sformatf("extra classification at byte %0d", address));
      if (extra_write_complete !== 1'b0)
        fail($sformatf("write completed before parser sampled byte %0d", address));
      if ($isunknown({extra_data_addr, extra_write_complete}))
        fail($sformatf("unknown classification at byte %0d", address));
      @(posedge clk);
      #1;
      if (extra_write_complete !== expected_extra)
        fail($sformatf("sampled write completion at byte %0d", address));
      if ($isunknown({rtc_trailer_begin, rtc_payload_write,
                      rtc_payload_index, rtc_payload_data,
                      rtc_trailer_complete}))
        fail($sformatf("unknown RTC output at byte %0d", address));
      @(negedge clk);
      sd_buff_wr = 1'b0;
    end
  endtask

  task automatic check_payload(
      input [15:0] word0,
      input [15:0] word1,
      input [15:0] word2,
      input [15:0] word3,
      input [15:0] word4
  );
    begin
      if (captured_payload[0] !== word0) fail("RTC payload word 0 mismatch");
      if (captured_payload[1] !== word1) fail("RTC payload word 1 mismatch");
      if (captured_payload[2] !== word2) fail("RTC payload word 2 mismatch");
      if (captured_payload[3] !== word3) fail("RTC payload word 3 mismatch");
      if (captured_payload[4] !== word4) fail("RTC payload word 4 mismatch");
    end
  endtask

  always @(posedge clk) begin
    #1;
    if (rtc_trailer_begin) begin_count = begin_count + 1;
    if (rtc_payload_write) begin
      payload_count = payload_count + 1;
      if (rtc_payload_index < 5)
        captured_payload[rtc_payload_index] = rtc_payload_data;
      else
        fail("RTC payload index out of range");
    end
    if (rtc_trailer_complete) complete_count = complete_count + 1;
  end

  initial begin
    // Canonical type-0x10: exact EEPROM payload followed immediately by RTC.
    has_rtc = 1'b1;
    legacy_padded_type = 1'b1;
    save_size_bytes = 20'd128;
    reset_loader();
    write_word(21'd126, 16'hcafe);
    write_word(21'd128, "RT");
    write_word(21'd130, 16'h1000);
    write_word(21'd132, 16'h1001);
    write_word(21'd134, 16'h1002);
    write_word(21'd136, 16'h1003);
    write_word(21'd138, 16'h1004);
    if (begin_count != 1) fail("canonical trailer header count");
    if (payload_count != 5) fail("canonical trailer payload count");
    if (complete_count != 1) fail("canonical trailer completion count");
    check_payload(16'h1000, 16'h1001, 16'h1002, 16'h1003, 16'h1004);

    // Legacy type-0x10: acknowledge and discard all 1,920 padding bytes,
    // then recognize the inherited RTC trailer at absolute byte 2,048.
    reset_loader();
    for (index = 128; index < 2048; index = index + 2)
      write_word(index[20:0], 16'h0000);
    write_word(21'd2048, "RT");
    write_word(21'd2050, 16'ha000);
    write_word(21'd2052, 16'ha001);
    write_word(21'd2054, 16'ha002);
    write_word(21'd2056, 16'ha003);
    write_word(21'd2058, 16'ha004);
    if (begin_count != 1) fail("legacy type-0x10 trailer header count");
    if (payload_count != 5) fail("legacy type-0x10 payload count");
    if (complete_count != 1) fail("legacy type-0x10 completion count");
    check_payload(16'ha000, 16'ha001, 16'ha002, 16'ha003, 16'ha004);

    // Legacy type-0x50 has a 1 KiB payload and the same inherited RTC base.
    save_size_bytes = 20'd1024;
    reset_loader();
    for (index = 1024; index < 2048; index = index + 2)
      write_word(index[20:0], 16'hffff);
    write_word(21'd2048, "RT");
    write_word(21'd2050, 16'h5000);
    write_word(21'd2052, 16'h5001);
    write_word(21'd2054, 16'h5002);
    write_word(21'd2056, 16'h5003);
    write_word(21'd2058, 16'h5004);
    if (begin_count != 1) fail("legacy type-0x50 trailer header count");
    if (payload_count != 5) fail("legacy type-0x50 payload count");
    if (complete_count != 1) fail("legacy type-0x50 completion count");
    check_payload(16'h5000, 16'h5001, 16'h5002, 16'h5003, 16'h5004);

    // An accidental canonical marker in padding may complete once, but the
    // authoritative legacy marker must restart and overwrite all five words.
    save_size_bytes = 20'd128;
    reset_loader();
    write_word(21'd128, "RT");
    write_word(21'd130, 16'hdead);
    write_word(21'd132, 16'hdead);
    write_word(21'd134, 16'hdead);
    write_word(21'd136, 16'hdead);
    write_word(21'd138, 16'hdead);
    write_word(21'd2048, "RT");
    write_word(21'd2050, 16'h7100);
    write_word(21'd2052, 16'h7101);
    write_word(21'd2054, 16'h7102);
    write_word(21'd2056, 16'h7103);
    write_word(21'd2058, 16'h7104);
    if (begin_count != 2) fail("legacy marker did not restart a prior trailer");
    if (complete_count != 2) fail("restarted trailer completion count");
    check_payload(16'h7100, 16'h7101, 16'h7102, 16'h7103, 16'h7104);

    // No-RTC carts still acknowledge overflow, but no marker may mutate RTC.
    has_rtc = 1'b0;
    save_size_bytes = 20'd1024;
    reset_loader();
    write_word(21'd1024, "RT");
    write_word(21'd1026, 16'h1111);
    write_word(21'd2048, "RT");
    write_word(21'd2050, 16'h2222);
    if (begin_count != 0 || payload_count != 0 || complete_count != 0)
      fail("no-RTC overflow was parsed as a trailer");

    if (errors != 0) begin
      $display("FAIL apf_rtc_save_loader_tb errors=%0d", errors);
      $fatal(1);
    end
    $display("PASS canonical and legacy padded EEPROM RTC save loading");
    $finish;
  end

endmodule
