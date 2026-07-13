`timescale 1ns/1ps

module apf_frame_orientation_tb;
  reg clk = 1'b0;
  reg reset = 1'b1;
  reg enable = 1'b0;
  reg producer_frame_done = 1'b0;
  reg consumer_frame_boundary = 1'b0;
  reg producer_orientation = 1'b0;

  wire [2:0] write_bank;
  wire [2:0] history_newest;
  wire [2:0] history_previous;
  wire [2:0] history_oldest;
  wire [1:0] history_valid_count;
  wire buffered_frame_visible = enable && history_valid_count != 2'd0;
  wire presented_orientation;

  integer producer_frames = 0;
  integer consumer_frames = 0;
  reg [2:0] first_pending_bank;
  reg [2:0] superseding_bank;

  always #5 clk = ~clk;

  apf_framebank_arbiter arbiter (
      .clk(clk),
      .reset(reset),
      .enable(enable),
      .producer_frame_done(producer_frame_done),
      .consumer_frame_boundary(consumer_frame_boundary),
      .write_bank(write_bank),
      .history_newest(history_newest),
      .history_previous(history_previous),
      .history_oldest(history_oldest),
      .history_valid_count(history_valid_count)
  );

  apf_frame_orientation dut (
      .clk(clk),
      .reset(reset),
      .producer_frame_done(producer_frame_done),
      .write_bank(write_bank),
      .producer_orientation(producer_orientation),
      .consumer_frame_boundary(consumer_frame_boundary),
      .buffered_frame_visible(buffered_frame_visible),
      .history_newest(history_newest),
      .presented_orientation(presented_orientation)
  );

  task automatic drive(input bit produce, input bit consume);
    begin
      @(negedge clk);
      producer_frame_done = produce;
      consumer_frame_boundary = consume;
      @(posedge clk);
      #1ps;
      if (produce) producer_frames = producer_frames + 1;
      if (consume) consumer_frames = consumer_frames + 1;
      @(negedge clk);
      producer_frame_done = 1'b0;
      consumer_frame_boundary = 1'b0;
    end
  endtask

  task automatic expect_orientation(input bit expected, input string check_name);
    begin
      #1ps;
      if (presented_orientation !== expected) begin
        $fatal(
            1,
            "%0s expected orientation=%0d got=%0d newest=%0d count=%0d writer=%0d",
            check_name,
            expected,
            presented_orientation,
            history_newest,
            history_valid_count,
            write_bank
        );
      end
    end
  endtask

  initial begin
    repeat (3) @(posedge clk);
    @(negedge clk);
    reset = 1'b0;

    // Direct mode captures the first post-reset level immediately, then holds
    // it throughout the frame even if the game changes orientation mid-frame.
    producer_orientation = 1'b1;
    @(posedge clk);
    expect_orientation(1'b1, "direct startup portrait");
    @(negedge clk);
    producer_orientation = 1'b0;
    repeat (4) @(posedge clk);
    expect_orientation(1'b1, "direct mid-frame hold");
    drive(1'b0, 1'b1);
    expect_orientation(1'b0, "direct boundary apply");

    // Enable buffering with no history. The direct startup image remains
    // selected until a complete frame has actually been promoted.
    @(negedge clk);
    enable = 1'b1;
    producer_orientation = 1'b1;
    first_pending_bank = write_bank;
    drive(1'b1, 1'b0);
    if (history_valid_count !== 2'd0)
      $fatal(1, "unconsumed producer frame became visible");
    expect_orientation(1'b0, "buffer priming direct fallback");

    // A faster producer supersedes the portrait pending frame with a newer
    // landscape frame. Consuming the queue must publish only the orientation
    // stored beside the newer bank, never the stale live bit or dropped bank.
    producer_orientation = 1'b0;
    superseding_bank = write_bank;
    if (superseding_bank == first_pending_bank)
      $fatal(1, "arbiter did not separate writer and pending bank");
    drive(1'b1, 1'b0);
    producer_orientation = 1'b1; // Poison the live level after completion.
    drive(1'b0, 1'b1);
    if (history_newest !== superseding_bank)
      $fatal(1, "newest pending frame did not supersede the older one");
    expect_orientation(1'b0, "superseded pending frame metadata");

    // A coincident producer/consumer boundary promotes the just-completed
    // writer. Its bank metadata and ownership update on the same edge.
    producer_orientation = 1'b1;
    superseding_bank = write_bank;
    drive(1'b1, 1'b1);
    if (history_newest !== superseding_bank)
      $fatal(1, "coincident completion promoted the wrong bank");
    expect_orientation(1'b1, "coincident portrait promotion");

    // Changing the live console level cannot rotate an immutable visible
    // bank. Even an empty consumer boundary retains its bank-bound metadata.
    producer_orientation = 1'b0;
    repeat (5) @(posedge clk);
    expect_orientation(1'b1, "buffered live-level isolation");
    drive(1'b0, 1'b1);
    expect_orientation(1'b1, "empty consumer boundary isolation");

    // Disabling buffering invalidates history and returns to a direct value,
    // but that direct value still changes only at a frame boundary.
    @(negedge clk);
    enable = 1'b0;
    @(posedge clk);
    #1ps;
    expect_orientation(1'b0, "buffer disable direct boundary");
    @(negedge clk);
    producer_orientation = 1'b1;
    repeat (3) @(posedge clk);
    expect_orientation(1'b0, "direct post-disable mid-frame hold");
    drive(1'b0, 1'b1);
    expect_orientation(1'b1, "direct post-disable next boundary");

    // Reset must erase retained per-bank metadata before another title uses
    // the same physical RAM banks.
    @(negedge clk);
    reset = 1'b1;
    @(posedge clk);
    #1ps;
    expect_orientation(1'b0, "reset clears presentation metadata");

    $display(
        "PASS APF frame orientation producer=%0d consumer=%0d queued_supersession=1 direct_atomic=1",
        producer_frames,
        consumer_frames
    );
    $finish;
  end
endmodule
