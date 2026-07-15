`timescale 1ns/1ps
`default_nettype none

module apf_savestate_v2_owner_tb;
  reg clk = 1'b0;
  reg lifecycle_reset_n = 1'b0;
  always #5 clk = ~clk;

  reg capture_request = 1'b0;
  reg restore_request = 1'b0;
  reg staged_image_valid = 1'b0;
  reg [31:0] staged_image_generation = 32'd0;
  reg cancel = 1'b0;
  wire capture_busy;
  wire capture_done;
  wire capture_failed;
  wire restore_busy;
  wire restore_done;
  wire restore_failed;
  wire protocol_error;
  wire fatal_reset_hold;
  wire staged_image_lock;
  wire runtime_pause_request;
  reg runtime_pause_ack = 1'b0;
  reg sdram_quiescent = 1'b0;
  wire device_freeze;
  reg [2:0] device_frozen = 3'b000;
  reg [2:0] device_settling = 3'b000;
  reg device_protocol_fault = 1'b0;
  wire stage_acquire;
  reg stage_granted = 1'b0;
  wire capture_start;
  reg capture_complete = 1'b0;
  reg capture_error = 1'b0;
  wire restore_apply_start;
  reg restore_apply_complete = 1'b0;
  reg restore_apply_error = 1'b0;
  wire datapath_abort;
  reg datapath_quiescent = 1'b1;

  integer capture_starts = 0;
  integer restore_starts = 0;
  integer abort_cycles = 0;
  integer refresh_low_active_cycles = 0;
  integer starts_before = 0;
  integer prestart_terminal_cases = 0;
  integer wrong_operation_cases = 0;
  integer late_error_cases = 0;

  apf_savestate_v2_owner #(
      .DEVICE_COUNT(3),
      .MAX_PHASE_CYCLES(12)
  ) dut (
      .clk(clk),
      .lifecycle_reset_n(lifecycle_reset_n),
      .capture_request(capture_request),
      .restore_request(restore_request),
      .staged_image_valid(staged_image_valid),
      .staged_image_generation(staged_image_generation),
      .cancel(cancel),
      .capture_busy(capture_busy),
      .capture_done(capture_done),
      .capture_failed(capture_failed),
      .restore_busy(restore_busy),
      .restore_done(restore_done),
      .restore_failed(restore_failed),
      .protocol_error(protocol_error),
      .fatal_reset_hold(fatal_reset_hold),
      .staged_image_lock(staged_image_lock),
      .runtime_pause_request(runtime_pause_request),
      .runtime_pause_ack(runtime_pause_ack),
      .sdram_quiescent(sdram_quiescent),
      .device_freeze(device_freeze),
      .device_frozen(device_frozen),
      .device_settling(device_settling),
      .device_protocol_fault(device_protocol_fault),
      .stage_acquire(stage_acquire),
      .stage_granted(stage_granted),
      .capture_start(capture_start),
      .capture_complete(capture_complete),
      .capture_error(capture_error),
      .restore_apply_start(restore_apply_start),
      .restore_apply_complete(restore_apply_complete),
      .restore_apply_error(restore_apply_error),
      .datapath_abort(datapath_abort),
      .datapath_quiescent(datapath_quiescent)
  );

  always @(posedge clk) begin
    if (capture_start)
      capture_starts <= capture_starts + 1;
    if (restore_apply_start)
      restore_starts <= restore_starts + 1;
    if (datapath_abort)
      abort_cycles <= abort_cycles + 1;
    if ((capture_busy || restore_busy) && stage_granted && !sdram_quiescent)
      refresh_low_active_cycles <= refresh_low_active_cycles + 1;
    if ((capture_start || restore_apply_start) &&
        !(runtime_pause_request && runtime_pause_ack &&
          device_freeze && (&device_frozen) && stage_acquire && stage_granted &&
          datapath_quiescent))
      $fatal(1, "data plane started outside the complete atomic window");
    if (restore_apply_start &&
        (!staged_image_valid || !staged_image_lock))
      $fatal(1, "restore started without current locked validation");
    if (capture_start && restore_apply_start)
      $fatal(1, "capture and restore started together");
  end

  task automatic tick;
    begin
      @(posedge clk);
      #1;
    end
  endtask

  task automatic expect_true(input bit condition, input string message);
    begin
      if (!condition)
        $fatal(1, "%s", message);
    end
  endtask

  task automatic pulse_capture;
    begin
      capture_request = 1'b1;
      tick();
      capture_request = 1'b0;
    end
  endtask

  task automatic pulse_restore;
    begin
      restore_request = 1'b1;
      tick();
      restore_request = 1'b0;
    end
  endtask

  task automatic reach_atomic_window(input bit restore_kind);
    begin
      tick();
      expect_true(runtime_pause_request && !device_freeze && !stage_acquire,
                  "pause was not the first ownership phase");
      runtime_pause_ack = 1'b1;
      tick();
      expect_true(device_freeze && !stage_acquire,
                  "devices did not freeze after runtime pause");
      device_frozen = 3'b111;
      tick();
      expect_true(!stage_acquire,
                  "stage acquisition escaped before initial SDRAM drain");
      sdram_quiescent = 1'b1;
      tick();
      expect_true(stage_acquire,
                  "stage acquisition did not follow drain and freeze");
      stage_granted = 1'b1;
      tick();
      if (restore_kind)
        expect_true(restore_apply_start && !capture_start,
                    "restore did not start exactly at the atomic window");
      else
        expect_true(capture_start && !restore_apply_start,
                    "capture did not start exactly at the atomic window");

      // Let the registered one-cycle start retire before the data plane
      // advertises its first outstanding request.
      tick();
      expect_true(!capture_start && !restore_apply_start,
                  "data-plane start was not a one-cycle pulse");

      // A legitimate staging request or periodic refresh deasserts the global
      // quiescent observation. It must not abort an already granted operation.
      sdram_quiescent = 1'b0;
      datapath_quiescent = 1'b0;
      tick();
      expect_true(!capture_start && !restore_apply_start && !datapath_abort,
                  "normal staging traffic was treated as an invariant loss");
    end
  endtask

  task automatic finish_success(input bit restore_kind);
    begin
      // Terminal may arrive before the final physical response; ownership is
      // retained until the independent data-plane drain acknowledges idle.
      if (restore_kind)
        restore_apply_complete = 1'b1;
      else
        capture_complete = 1'b1;
      tick();
      restore_apply_complete = 1'b0;
      capture_complete = 1'b0;
      expect_true(stage_acquire && stage_granted,
                  "terminal result revoked a busy data plane");
      repeat (2) tick();
      datapath_quiescent = 1'b1;
      tick();
      expect_true(!stage_acquire && device_freeze && runtime_pause_request,
                  "drained operation did not revoke stage first");
      stage_granted = 1'b0;
      tick();
      expect_true(!device_freeze && runtime_pause_request,
                  "runtime resumed before device thaw");
      device_frozen = 3'b000;
      tick();
      expect_true(!runtime_pause_request &&
                  ((restore_kind && restore_busy) ||
                   (!restore_kind && capture_busy)),
                  "result published before pause release handshake");
      repeat (2) begin
        tick();
        expect_true(!restore_done && !capture_done,
                    "completion escaped while runtime ack remained high");
      end
      runtime_pause_ack = 1'b0;
      tick();
      if (restore_kind)
        expect_true(restore_done && !restore_busy && !restore_failed,
                    "successful restore result was wrong");
      else
        expect_true(capture_done && !capture_busy && !capture_failed,
                    "successful capture result was wrong");
      expect_true(!fatal_reset_hold && !stage_acquire && !device_freeze,
                  "successful operation did not release all ownership");
      sdram_quiescent = 1'b0;
    end
  endtask

  task automatic drain_recoverable_abort(input bit restore_kind);
    begin
      expect_true(datapath_abort && stage_acquire,
                  "abort did not retain stage routing while data was active");
      repeat (2) tick();
      datapath_quiescent = 1'b1;
      tick();
      expect_true(!stage_acquire && device_freeze,
                  "abort revoked routing before data-plane drain");
      stage_granted = 1'b0;
      tick();
      device_frozen = 3'b000;
      tick();
      expect_true(!runtime_pause_request,
                  "recoverable abort did not request runtime release");
      runtime_pause_ack = 1'b0;
      tick();
      if (restore_kind)
        expect_true(restore_failed && !restore_busy,
                    "pre-apply restore abort result was wrong");
      else
        expect_true(capture_failed && !capture_busy,
                    "capture abort result was wrong");
      expect_true(!fatal_reset_hold,
                  "pre-apply/capture abort incorrectly became fatal");
      sdram_quiescent = 1'b0;
    end
  endtask

  task automatic unwind_prestart_abort(input bit restore_kind);
    begin
      expect_true(datapath_abort && stage_acquire,
                  "pre-start terminal did not enter abort drain");
      datapath_quiescent = 1'b1;
      tick();
      expect_true(!stage_acquire && device_freeze,
                  "idle pre-start abort retained stage acquisition");
      stage_granted = 1'b0;
      tick();
      device_frozen = 3'b000;
      tick();
      expect_true(!runtime_pause_request,
                  "pre-start abort did not begin runtime thaw");
      runtime_pause_ack = 1'b0;
      tick();
      if (restore_kind)
        expect_true(restore_failed && !restore_busy,
                    "pre-start restore terminal did not fail cleanly");
      else
        expect_true(capture_failed && !capture_busy,
                    "pre-start capture terminal did not fail cleanly");
      expect_true(protocol_error && !fatal_reset_hold && !staged_image_lock,
                  "pre-start terminal was not a recoverable protocol fault");
      sdram_quiescent = 1'b0;
    end
  endtask

  task automatic drain_fatal_abort;
    begin
      expect_true(datapath_abort && stage_acquire && fatal_reset_hold &&
                  restore_failed && !restore_busy && device_freeze &&
                  runtime_pause_request,
                  "post-barrier fault did not enter fatal drain");
      repeat (2) tick();
      datapath_quiescent = 1'b1;
      tick();
      expect_true(!stage_acquire && device_freeze && fatal_reset_hold,
                  "fatal drain revoked stage before quiescence");
      stage_granted = 1'b0;
      tick();
      repeat (2) begin
        tick();
        expect_true(fatal_reset_hold && runtime_pause_request && device_freeze,
                    "fatal reset/freeze was not sticky");
      end
    end
  endtask

  task automatic clean_lifecycle_reset;
    begin
      capture_request = 1'b0;
      restore_request = 1'b0;
      cancel = 1'b0;
      capture_complete = 1'b0;
      capture_error = 1'b0;
      restore_apply_complete = 1'b0;
      restore_apply_error = 1'b0;
      runtime_pause_ack = 1'b0;
      sdram_quiescent = 1'b0;
      device_frozen = 3'b000;
      stage_granted = 1'b0;
      datapath_quiescent = 1'b1;
      staged_image_valid = 1'b0;
      lifecycle_reset_n = 1'b0;
      tick();
      lifecycle_reset_n = 1'b1;
      tick();
      expect_true(!fatal_reset_hold && !protocol_error &&
                  !capture_busy && !restore_busy && !staged_image_lock,
                  "clean lifecycle reset did not restore idle ownership");
    end
  endtask

  initial begin
    repeat (3) tick();
    lifecycle_reset_n = 1'b1;
    tick();

    // Capture: hierarchical pause/freeze/drain, normal active SDRAM traffic,
    // data-plane drain, reverse release, and explicit runtime thaw ack.
    pulse_capture();
    expect_true(capture_busy && staged_image_lock,
                "capture request was not accepted cleanly");
    reach_atomic_window(1'b0);
    finish_success(1'b0);

    // A held stale terminal on the command-acceptance edge is rejected before
    // any ownership or data-plane start is possible.
    starts_before = capture_starts;
    capture_complete = 1'b1;
    pulse_capture();
    capture_complete = 1'b0;
    expect_true(protocol_error && capture_failed && !capture_busy &&
                !runtime_pause_request && !staged_image_lock &&
                capture_starts == starts_before,
                "terminal held at request was not rejected in IDLE");
    prestart_terminal_cases = prestart_terminal_cases + 1;
    clean_lifecycle_reset();

    // A one-cycle terminal pulse while waiting for the cooperative pause must
    // be converted into a sticky protocol failure, not disappear before grant.
    starts_before = capture_starts;
    pulse_capture();
    capture_complete = 1'b1;
    tick();
    capture_complete = 1'b0;
    expect_true(datapath_abort && capture_starts == starts_before,
                "WAIT_PAUSE stale pulse escaped pre-start rejection");
    unwind_prestart_abort(1'b0);
    prestart_terminal_cases = prestart_terminal_cases + 1;
    clean_lifecycle_reset();

    // The same protection applies after runtime pause while devices/SDRAM are
    // still reaching the atomic boundary, including a wrong-operation pulse.
    starts_before = capture_starts;
    pulse_capture();
    runtime_pause_ack = 1'b1;
    tick();
    expect_true(device_freeze && !stage_acquire,
                "test did not reach WAIT_QUIESCE");
    restore_apply_error = 1'b1;
    tick();
    restore_apply_error = 1'b0;
    expect_true(datapath_abort && capture_starts == starts_before,
                "WAIT_QUIESCE stale pulse escaped pre-start rejection");
    unwind_prestart_abort(1'b0);
    prestart_terminal_cases = prestart_terminal_cases + 1;
    clean_lifecycle_reset();

    // A terminal coincident with the would-be grant/start edge wins over the
    // start and aborts without emitting even a one-cycle data-plane command.
    starts_before = capture_starts;
    pulse_capture();
    runtime_pause_ack = 1'b1;
    tick();
    device_frozen = 3'b111;
    sdram_quiescent = 1'b1;
    tick();
    expect_true(stage_acquire, "test did not reach WAIT_STAGE");
    stage_granted = 1'b1;
    capture_complete = 1'b1;
    tick();
    capture_complete = 1'b0;
    expect_true(datapath_abort && !capture_start &&
                capture_starts == starts_before,
                "terminal on grant edge did not suppress capture_start");
    unwind_prestart_abort(1'b0);
    prestart_terminal_cases = prestart_terminal_cases + 1;
    clean_lifecycle_reset();

    // Invalid staged input is rejected before the machine is paused.
    staged_image_valid = 1'b0;
    staged_image_generation = 32'd4;
    pulse_restore();
    expect_true(restore_failed && !restore_busy && !runtime_pause_request &&
                restore_starts == 0,
                "invalid staged image reached live ownership");

    // The generation is captured and locked at request acceptance. Replacing
    // it while waiting for pause is a recoverable pre-barrier failure.
    staged_image_valid = 1'b1;
    staged_image_generation = 32'd5;
    pulse_restore();
    expect_true(staged_image_lock, "restore did not lock its staged generation");
    staged_image_generation = 32'd6;
    tick();
    expect_true(datapath_abort && restore_starts == 0,
                "generation replacement was not rejected before apply");
    tick();
    tick();
    tick();
    expect_true(!runtime_pause_request,
                "pre-apply generation failure did not enter thaw handshake");
    runtime_pause_ack = 1'b0;
    tick();
    expect_true(restore_failed && !restore_busy && !fatal_reset_hold &&
                !staged_image_lock && restore_starts == 0,
                "pre-apply generation failure did not unwind safely");

    // Fully validated restore, including the same legal post-grant SDRAM
    // activity that exposed the first owner draft's continuous-drain bug.
    staged_image_generation = 32'd7;
    pulse_restore();
    reach_atomic_window(1'b1);
    finish_success(1'b1);

    // A terminal for the inactive restore operation during a capture is a CDC
    // protocol fault. It must poison/drain the capture rather than be ignored.
    pulse_capture();
    reach_atomic_window(1'b0);
    restore_apply_complete = 1'b1;
    tick();
    restore_apply_complete = 1'b0;
    expect_true(protocol_error && datapath_abort && !fatal_reset_hold,
                "wrong-operation terminal did not fail capture closed");
    drain_recoverable_abort(1'b0);
    wrong_operation_cases = wrong_operation_cases + 1;
    clean_lifecycle_reset();

    // Completion can precede the final physical reply. A current-operation
    // error on the same edge as final quiescence must supersede that success.
    pulse_capture();
    reach_atomic_window(1'b0);
    capture_complete = 1'b1;
    tick();
    capture_complete = 1'b0;
    expect_true(stage_acquire && stage_granted,
                "early capture completion did not retain ownership");
    capture_error = 1'b1;
    datapath_quiescent = 1'b1;
    tick();
    capture_error = 1'b0;
    expect_true(datapath_abort && stage_acquire && !fatal_reset_hold,
                "late capture error lost to same-edge quiescence");
    datapath_quiescent = 1'b0;
    drain_recoverable_abort(1'b0);
    expect_true(!protocol_error,
                "legal late current-operation error was mislabeled stale");
    late_error_cases = late_error_cases + 1;

    // A cancelled capture poisons/drains staging but never becomes fatal.
    pulse_capture();
    reach_atomic_window(1'b0);
    cancel = 1'b1;
    tick();
    cancel = 1'b0;
    drain_recoverable_abort(1'b0);

    // A capture terminal during restore is a wrong-operation protocol fault.
    // Because apply has already crossed the mutation barrier, it is fatal.
    staged_image_valid = 1'b1;
    staged_image_generation = 32'd8;
    pulse_restore();
    reach_atomic_window(1'b1);
    capture_complete = 1'b1;
    tick();
    capture_complete = 1'b0;
    expect_true(protocol_error && datapath_abort && fatal_reset_hold,
                "wrong-operation terminal did not fail restore closed");
    drain_fatal_abort();
    wrong_operation_cases = wrong_operation_cases + 1;
    clean_lifecycle_reset();

    // The late-error rule is symmetric for restore. An error coincident with
    // final quiescence after early completion must become a fatal reset hold.
    staged_image_valid = 1'b1;
    staged_image_generation = 32'd9;
    pulse_restore();
    reach_atomic_window(1'b1);
    restore_apply_complete = 1'b1;
    tick();
    restore_apply_complete = 1'b0;
    expect_true(stage_acquire && stage_granted,
                "early restore completion did not retain ownership");
    restore_apply_error = 1'b1;
    datapath_quiescent = 1'b1;
    tick();
    restore_apply_error = 1'b0;
    expect_true(datapath_abort && stage_acquire && fatal_reset_hold,
                "late restore error lost to same-edge quiescence");
    datapath_quiescent = 1'b0;
    drain_fatal_abort();
    late_error_cases = late_error_cases + 1;

    // Console reset must not clear fatal state; only this explicit lifecycle
    // reset represents a clean title/PLL reload.
    clean_lifecycle_reset();
    expect_true(!fatal_reset_hold && !protocol_error && !restore_failed,
                "clean lifecycle reset did not clear fatal ownership state");

    // A pre-pause timeout is recoverable and starts neither data plane.
    starts_before = capture_starts;
    pulse_capture();
    repeat (18) tick();
    expect_true(capture_failed && !fatal_reset_hold &&
                capture_starts == starts_before,
                "pre-apply timeout did not fail closed");

    // Simultaneous commands never acquire or mutate live state.
    capture_request = 1'b1;
    restore_request = 1'b1;
    tick();
    capture_request = 1'b0;
    restore_request = 1'b0;
    expect_true(protocol_error && capture_failed && restore_failed &&
                !runtime_pause_request && !capture_busy && !restore_busy,
                "simultaneous commands did not fail closed");

    expect_true(refresh_low_active_cycles > 0,
                "test never exercised legal non-quiescent staging traffic");
    expect_true(prestart_terminal_cases == 4 &&
                wrong_operation_cases == 2 && late_error_cases == 2,
                "adversarial terminal case coverage count was incomplete");
    $display("PASS APF savestate v2 atomic owner capture_starts=%0d restore_starts=%0d abort_cycles=%0d active_sdram_cycles=%0d prestart_terminals=%0d wrong_operation=%0d late_errors=%0d generation_lock=1 thaw_ack=1 fatal_drain=1",
             capture_starts, restore_starts, abort_cycles,
             refresh_low_active_cycles, prestart_terminal_cases,
             wrong_operation_cases, late_error_cases);
    $finish;
  end
endmodule

`default_nettype wire
