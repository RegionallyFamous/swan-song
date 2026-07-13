`timescale 1ns/1ps

module apf_framebank_arbiter_tb;
  reg clk = 1'b0;
  reg reset = 1'b1;
  reg enable = 1'b0;
  reg producer_frame_done = 1'b0;
  reg consumer_frame_boundary = 1'b0;
  reg defer_candidate = 1'b0;
  reg protect_pending = 1'b0;

  wire [2:0] write_bank;
  wire pending_valid;
  wire [2:0] pending_bank;
  wire [2:0] history_newest;
  wire [2:0] history_previous;
  wire [2:0] history_oldest;
  wire [1:0] history_valid_count;

  integer cycles = 0;
  integer producer_frames = 0;
  integer consumer_frames = 0;
  integer i;

  always #5 clk = ~clk;

  apf_framebank_arbiter dut (
      .clk(clk),
      .reset(reset),
      .enable(enable),
      .producer_frame_done(producer_frame_done),
      .consumer_frame_boundary(consumer_frame_boundary),
      .defer_candidate(defer_candidate),
      .protect_pending(protect_pending),
      .write_bank(write_bank),
      .pending_valid_out(pending_valid),
      .pending_bank_out(pending_bank),
      .history_newest(history_newest),
      .history_previous(history_previous),
      .history_oldest(history_oldest),
      .history_valid_count(history_valid_count)
  );

  task automatic check_ownership;
    begin
      #1ps;
      if (write_bank > 3'd4 || history_valid_count > 2'd3)
        $fatal(1, "bank/count out of range");
      if (enable) begin
        if (history_valid_count >= 1 && write_bank == history_newest)
          $fatal(1, "writer collided with newest history bank %0d", write_bank);
        if (history_valid_count >= 2 &&
            (write_bank == history_previous || history_newest == history_previous))
          $fatal(1, "writer/history collision at depth 2");
        if (history_valid_count >= 3 &&
            (write_bank == history_oldest || history_newest == history_oldest ||
             history_previous == history_oldest))
          $fatal(1, "writer/history collision at depth 3");
        if (pending_valid) begin
          if (pending_bank == write_bank)
            $fatal(1, "pending bank collided with writer");
          if (history_valid_count >= 1 && pending_bank == history_newest)
            $fatal(1, "pending bank collided with newest history");
          if (history_valid_count >= 2 && pending_bank == history_previous)
            $fatal(1, "pending bank collided with previous history");
          if (history_valid_count >= 3 && pending_bank == history_oldest)
            $fatal(1, "pending bank collided with oldest history");
        end
      end else if (write_bank != 3'd0 || history_valid_count != 2'd0) begin
        $fatal(1, "disabled arbiter did not return to direct bank zero");
      end
    end
  endtask

  task automatic drive(input bit produce, input bit consume);
    reg [2:0] completed_bank;
    begin
      @(negedge clk);
      completed_bank = write_bank;
      producer_frame_done = produce;
      consumer_frame_boundary = consume;
      @(posedge clk);
      cycles = cycles + 1;
      if (produce) producer_frames = producer_frames + 1;
      if (consume) consumer_frames = consumer_frames + 1;
      check_ownership();
      if (produce && consume && history_newest !== completed_bank)
        $fatal(1, "coincident boundary did not consume newest completed frame");
      @(negedge clk);
      producer_frame_done = 1'b0;
      consumer_frame_boundary = 1'b0;
    end
  endtask

  initial begin
    repeat (3) @(posedge clk);
    reset = 1'b0;
    enable = 1'b1;

    repeat (3) begin
      drive(1'b1, 1'b0);
      drive(1'b0, 1'b1);
    end
    if (history_valid_count != 3)
      $fatal(1, "history failed to prime to depth three");

    // Exercise the 75 Hz producer outrunning the roughly 59 Hz scanout.
    repeat (20) begin
      drive(1'b1, 1'b0);
      drive(1'b1, 1'b0);
      drive(1'b0, 1'b1);
    end

    for (i = 0; i < 10000; i = i + 1)
      drive((i % 5) < 3, ((i * 3 + 1) % 7) < 2);

    // A title/mode reset invalidates history even though RAM retains bits.
    @(negedge clk);
    enable = 1'b0;
    @(posedge clk);
    check_ownership();
    @(negedge clk);
    enable = 1'b1;
    drive(1'b1, 1'b1);
    if (history_valid_count != 1)
      $fatal(1, "history did not re-prime from one fresh frame");

    $display(
        "PASS APF framebank ownership cycles=%0d producer=%0d consumer=%0d banks=5 history=3",
        cycles, producer_frames, consumer_frames
    );
    $finish;
  end
endmodule
