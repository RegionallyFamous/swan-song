`timescale 1ns/1ps

module apf_late_frame_candidate_tb;
  reg clk = 1'b0;
  reg reset = 1'b1;
  reg pixel_enable = 1'b0;
  reg candidate_valid = 1'b0;
  reg [2:0] candidate_bank = 3'd0;
  reg [2:0] candidate_slot = 3'd0;

  wire candidate_take;
  wire presentation_valid;
  wire [2:0] presentation_bank;
  wire [2:0] presentation_slot;
  wire [2:0] expected_applied_slot;
  wire [2:0] command_for_next_frame;
  wire scheduled_valid;
  wire [2:0] scheduled_bank;
  wire [2:0] scheduled_slot;
  wire scheduled_protect_valid;
  wire [2:0] scheduled_protect_bank;
  wire promotion_pulse;
  wire repeat_pulse;
  wire blank_pulse;
  wire orientation_deferred_pulse;
  wire [8:0] x;
  wire [8:0] y;
  wire line_end;
  wire frame_boundary;
  wire apf_vs_phase;
  wire apf_hs_phase;
  wire apf_de_phase;
  wire apf_eol_phase;
  wire late_selection;

  integer pixel_events = 0;
  integer vs_events = 0;
  integer hs_events = 0;
  integer de_events = 0;
  integer eol_events = 0;
  integer late_events = 0;
  integer completed_geometry_frames = 0;

  always #5 clk = ~clk;

  apf_late_frame_candidate dut (
      .clk(clk),
      .reset(reset),
      .pixel_enable(pixel_enable),
      .candidate_valid(candidate_valid),
      .candidate_bank(candidate_bank),
      .candidate_slot(candidate_slot),
      .candidate_take(candidate_take),
      .presentation_valid(presentation_valid),
      .presentation_bank(presentation_bank),
      .presentation_slot(presentation_slot),
      .expected_applied_slot(expected_applied_slot),
      .command_for_next_frame(command_for_next_frame),
      .scheduled_valid(scheduled_valid),
      .scheduled_bank(scheduled_bank),
      .scheduled_slot(scheduled_slot),
      .scheduled_protect_valid(scheduled_protect_valid),
      .scheduled_protect_bank(scheduled_protect_bank),
      .promotion_pulse(promotion_pulse),
      .repeat_pulse(repeat_pulse),
      .blank_pulse(blank_pulse),
      .orientation_deferred_pulse(orientation_deferred_pulse),
      .x(x),
      .y(y),
      .line_end(line_end),
      .frame_boundary(frame_boundary),
      .apf_vs_phase(apf_vs_phase),
      .apf_hs_phase(apf_hs_phase),
      .apf_de_phase(apf_de_phase),
      .apf_eol_phase(apf_eol_phase),
      .late_selection(late_selection)
  );

  always @(posedge clk) begin
    if (!reset && pixel_enable && completed_geometry_frames == 0) begin
      pixel_events = pixel_events + 1;
      if (apf_vs_phase) vs_events = vs_events + 1;
      if (apf_hs_phase) begin
        hs_events = hs_events + 1;
        if (x != 9'd7)
          $fatal(1, "HS escaped x=7");
      end
      if (apf_de_phase) begin
        de_events = de_events + 1;
        if (x < 9'd9 || x > 9'd232 || y < 9'd256 || y > 9'd399)
          $fatal(1, "DE escaped guarded 224x144 window");
      end
      if (apf_eol_phase) begin
        eol_events = eol_events + 1;
        if (x != 9'd233 || y < 9'd256 || y > 9'd399)
          $fatal(1, "EOL escaped x=233 active-line position");
      end
      if (late_selection) late_events = late_events + 1;
      if (frame_boundary) begin
        if (pixel_events != 102400 || vs_events != 1 || hs_events != 400 ||
            de_events != 32256 || eol_events != 144 || late_events != 1)
          $fatal(
              1,
              "bad geometry pixels=%0d vs=%0d hs=%0d de=%0d eol=%0d late=%0d",
              pixel_events,
              vs_events,
              hs_events,
              de_events,
              eol_events,
              late_events
          );
        completed_geometry_frames = 1;
      end
    end
  end

  task automatic wait_late_result;
    begin
      while (!(x == 9'd0 && y == 9'd256)) @(negedge clk);
      @(posedge clk);
      #1ps;
    end
  endtask

  task automatic wait_boundary_result;
    begin
      while (!(x == 9'd255 && y == 9'd399)) @(negedge clk);
      @(posedge clk);
      #1ps;
    end
  endtask

  initial begin
    repeat (3) @(posedge clk);

    // Disabled pixel enables must hold the candidate raster exactly.
    if (x != 0 || y != 0)
      $fatal(1, "raster did not reset to zero");
    repeat (4) @(posedge clk);
    if (x != 0 || y != 0)
      $fatal(1, "raster advanced while pixel_enable was low");

    @(negedge clk);
    reset = 1'b0;
    pixel_enable = 1'b1;

    // A complete slot-matched candidate is promoted at the late gate.
    candidate_valid = 1'b1;
    candidate_bank = 3'd1;
    candidate_slot = 3'd0;
    wait_late_result();
    if (!candidate_take || !promotion_pulse || repeat_pulse || blank_pulse ||
        !presentation_valid || presentation_bank != 3'd1 ||
        presentation_slot != 3'd0)
      $fatal(1, "slot-matched candidate was not promoted");
    @(negedge clk);
    candidate_valid = 1'b0;

    // With no completion, the same complete matching frame is repeated.
    wait_late_result();
    if (!repeat_pulse || promotion_pulse || blank_pulse || candidate_take ||
        presentation_bank != 3'd1 || presentation_slot != 3'd0)
      $fatal(1, "no-completion frame did not repeat matching history");

    // A portrait candidate cannot be shown under the currently applied
    // landscape slot. Claim/protect it, repeat bank 1, and command slot 1 for
    // the next APF frame.
    @(negedge clk);
    candidate_valid = 1'b1;
    candidate_bank = 3'd2;
    candidate_slot = 3'd1;
    wait_late_result();
    if (!candidate_take || !orientation_deferred_pulse || !repeat_pulse ||
        promotion_pulse || blank_pulse || command_for_next_frame != 3'd1 ||
        expected_applied_slot != 3'd0 || !scheduled_valid ||
        scheduled_bank != 3'd2 || scheduled_slot != 3'd1 ||
        !scheduled_protect_valid || scheduled_protect_bank != 3'd2 ||
        presentation_bank != 3'd1)
      $fatal(1, "orientation mismatch was not deferred safely");

    // Upstream may offer a newer completion, but the protected scheduled bank
    // has priority and candidate_take must remain low until it is presented.
    @(negedge clk);
    candidate_bank = 3'd3;
    candidate_slot = 3'd0;
    wait_boundary_result();
    if (expected_applied_slot != 3'd1)
      $fatal(1, "next-frame slot command did not become expected applied slot");
    wait_late_result();
    if (!promotion_pulse || candidate_take || repeat_pulse || blank_pulse ||
        !presentation_valid || presentation_bank != 3'd2 ||
        presentation_slot != 3'd1 || scheduled_valid ||
        scheduled_protect_valid)
      $fatal(1, "protected candidate was not promoted with its applied slot");

    // The waiting landscape candidate is considered only at the following
    // late gate, proving backpressure rather than unsafe supersession.
    wait_late_result();
    if (!candidate_take || !orientation_deferred_pulse || !repeat_pulse ||
        promotion_pulse || command_for_next_frame != 3'd0 ||
        expected_applied_slot != 3'd1 || !scheduled_valid ||
        scheduled_bank != 3'd3 || presentation_bank != 3'd2)
      $fatal(1, "waiting opposite-slot candidate was not deferred in order");
    @(negedge clk);
    candidate_valid = 1'b0;
    wait_boundary_result();
    if (expected_applied_slot != 3'd0)
      $fatal(1, "return command did not become expected slot");
    wait_late_result();
    if (!promotion_pulse || presentation_bank != 3'd3 ||
        presentation_slot != 3'd0 || scheduled_valid)
      $fatal(1, "return candidate was not promoted under matching slot");

    // After reset there is no complete matching presentation. A mismatched
    // first candidate is scheduled, but fallback must be blank rather than
    // displaying pixels under the wrong scaler orientation.
    @(negedge clk);
    reset = 1'b1;
    candidate_valid = 1'b1;
    candidate_bank = 3'd4;
    candidate_slot = 3'd1;
    repeat (2) @(posedge clk);
    @(negedge clk);
    reset = 1'b0;
    wait_late_result();
    if (!candidate_take || !orientation_deferred_pulse || !blank_pulse ||
        repeat_pulse || promotion_pulse || presentation_valid ||
        !scheduled_valid || scheduled_bank != 3'd4)
      $fatal(1, "cold mismatched candidate did not fail closed");

    if (completed_geometry_frames != 1)
      $fatal(1, "default exact-60 geometry was not checked");

    $display(
        "PASS APF late-frame candidate exact60=1 no_completion_repeat=1 slot_defer=2 protected=1 cold_blank=1"
    );
    $finish;
  end
endmodule
