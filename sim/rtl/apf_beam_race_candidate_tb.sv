`timescale 1ns/1ps

module apf_beam_race_candidate_tb;
  reg clk = 1'b0;
  reg reset = 1'b1;
  reg pixel_write = 1'b0;
  reg [14:0] pixel_address = 15'd0;
  reg producer_frame_done = 1'b0;
  reg [2:0] writer_bank = 3'd0;
  reg output_frame_boundary = 1'b0;
  reg normal_speed = 1'b1;
  reg producer_contract_valid = 1'b0;
  wire beam_valid;
  wire [2:0] beam_bank;
  wire protect_valid;
  wire [2:0] protect_bank;

  always #5 clk = ~clk;

  apf_beam_race_candidate dut (
      .clk(clk),
      .reset(reset),
      .pixel_write(pixel_write),
      .pixel_address(pixel_address),
      .producer_frame_done(producer_frame_done),
      .writer_bank(writer_bank),
      .output_frame_boundary(output_frame_boundary),
      .normal_speed(normal_speed),
      .producer_contract_valid(producer_contract_valid),
      .beam_valid(beam_valid),
      .beam_bank(beam_bank),
      .protect_valid(protect_valid),
      .protect_bank(protect_bank)
  );

  task automatic pulse_boundary;
    begin
      @(negedge clk);
      output_frame_boundary = 1'b1;
      @(posedge clk);
      #1ps;
      @(negedge clk);
      output_frame_boundary = 1'b0;
    end
  endtask

  task automatic write_pixel(input [14:0] address);
    begin
      @(negedge clk);
      pixel_address = address;
      pixel_write = 1'b1;
      @(posedge clk);
      #1ps;
      @(negedge clk);
      pixel_write = 1'b0;
    end
  endtask

  initial begin
    repeat (3) @(posedge clk);
    @(negedge clk);
    reset = 1'b0;

    // No observed first pixel: fail closed even if a hypothetical producer
    // contract is asserted.
    producer_contract_valid = 1'b1;
    writer_bank = 3'd2;
    pulse_boundary();
    if (beam_valid)
      $fatal(1, "candidate armed before writer start");

    // Pixel zero starts a candidate generation, but lack of an end-to-end
    // producer contract must still force the complete-frame fallback.
    write_pixel(15'd0);
    producer_contract_valid = 1'b0;
    pulse_boundary();
    if (beam_valid)
      $fatal(1, "candidate armed without producer contract");

    // Under all three prerequisites, latch and protect the writer bank for the
    // complete output frame.
    producer_contract_valid = 1'b1;
    pulse_boundary();
    if (!beam_valid || beam_bank != 3'd2 || !protect_valid || protect_bank != 3'd2)
      $fatal(1, "eligible writer was not latched/protected");
    writer_bank = 3'd4;
    write_pixel(15'd1234);
    if (beam_bank != 3'd2 || protect_bank != 3'd2)
      $fatal(1, "latched bank followed live writer");

    // Accelerated production is explicitly ineligible.
    normal_speed = 1'b0;
    pulse_boundary();
    if (beam_valid || protect_valid)
      $fatal(1, "candidate remained armed outside normal speed");

    // Completing a frame invalidates the next writer until its own address
    // zero is observed. A coincident boundary conservatively falls back.
    normal_speed = 1'b1;
    @(negedge clk);
    producer_frame_done = 1'b1;
    output_frame_boundary = 1'b1;
    @(posedge clk);
    #1ps;
    @(negedge clk);
    producer_frame_done = 1'b0;
    output_frame_boundary = 1'b0;
    if (!beam_valid)
      $fatal(1, "completed current writer should remain eligible at its boundary");
    pulse_boundary();
    if (beam_valid)
      $fatal(1, "next writer armed before its first pixel");

    // Pixel-zero/boundary coincidence is intentionally one frame too late,
    // avoiding an optimistic same-edge phase assumption.
    writer_bank = 3'd1;
    @(negedge clk);
    pixel_address = 15'd0;
    pixel_write = 1'b1;
    output_frame_boundary = 1'b1;
    @(posedge clk);
    #1ps;
    @(negedge clk);
    pixel_write = 1'b0;
    output_frame_boundary = 1'b0;
    if (beam_valid)
      $fatal(1, "coincident first pixel armed optimistically");
    pulse_boundary();
    if (!beam_valid || beam_bank != 3'd1)
      $fatal(1, "observed next writer did not become eligible");

    $display(
        "PASS APF beam-race candidate fail_closed=3 writer_latched=1 protection=1 coincident_conservative=1"
    );
    $finish;
  end
endmodule
