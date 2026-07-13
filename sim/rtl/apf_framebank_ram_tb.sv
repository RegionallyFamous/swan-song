`timescale 1ns/1ps

module apf_framebank_ram_tb;
  localparam integer FRAME_PIXELS = 32256;

  reg clk = 1'b0;
  reg write_enable = 1'b0;
  reg [14:0] write_address = 15'd0;
  reg [11:0] write_data = 12'd0;
  reg [14:0] read_address = 15'd0;
  wire [11:0] read_data;

  integer address;
  integer vectors = 0;
  reg [11:0] expected;

  always #5 clk = ~clk;

  apf_framebank_ram dut (
      .clk(clk),
      .write_enable(write_enable),
      .write_address(write_address),
      .write_data(write_data),
      .read_address(read_address),
      .read_data(read_data)
  );

  function automatic [11:0] pixel_pattern(input integer index);
    integer mixed;
    begin
      mixed = (index * 13) + (index >> 3) + (index >> 9);
      pixel_pattern = mixed[11:0];
    end
  endfunction

  initial begin
    // Fill every address so the check crosses all inferred 2K and 4K M10K
    // slice boundaries, not just the beginning and end of the visible frame.
    for (address = 0; address < FRAME_PIXELS; address = address + 1) begin
      @(negedge clk);
      write_enable = 1'b1;
      write_address = address[14:0];
      write_data = pixel_pattern(address);
    end

    @(negedge clk);
    write_enable = 1'b0;

    // The wrapper relies on a registered one-clock read. Changing the address
    // between clocks must not change the currently presented pixel.
    read_address = 15'd0;
    @(posedge clk);
    #1ps;
    if (read_data !== pixel_pattern(0))
      $fatal(1, "framebank initial synchronous read mismatch");
    read_address = 15'd1;
    #1ps;
    if (read_data !== pixel_pattern(0))
      $fatal(1, "framebank read changed without a clock edge");
    @(posedge clk);
    #1ps;
    if (read_data !== pixel_pattern(1))
      $fatal(1, "framebank registered read latency mismatch");
    vectors = vectors + 2;

    for (address = 0; address < FRAME_PIXELS; address = address + 1) begin
      @(negedge clk);
      read_address = address[14:0];
      expected = pixel_pattern(address);
      @(posedge clk);
      #1ps;
      if (read_data !== expected)
        $fatal(
            1,
            "framebank data mismatch address=%0d expected=%03x actual=%03x",
            address,
            expected,
            read_data
        );
      vectors = vectors + 1;
    end

    // Prove that both sides of the 10+2 split update on an overwrite.
    @(negedge clk);
    write_enable = 1'b1;
    write_address = 15'd2048;
    write_data = 12'hFFF;
    @(negedge clk);
    write_enable = 1'b0;
    read_address = 15'd2048;
    @(posedge clk);
    #1ps;
    if (read_data !== 12'hFFF)
      $fatal(1, "framebank split overwrite mismatch actual=%03x", read_data);
    vectors = vectors + 1;

    $display(
        "PASS APF framebank RAM pixels=%0d vectors=%0d split=10+2",
        FRAME_PIXELS,
        vectors
    );
    $finish;
  end
endmodule
