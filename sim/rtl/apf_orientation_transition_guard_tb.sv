`timescale 1ns/1ps

module apf_orientation_transition_guard_tb;
  reg clk = 1'b0;
  reg reset = 1'b1;
  reg enable = 1'b1;
  reg producer_frame_done = 1'b0;
  reg consumer_frame_boundary = 1'b0;
  reg producer_orientation = 1'b0;
  reg [1:0] configured_orientation = 2'd0;
  reg landscape_180 = 1'b0;

  wire [2:0] write_bank;
  wire pending_valid;
  wire [2:0] pending_bank;
  wire [2:0] history_newest;
  wire [2:0] history_previous;
  wire [2:0] history_oldest;
  wire [1:0] history_valid_count;
  wire current_frame_valid = enable && history_valid_count != 0;
  wire presented_orientation;
  wire candidate_orientation;
  wire defer_candidate;
  wire protect_pending;
  wire [2:0] command_slot;
  wire [2:0] expected_applied_slot;
  wire [2:0] presentation_slot;
  wire blank_presentation;

  wire candidate_valid = protect_pending ? pending_valid :
      (producer_frame_done || pending_valid);
  wire [2:0] candidate_bank = protect_pending ? pending_bank :
      producer_frame_done ? write_bank : pending_bank;
  wire candidate_uses_live = !protect_pending && producer_frame_done;

  integer deferred_transitions = 0;
  integer protected_drops = 0;
  reg [2:0] held_history;
  reg [2:0] held_pending;
  reg [2:0] held_writer;

  always #5 clk = ~clk;

  apf_framebank_arbiter arbiter (
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

  apf_frame_orientation orientation (
      .clk(clk),
      .reset(reset),
      .producer_frame_done(producer_frame_done),
      .write_bank(write_bank),
      .producer_orientation(producer_orientation),
      .consumer_frame_boundary(consumer_frame_boundary),
      .buffered_frame_visible(current_frame_valid),
      .history_newest(history_newest),
      .candidate_bank(candidate_bank),
      .candidate_uses_live_orientation(candidate_uses_live),
      .presented_orientation(presented_orientation),
      .candidate_orientation(candidate_orientation)
  );

  apf_orientation_transition_guard dut (
      .clk(clk),
      .reset(reset),
      .frame_boundary(consumer_frame_boundary),
      .buffered_mode(enable),
      .current_frame_valid(current_frame_valid),
      .current_orientation(presented_orientation),
      .producer_orientation(producer_orientation),
      .candidate_valid(candidate_valid),
      .candidate_orientation(candidate_orientation),
      .configured_orientation(configured_orientation),
      .landscape_180(landscape_180),
      .defer_candidate(defer_candidate),
      .protect_pending(protect_pending),
      .command_slot(command_slot),
      .expected_applied_slot(expected_applied_slot),
      .presentation_slot(presentation_slot),
      .blank_presentation(blank_presentation)
  );

  task automatic drive(input bit produce, input bit consume);
    begin
      @(negedge clk);
      producer_frame_done = produce;
      consumer_frame_boundary = consume;
      #1ps;
      if (consume && defer_candidate) deferred_transitions = deferred_transitions + 1;
      @(posedge clk);
      #1ps;
      @(negedge clk);
      producer_frame_done = 1'b0;
      consumer_frame_boundary = 1'b0;
    end
  endtask

  task automatic expect_matched(input string label_text);
    begin
      #1ps;
      if (blank_presentation || presentation_slot != expected_applied_slot) begin
        $fatal(
            1,
            "%0s blank=%0d presentation=%0d applied=%0d command=%0d protect=%0d",
            label_text,
            blank_presentation,
            presentation_slot,
            expected_applied_slot,
            command_slot,
            protect_pending
        );
      end
    end
  endtask

  initial begin
    repeat (3) @(posedge clk);
    @(negedge clk);
    reset = 1'b0;

    // Prime one complete landscape frame under reset slot zero.
    producer_orientation = 1'b0;
    drive(1'b1, 1'b0);
    drive(1'b0, 1'b1);
    if (history_valid_count != 1 || presented_orientation != 0 ||
        presentation_slot != 0 || protect_pending)
      $fatal(1, "landscape history did not prime atomically");
    expect_matched("primed landscape");

    // A portrait completion cannot be promoted while slot zero is applied.
    producer_orientation = 1'b1;
    drive(1'b1, 1'b0);
    held_history = history_newest;
    held_pending = pending_bank;
    drive(1'b0, 1'b1);
    if (!protect_pending || command_slot != 1 || expected_applied_slot != 0 ||
        history_newest != held_history || pending_bank != held_pending ||
        presented_orientation != 0 || presentation_slot != 0 ||
        blank_presentation)
      $fatal(1, "portrait transition did not repeat/protect landscape history");

    // A 75-Hz producer may finish more frames during the defer interval. They
    // are dropped by reusing the writer; the protected portrait bank is never
    // superseded or recycled.
    held_writer = write_bank;
    producer_orientation = 1'b0;
    drive(1'b1, 1'b0);
    protected_drops = protected_drops + 1;
    if (pending_bank != held_pending || write_bank != held_writer ||
        history_newest != held_history)
      $fatal(1, "protected pending bank changed after first producer completion");
    drive(1'b1, 1'b0);
    protected_drops = protected_drops + 1;
    if (pending_bank != held_pending || write_bank != held_writer)
      $fatal(1, "protected pending bank changed after second completion");

    // Even a coincident newer completion is dropped at the following boundary;
    // the bank whose slot was commanded is the one that becomes visible.
    drive(1'b1, 1'b1);
    protected_drops = protected_drops + 1;
    if (protect_pending || history_newest != held_pending ||
        presented_orientation != 1 || presentation_slot != 1 ||
        expected_applied_slot != 1 || command_slot != 1)
      $fatal(1, "protected portrait was not promoted under slot one");
    expect_matched("promoted portrait");

    // Reverse direction uses the same one-frame repeat/defer contract.
    producer_orientation = 1'b0;
    drive(1'b1, 1'b0);
    held_history = history_newest;
    held_pending = pending_bank;
    drive(1'b0, 1'b1);
    if (!protect_pending || command_slot != 0 || expected_applied_slot != 1 ||
        history_newest != held_history || presentation_slot != 1)
      $fatal(1, "landscape return was not deferred");
    drive(1'b0, 1'b1);
    if (protect_pending || history_newest != held_pending ||
        presented_orientation != 0 || presentation_slot != 0 ||
        expected_applied_slot != 0)
      $fatal(1, "landscape return did not promote under slot zero");
    expect_matched("returned landscape");

    // A menu-only forced transform reuses the immutable bank: one frame keeps
    // the old slot while commanding portrait, then the same bank adopts slot 1.
    configured_orientation = 2'd2;
    held_history = history_newest;
    drive(1'b0, 1'b1);
    if (history_newest != held_history || command_slot != 1 ||
        expected_applied_slot != 0 || presentation_slot != 0)
      $fatal(1, "menu-only transform did not schedule next-frame slot");
    expect_matched("menu transition repeat");
    drive(1'b0, 1'b1);
    if (history_newest != held_history || presentation_slot != 1 ||
        expected_applied_slot != 1 || command_slot != 1)
      $fatal(1, "menu-only transform did not adopt applied slot");
    expect_matched("menu transform applied");

    // Direct mode cannot repeat immutable pixels. A live/requested mismatch
    // blacks immediately, remains black for the command frame, and recovers
    // only after the matching slot is expected to be applied.
    enable = 1'b0;
    drive(1'b0, 1'b1);
    if (blank_presentation)
      $fatal(1, "matching direct portrait unexpectedly blanked");
    configured_orientation = 2'd0;
    producer_orientation = 1'b0;
    #1ps;
    if (!blank_presentation)
      $fatal(1, "direct live mismatch did not fail closed immediately");
    drive(1'b0, 1'b1);
    if (!blank_presentation || command_slot != 0 || expected_applied_slot != 1)
      $fatal(1, "direct mismatch command frame was not black");
    drive(1'b0, 1'b1);
    if (blank_presentation || presentation_slot != 0 ||
        expected_applied_slot != 0)
      $fatal(1, "direct mode did not recover under matching slot");

    // Direct pixels may remain visible briefly while buffered history primes.
    // The absence of an immutable frame must retain direct-mode fail-closed
    // behavior if live orientation changes during that interval.
    enable = 1'b1;
    producer_orientation = 1'b1;
    #1ps;
    if (!blank_presentation)
      $fatal(1, "direct-to-buffer priming mismatch did not fail closed");

    // Cold buffered portrait plus producer/consumer coincidence exercises the
    // live completion metadata path. No old matching history exists, so the
    // defer frame must be black before protected promotion.
    @(negedge clk);
    reset = 1'b1;
    enable = 1'b1;
    producer_orientation = 1'b1;
    repeat (2) @(posedge clk);
    @(negedge clk);
    reset = 1'b0;
    drive(1'b1, 1'b1);
    if (!protect_pending || !pending_valid || pending_bank != 0 ||
        command_slot != 1 || expected_applied_slot != 0 ||
        !blank_presentation || history_valid_count != 0)
      $fatal(1, "cold coincident portrait did not defer/fail closed");
    drive(1'b0, 1'b1);
    if (protect_pending || history_valid_count != 1 ||
        presented_orientation != 1 || presentation_slot != 1 ||
        expected_applied_slot != 1 || blank_presentation)
      $fatal(1, "cold protected portrait did not promote safely");
    expect_matched("cold portrait recovered");

    if (deferred_transitions != 3 || protected_drops != 3)
      $fatal(
          1,
          "coverage mismatch defers=%0d protected_drops=%0d",
          deferred_transitions,
          protected_drops
      );

    $display(
        "PASS APF orientation transition defers=%0d protected_drops=%0d menu_defer=1 direct_black=1 cold_black=1",
        deferred_transitions,
        protected_drops
    );
    $finish;
  end
endmodule
