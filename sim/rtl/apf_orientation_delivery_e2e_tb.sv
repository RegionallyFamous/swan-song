`timescale 1ns/1ps

// End-to-end proof of the production orientation handoff timeline:
//
//   system boundary B0 -> bundled CDC -> APF frame F1 EOL command
//   -> APF applies that command at F2 VS -> F2 active pixels use new bank
//
// The guard is allowed to change its presentation bookkeeping at B1, shortly
// before F2 VS, because the raster is vertically blank until the F2 active
// area. It must never expose active pixels under a different modeled APF slot.
module apf_orientation_delivery_e2e_tb;
  localparam integer MIN_BOUNDARY_TO_VS_CLOCKS = 717;
  localparam integer FRAME_CLOCKS = 397 * 258;

  reg clk_sys;
  reg clk_video;
  reg reset = 1'b1;
  reg reset_n = 1'b0;
  reg frame_boundary = 1'b0;
  reg frame_start_video = 1'b0;
  reg buffered_mode = 1'b1;
  reg current_frame_valid = 1'b1;
  reg current_orientation = 1'b0;
  reg producer_orientation = 1'b1;
  reg candidate_valid = 1'b1;
  reg candidate_orientation = 1'b1;
  reg [1:0] configured_orientation = 2'd0;
  reg landscape_180 = 1'b0;

  wire defer_candidate;
  wire protect_pending;
  wire [2:0] command_slot;
  wire [2:0] expected_applied_slot;
  wire [2:0] presentation_slot;
  wire blank_presentation;
  wire scaler_update_pending;
  wire [2:0] scaler_slot_video;
  wire [23:0] eol_word_video;

  integer phase_residue;
  integer capture_clocks;
  integer max_capture_clocks = 0;

  // The real clocks are 36.864 MHz and 6.144 MHz. Their exact period is not
  // material to this cycle-domain proof; preserving the 6:1 relationship is.
  initial begin
    clk_sys = 1'b0;
    forever #1 clk_sys = ~clk_sys;
  end
  initial begin
    clk_video = 1'b0;
    forever #6 clk_video = ~clk_video;
  end

  apf_orientation_transition_guard guard (
      .clk(clk_sys),
      .reset(reset),
      .frame_boundary(frame_boundary),
      .buffered_mode(buffered_mode),
      .current_frame_valid(current_frame_valid),
      .current_orientation(current_orientation),
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

  apf_scaler_selector selector (
      .reset_n(reset_n),
      .clk_sys(clk_sys),
      .requested_slot_sys(command_slot),
      .update_pending_sys(scaler_update_pending),
      .clk_video(clk_video),
      .frame_start_video(frame_start_video),
      .scaler_slot_video(scaler_slot_video),
      .eol_word_video(eol_word_video)
  );

  // Behavioral APF next-frame contract. The slot last emitted after an active
  // line in frame Fn becomes applied at the VS beginning frame Fn+1.
  reg [2:0] last_frame_eol_slot;
  reg [2:0] modeled_apf_applied_slot;
  always @(posedge clk_video or negedge reset_n) begin
    if (!reset_n) begin
      modeled_apf_applied_slot <= 3'd0;
    end else if (frame_start_video) begin
      modeled_apf_applied_slot <= last_frame_eol_slot;
    end
  end

  task automatic apply_reset;
    begin
      @(negedge clk_sys);
      reset = 1'b1;
      reset_n = 1'b0;
      frame_boundary = 1'b0;
      frame_start_video = 1'b0;
      last_frame_eol_slot = 3'd0;
      repeat (4) @(posedge clk_sys);
      repeat (4) @(posedge clk_video);
      @(negedge clk_sys);
      reset = 1'b0;
      reset_n = 1'b1;
      repeat (5) @(posedge clk_sys);
      repeat (5) @(posedge clk_video);
    end
  endtask

  task automatic pulse_boundary(input bit expect_defer);
    begin
      @(negedge clk_sys);
      // The last active-line EOL has already been emitted by this point.
      last_frame_eol_slot = scaler_slot_video;
      frame_boundary = 1'b1;
      #1ps;
      if (defer_candidate !== expect_defer)
        $fatal(
            1,
            "boundary defer mismatch expected=%0d actual=%0d protect=%0d candidate=%0d",
            expect_defer,
            defer_candidate,
            protect_pending,
            candidate_valid
        );
      if (eol_word_video !== {8'd0, scaler_slot_video, 10'd0, 3'b000})
        $fatal(1, "EOL encoding disagreed with scaler slot at boundary");
      @(posedge clk_sys);
      #1ps;
      @(negedge clk_sys);
      frame_boundary = 1'b0;
    end
  endtask

  task automatic advance_to_next_vs(input bit require_pending);
    integer clock_count;
    begin
      for (clock_count = 0;
           clock_count < MIN_BOUNDARY_TO_VS_CLOCKS;
           clock_count = clock_count + 1)
        @(posedge clk_video);
      #1ps;

      if (require_pending &&
          (!selector.pending_valid_video || selector.request_arrived_video))
        $fatal(
            1,
            "new slot was not safely pending before next VS pending=%0d arrived=%0d",
            selector.pending_valid_video,
            selector.request_arrived_video
        );

      @(negedge clk_video);
      frame_start_video = 1'b1;
      @(posedge clk_video);
      #1ps;
      @(negedge clk_video);
      frame_start_video = 1'b0;
    end
  endtask

  task automatic advance_to_end_of_frame;
    integer clock_count;
    begin
      for (clock_count = MIN_BOUNDARY_TO_VS_CLOCKS;
           clock_count < FRAME_CLOCKS;
           clock_count = clock_count + 1)
        @(posedge clk_video);
    end
  endtask

  task automatic expect_active_match(input string label_text);
    begin
      #1ps;
      if (blank_presentation ||
          presentation_slot != modeled_apf_applied_slot)
        $fatal(
            1,
            "%0s blank=%0d presentation=%0d modeled_apf=%0d command=%0d scaler=%0d",
            label_text,
            blank_presentation,
            presentation_slot,
            modeled_apf_applied_slot,
            command_slot,
            scaler_slot_video
        );
    end
  endtask

  initial begin
    // Sweep every possible system-clock residue inside one 6:1 video period.
    // This turns the boundary-to-VS budget claim into a phase-independent
    // proof rather than relying on one favorable clock alignment.
    for (phase_residue = 0; phase_residue < 6;
         phase_residue = phase_residue + 1) begin
      buffered_mode = 1'b1;
      current_frame_valid = 1'b1;
      current_orientation = 1'b0;
      producer_orientation = 1'b1;
      candidate_valid = 1'b1;
      candidate_orientation = 1'b1;
      apply_reset();
      repeat (phase_residue) @(posedge clk_sys);
      pulse_boundary(1'b1);
      if (!protect_pending || !scaler_update_pending ||
          expected_applied_slot != 0 || command_slot != 1)
        $fatal(1, "phase %0d did not launch guarded CDC update", phase_residue);

      capture_clocks = 0;
      while (!selector.pending_valid_video && capture_clocks < 32) begin
        @(posedge clk_video);
        #1ps;
        capture_clocks = capture_clocks + 1;
      end
      if (!selector.pending_valid_video || selector.request_arrived_video)
        $fatal(1, "phase %0d did not settle in video domain", phase_residue);
      if (capture_clocks > max_capture_clocks)
        max_capture_clocks = capture_clocks;
      if (capture_clocks >= MIN_BOUNDARY_TO_VS_CLOCKS)
        $fatal(1, "phase %0d exhausted the production VS budget", phase_residue);
    end

    // Reset after the phase sweep and run complete buffered/APF and direct/APF
    // frame sequences with the same production modules.
    buffered_mode = 1'b1;
    current_frame_valid = 1'b1;
    current_orientation = 1'b0;
    producer_orientation = 1'b1;
    candidate_valid = 1'b1;
    candidate_orientation = 1'b1;
    apply_reset();

    // B0 ends landscape F0. Portrait candidate is reserved, while landscape
    // history repeats through F1 and the new slot is emitted in F1 EOL words.
    pulse_boundary(1'b1);
    if (!protect_pending || !scaler_update_pending || command_slot != 1 ||
        expected_applied_slot != 0 || presentation_slot != 0)
      $fatal(1, "B0 did not reserve portrait and repeat landscape");
    advance_to_next_vs(1'b1);
    if (scaler_slot_video != 1 || eol_word_video != 24'h002000 ||
        modeled_apf_applied_slot != 0 || expected_applied_slot != 0)
      $fatal(1, "F1 did not emit portrait while APF retained landscape");
    expect_active_match("F1 repeated landscape");

    // At B1 the protected bank becomes the F2 presentation. APF is still on
    // slot zero during vertical blank, then consumes F1's EOL slot at F2 VS.
    advance_to_end_of_frame();
    pulse_boundary(1'b0);
    candidate_valid = 1'b0;
    current_orientation = 1'b1;
    if (protect_pending || presentation_slot != 1 ||
        expected_applied_slot != 1 ||
        modeled_apf_applied_slot != 0)
      $fatal(1, "B1 did not promote only inside F2 vertical blank");
    advance_to_next_vs(1'b0);
    if (modeled_apf_applied_slot != 1 ||
        expected_applied_slot != modeled_apf_applied_slot)
      $fatal(1, "APF did not apply F1 portrait command at F2 VS");
    expect_active_match("F2 portrait promotion");

    // Repeat the proof in direct mode. With no immutable history, active F1
    // is black; output recovers only after APF applies the F1 EOL command.
    buffered_mode = 1'b0;
    current_frame_valid = 1'b0;
    current_orientation = 1'b0;
    producer_orientation = 1'b1;
    candidate_valid = 1'b0;
    apply_reset();

    pulse_boundary(1'b0);
    if (!blank_presentation || !scaler_update_pending || command_slot != 1 ||
        expected_applied_slot != 0)
      $fatal(1, "direct B0 mismatch did not fail closed");
    advance_to_next_vs(1'b1);
    if (!blank_presentation || modeled_apf_applied_slot != 0 ||
        scaler_slot_video != 1 || eol_word_video != 24'h002000)
      $fatal(1, "direct F1 was not black while emitting portrait");
    advance_to_end_of_frame();
    pulse_boundary(1'b0);
    if (blank_presentation || presentation_slot != 1 ||
        expected_applied_slot != 1 ||
        modeled_apf_applied_slot != 0)
      $fatal(1, "direct recovery was not scheduled in vertical blank");
    advance_to_next_vs(1'b0);
    expect_active_match("direct F2 portrait recovery");

    $display(
        "PASS APF orientation delivery e2e phases=6 max_capture_clocks=%0d min_boundary_to_vs=%0d frame_clocks=%0d buffered_repeat=1 direct_black=1",
        max_capture_clocks,
        MIN_BOUNDARY_TO_VS_CLOCKS,
        FRAME_CLOCKS
    );
    $finish;
  end
endmodule
