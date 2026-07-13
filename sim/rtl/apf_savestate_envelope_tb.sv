`timescale 1ns / 1ps

module apf_savestate_envelope_tb;
  localparam [31:0] TEST_PAYLOAD_BYTES = 32'd32;
  localparam [31:0] TEST_TOTAL_BYTES = 32'd64;
  localparam [31:0] TEST_FORMAT_ID = 32'h5753_00a5;

  reg clk = 1'b0;
  reg reset_n = 1'b0;
  reg load_write = 1'b0;
  reg [27:0] load_offset = 28'd0;
  reg [31:0] load_data = 32'd0;
  reg load_finalize = 1'b0;
  wire payload_write;
  wire [27:0] payload_offset;
  wire [31:0] payload_data;
  wire load_active;
  wire load_complete;
  wire load_ready;
  wire load_error;
  reg [27:0] save_offset = 28'd0;
  wire [31:0] save_header_data;
  wire save_header_select;
  reg [27:0] default_save_offset = 28'd0;
  wire [31:0] default_save_header_data;
  wire default_save_header_select;

  integer forwarded_words = 0;

  always #5 clk = ~clk;

  apf_savestate_envelope #(
      .PAYLOAD_BYTES(TEST_PAYLOAD_BYTES),
      .FORMAT_ID(TEST_FORMAT_ID)
  ) dut (
      .clk(clk),
      .reset_n(reset_n),
      .load_write(load_write),
      .load_offset(load_offset),
      .load_data(load_data),
      .load_finalize(load_finalize),
      .payload_write(payload_write),
      .payload_offset(payload_offset),
      .payload_data(payload_data),
      .load_active(load_active),
      .load_complete(load_complete),
      .load_ready(load_ready),
      .load_error(load_error),
      .save_offset(save_offset),
      .save_header_data(save_header_data),
      .save_header_select(save_header_select)
  );

  // A second, un-driven parser locks the production format defaults while the
  // compact instance above keeps adversarial transfer tests fast.
  apf_savestate_envelope production_defaults (
      .clk(clk),
      .reset_n(reset_n),
      .load_write(1'b0),
      .load_offset(28'd0),
      .load_data(32'd0),
      .load_finalize(1'b0),
      .payload_write(),
      .payload_offset(),
      .payload_data(),
      .load_active(),
      .load_complete(),
      .load_ready(),
      .load_error(),
      .save_offset(default_save_offset),
      .save_header_data(default_save_header_data),
      .save_header_select(default_save_header_select)
  );

  task automatic expect_header(input [27:0] offset, input [31:0] expected);
    begin
      save_offset = offset;
      #1;
      if (!save_header_select || save_header_data !== expected)
        $fatal(1, "header[%0d] expected %08x, got select=%b data=%08x",
               offset, expected, save_header_select, save_header_data);
    end
  endtask

  task automatic send_word(input [27:0] offset, input [31:0] data);
    begin
      @(negedge clk);
      load_offset = offset;
      load_data = data;
      load_write = 1'b1;
      @(negedge clk);
      if (payload_write) begin
        forwarded_words = forwarded_words + 1;
        if (payload_offset !== offset - 28'd32 || payload_data !== data)
          $fatal(1, "payload forwarding mismatch offset=%0d/%0d data=%08x/%08x",
                 payload_offset, offset - 28'd32, payload_data, data);
      end else if (offset >= 28'd32 && offset < TEST_TOTAL_BYTES[27:0] &&
                   !load_error) begin
        $fatal(1, "payload word at offset %0d was not forwarded", offset);
      end
      load_write = 1'b0;
    end
  endtask

  task automatic finalize_load;
    begin
      @(negedge clk);
      load_finalize = 1'b1;
      @(negedge clk);
      load_finalize = 1'b0;
    end
  endtask

  task automatic start_header;
    begin
      send_word(28'd0, 32'h5357_414e);
      send_word(28'd4, 32'd1);
      send_word(28'd8, 32'd32);
      send_word(28'd12, TEST_PAYLOAD_BYTES);
      send_word(28'd16, TEST_TOTAL_BYTES);
      send_word(28'd20, TEST_FORMAT_ID);
      send_word(28'd24, 32'd0);
      send_word(28'd28, 32'd0);
    end
  endtask

  task automatic send_valid_blob;
    integer offset;
    begin
      forwarded_words = 0;
      start_header();
      for (offset = 32; offset < TEST_TOTAL_BYTES; offset = offset + 4)
        send_word(offset[27:0], 32'hc000_0000 | offset);
      if (forwarded_words != TEST_PAYLOAD_BYTES / 4)
        $fatal(1, "expected %0d payload words, forwarded %0d",
               TEST_PAYLOAD_BYTES / 4, forwarded_words);
    end
  endtask

  task automatic expect_rejected(input [255:0] label_text);
    begin
      finalize_load();
      if (!load_error || load_ready)
        $fatal(1, "%0s transfer was not rejected: error=%b ready=%b",
               label_text, load_error, load_ready);
    end
  endtask

  initial begin
    repeat (3) @(posedge clk);
    reset_n = 1'b1;

    expect_header(28'd0, 32'h5357_414e);
    expect_header(28'd4, 32'd1);
    expect_header(28'd8, 32'd32);
    expect_header(28'd12, TEST_PAYLOAD_BYTES);
    expect_header(28'd16, TEST_TOTAL_BYTES);
    expect_header(28'd20, TEST_FORMAT_ID);
    expect_header(28'd24, 32'd0);
    expect_header(28'd28, 32'd0);

    default_save_offset = 28'd12;
    #1;
    if (!default_save_header_select || default_save_header_data !== 32'h0009_0300)
      $fatal(1, "production payload length is not 0x90300");
    default_save_offset = 28'd16;
    #1;
    if (!default_save_header_select || default_save_header_data !== 32'h0009_0320)
      $fatal(1, "production total length is not 0x90320");
    default_save_offset = 28'd20;
    #1;
    if (!default_save_header_select || default_save_header_data !== 32'h5753_0001)
      $fatal(1, "production payload format id is not WS revision 1");
    save_offset = 28'd32;
    #1;
    if (save_header_select || save_header_data !== 32'd0)
      $fatal(1, "payload address incorrectly selected as header");
    save_offset = 28'd2;
    #1;
    if (save_header_select)
      $fatal(1, "misaligned header address was selected");

    send_valid_blob();
    if (!load_complete || load_ready || load_error)
      $fatal(1, "complete blob state before finalize is wrong");
    finalize_load();
    if (!load_ready || load_error)
      $fatal(1, "valid blob was not accepted");

    send_word(28'd0, 32'h4241_4421);
    expect_rejected("bad magic");

    send_word(28'd0, 32'h5357_414e);
    send_word(28'd4, 32'd2);
    expect_rejected("future version");

    send_word(28'd0, 32'h5357_414e);
    send_word(28'd4, 32'd1);
    send_word(28'd8, 32'd28);
    expect_rejected("wrong header length");

    send_word(28'd0, 32'h5357_414e);
    send_word(28'd4, 32'd1);
    send_word(28'd8, 32'd32);
    send_word(28'd12, TEST_PAYLOAD_BYTES + 4);
    expect_rejected("wrong payload length");

    send_word(28'd0, 32'h5357_414e);
    send_word(28'd4, 32'd1);
    send_word(28'd8, 32'd32);
    send_word(28'd12, TEST_PAYLOAD_BYTES);
    send_word(28'd16, TEST_TOTAL_BYTES + 4);
    expect_rejected("wrong total length");

    send_word(28'd0, 32'h5357_414e);
    send_word(28'd4, 32'd1);
    send_word(28'd8, 32'd32);
    send_word(28'd12, TEST_PAYLOAD_BYTES);
    send_word(28'd16, TEST_TOTAL_BYTES);
    send_word(28'd20, TEST_FORMAT_ID ^ 32'd1);
    expect_rejected("wrong payload format");

    send_word(28'd0, 32'h5357_414e);
    send_word(28'd4, 32'd1);
    send_word(28'd8, 32'd32);
    send_word(28'd12, TEST_PAYLOAD_BYTES);
    send_word(28'd16, TEST_TOTAL_BYTES);
    send_word(28'd20, TEST_FORMAT_ID);
    send_word(28'd24, 32'd1);
    expect_rejected("unknown flags");

    send_word(28'd0, 32'h5357_414e);
    send_word(28'd4, 32'd1);
    send_word(28'd8, 32'd32);
    send_word(28'd12, TEST_PAYLOAD_BYTES);
    send_word(28'd16, TEST_TOTAL_BYTES);
    send_word(28'd20, TEST_FORMAT_ID);
    send_word(28'd24, 32'd0);
    send_word(28'd28, 32'hffff_ffff);
    expect_rejected("nonzero reserved word");

    start_header();
    send_word(28'd32, 32'h1111_1111);
    expect_rejected("short payload");

    send_word(28'd0, 32'h5357_414e);
    send_word(28'd8, 32'd32);
    expect_rejected("header gap");

    start_header();
    send_word(28'd32, 32'h1111_1111);
    send_word(28'd32, 32'h2222_2222);
    expect_rejected("duplicate payload word");

    start_header();
    send_word(28'd34, 32'h3333_3333);
    expect_rejected("misaligned payload word");

    send_valid_blob();
    send_word(TEST_TOTAL_BYTES[27:0], 32'h4444_4444);
    expect_rejected("overlong payload");

    start_header();
    expect_rejected("premature finalize");
    send_word(28'd32, 32'h5555_5555);
    if (!load_error || payload_write)
      $fatal(1, "errored transfer accepted data after finalize");
    send_valid_blob();
    finalize_load();
    if (!load_ready || load_error)
      $fatal(1, "new transfer did not recover from sticky error");

    $display("PASS APF savestate envelope magic=SWAN version=1 header=32 payload=%0d adversarial=15",
             TEST_PAYLOAD_BYTES);
    $finish;
  end
endmodule
