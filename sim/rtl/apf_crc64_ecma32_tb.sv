`timescale 1ns / 1ps
`default_nettype none

module apf_crc64_ecma32_tb;
  reg clk = 1'b0;
  reg reset_n = 1'b0;
  reg clear = 1'b0;
  reg enable = 1'b0;
  reg [31:0] blob_word = 32'd0;
  reg [2:0] byte_count = 3'd0;
  wire [63:0] crc_value;

  integer vector_file;
  integer scan_result;
  integer operation;
  integer vector_byte_count;
  integer vector_count = 0;
  reg [31:0] vector_word;
  reg [63:0] vector_expected;
  reg [1023:0] vector_path;

  always #5 clk = ~clk;

  apf_crc64_ecma32 dut (
      .clk(clk),
      .reset_n(reset_n),
      .clear(clear),
      .enable(enable),
      .blob_word(blob_word),
      .byte_count(byte_count),
      .crc_value(crc_value)
  );

  task automatic expect_crc(input [63:0] expected, input [255:0] label_text);
    begin
      if (crc_value !== expected)
        $fatal(1, "%0s expected CRC %016x, got %016x",
               label_text, expected, crc_value);
    end
  endtask

  task automatic clock_controls(
      input control_clear,
      input control_enable,
      input [31:0] control_word,
      input [2:0] control_count,
      input [63:0] expected,
      input [255:0] label_text
  );
    begin
      @(negedge clk);
      clear = control_clear;
      enable = control_enable;
      blob_word = control_word;
      byte_count = control_count;
      @(posedge clk);
      #1ps;
      expect_crc(expected, label_text);
      clear = 1'b0;
      enable = 1'b0;
    end
  endtask

  task automatic apply_vector(
      input integer vector_operation,
      input [31:0] word_value,
      input integer count_value,
      input [63:0] expected
  );
    begin
      if (vector_operation == 4) begin
        @(negedge clk);
        clear = 1'b0;
        enable = 1'b0;
        blob_word = word_value;
        byte_count = count_value[2:0];
        reset_n = 1'b0;
        #1ps;
        expect_crc(expected, "vector asynchronous reset");
        @(negedge clk);
        reset_n = 1'b1;
      end else begin
        clock_controls(
            vector_operation == 0 || vector_operation == 3,
            vector_operation == 1 || vector_operation == 3,
            word_value,
            count_value[2:0],
            expected,
            "generated reference vector"
        );
      end
    end
  endtask

  initial begin
    // Asynchronous reset seeds the direct ECMA accumulator to zero.
    #1ps;
    expect_crc(64'd0, "power-on reset");
    repeat (2) @(posedge clk);
    reset_n = 1'b1;

    // Published CRC-64/ECMA-182 check value. The final one-byte transaction
    // also proves that unused low bytes are not implicit zero padding.
    clock_controls(1'b1, 1'b0, 32'hdead_beef, 3'd4,
                   64'd0, "standard-vector clear");
    clock_controls(1'b0, 1'b1, 32'h3132_3334, 3'd4,
                   64'h1e36_0c18_91a6_0f78, "standard bytes 1-4");
    clock_controls(1'b0, 1'b1, 32'h3536_3738, 3'd4,
                   64'h3732_f4b6_474a_5a2b, "standard bytes 5-8");
    clock_controls(1'b0, 1'b1, 32'h39aa_55ff, 3'd1,
                   64'h6c40_df5f_0b49_7347, "standard byte 9");
    clock_controls(1'b0, 1'b0, 32'hffff_ffff, 3'd7,
                   64'h6c40_df5f_0b49_7347, "disabled hold");
    clock_controls(1'b1, 1'b1, 32'h5357_414e, 3'd4,
                   64'd0, "clear priority");

    // Reset assertion does not wait for a clock edge.
    clock_controls(1'b0, 1'b1, 32'h5357_414e, 3'd4,
                   64'h3c48_9b0c_215b_b48c, "pre-reset SWAN");
    #2;
    reset_n = 1'b0;
    #1ps;
    expect_crc(64'd0, "asynchronous reset assertion");
    #2;
    reset_n = 1'b1;

    if (!$value$plusargs("VECTORS=%s", vector_path))
      $fatal(1, "missing +VECTORS=<path>");
    vector_file = $fopen(vector_path, "r");
    if (vector_file == 0)
      $fatal(1, "could not open vector file %0s", vector_path);

    while (!$feof(vector_file)) begin
      scan_result = $fscanf(
          vector_file,
          "%d %h %d %h\n",
          operation,
          vector_word,
          vector_byte_count,
          vector_expected
      );
      if (scan_result == 4) begin
        apply_vector(operation, vector_word, vector_byte_count, vector_expected);
        vector_count = vector_count + 1;
      end else if (scan_result != -1) begin
        $fatal(1, "malformed CRC vector after %0d entries", vector_count);
      end
    end
    $fclose(vector_file);

    if (vector_count < 131072)
      $fatal(1, "reference vector set was unexpectedly small: %0d", vector_count);

    $display(
        "PASS APF CRC64 ECMA32 vectors=%0d check=%016x byte_order=msb_first",
        vector_count,
        64'h6c40_df5f_0b49_7347
    );
    $finish;
  end
endmodule

`default_nettype wire
