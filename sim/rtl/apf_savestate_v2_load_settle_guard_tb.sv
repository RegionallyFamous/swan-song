`timescale 1ns/1ps
`default_nettype none

module apf_savestate_v2_load_settle_guard_tb;
  reg clk = 1'b0;
  reg lifecycle_reset_n = 1'b0;
  always #5 clk = ~clk;

  reg capture_request = 1'b0;
  reg restore_request = 1'b0;
  reg staged_image_valid = 1'b1;
  reg [31:0] staged_image_generation = 32'h1234_5678;
  reg cancel = 1'b0;
  wire capture_busy;
  wire capture_done;
  wire capture_failed;
  wire restore_busy;
  wire restore_done;
  wire restore_failed;
  wire owner_protocol_error;
  wire fatal_reset_hold;
  wire staged_image_lock;
  wire runtime_pause_request;
  reg runtime_pause_ack = 1'b0;
  reg sdram_quiescent = 1'b0;
  wire device_freeze;
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

  reg internal_load = 1'b0;
  reg cartridge_load = 1'b0;
  reg internal_reset = 1'b0;
  reg cartridge_reset = 1'b0;
  reg internal_frozen_raw = 1'b0;
  reg cartridge_frozen_raw = 1'b0;
  wire internal_settling;
  wire cartridge_settling;
  wire internal_protocol_fault;
  wire cartridge_protocol_fault;

  // The real RTC gives freeze priority over its console/register resets.  It
  // therefore feeds the owner directly and does not use the EEPROM guard.
  reg rtc_device_reset = 1'b0;
  reg rtc_frozen_raw = 1'b0;
  integer rtc_reset_events = 0;
  integer rtc_reset_cases = 0;
  integer prestart_load_cases = 0;
  integer prestart_reset_cases = 0;
  always @(posedge clk or negedge lifecycle_reset_n) begin
    if (!lifecycle_reset_n) begin
      rtc_frozen_raw <= 1'b0;
      rtc_reset_events <= 0;
    end else begin
      rtc_frozen_raw <= device_freeze;
      if (device_freeze && rtc_device_reset)
        rtc_reset_events <= rtc_reset_events + 1;
    end
  end

  wire [2:0] device_frozen = {
      cartridge_frozen_raw, internal_frozen_raw, rtc_frozen_raw
  };
  wire [2:0] device_settling = {
      cartridge_settling, internal_settling, 1'b0
  };
  wire device_protocol_fault = internal_protocol_fault |
                               cartridge_protocol_fault;

  apf_savestate_v2_load_settle_guard #(
      .MAX_ACK_LOW_CYCLES(2)
  ) internal_guard (
      .clk(clk),
      .lifecycle_reset_n(lifecycle_reset_n),
      .freeze_request(device_freeze),
      .load_pulse(internal_load),
      .device_reset(internal_reset),
      .device_frozen_raw(internal_frozen_raw),
      .device_settling(internal_settling),
      .protocol_fault(internal_protocol_fault)
  );

  apf_savestate_v2_load_settle_guard #(
      .MAX_ACK_LOW_CYCLES(2)
  ) cartridge_guard (
      .clk(clk),
      .lifecycle_reset_n(lifecycle_reset_n),
      .freeze_request(device_freeze),
      .load_pulse(cartridge_load),
      .device_reset(cartridge_reset),
      .device_frozen_raw(cartridge_frozen_raw),
      .device_settling(cartridge_settling),
      .protocol_fault(cartridge_protocol_fault)
  );

  apf_savestate_v2_owner #(
      .DEVICE_COUNT(3),
      .MAX_PHASE_CYCLES(20)
  ) owner (
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
      .protocol_error(owner_protocol_error),
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

  task automatic clean_lifecycle_reset;
    begin
      capture_request = 1'b0;
      restore_request = 1'b0;
      cancel = 1'b0;
      runtime_pause_ack = 1'b0;
      sdram_quiescent = 1'b0;
      stage_granted = 1'b0;
      capture_complete = 1'b0;
      capture_error = 1'b0;
      restore_apply_complete = 1'b0;
      restore_apply_error = 1'b0;
      datapath_quiescent = 1'b1;
      internal_load = 1'b0;
      cartridge_load = 1'b0;
      internal_reset = 1'b0;
      cartridge_reset = 1'b0;
      rtc_device_reset = 1'b0;
      internal_frozen_raw = 1'b0;
      cartridge_frozen_raw = 1'b0;
      lifecycle_reset_n = 1'b0;
      tick();
      lifecycle_reset_n = 1'b1;
      tick();
      expect_true(!fatal_reset_hold && !owner_protocol_error &&
                  !internal_protocol_fault && !cartridge_protocol_fault &&
                  !internal_settling && !cartridge_settling,
                  "lifecycle reset did not clear owner/settle guards");
    end
  endtask

  task automatic begin_restore;
    begin
      restore_request = 1'b1;
      tick();
      restore_request = 1'b0;
      expect_true(restore_busy && runtime_pause_request,
                  "restore request did not enter pause acquisition");
      runtime_pause_ack = 1'b1;
      tick();
      expect_true(device_freeze && !stage_acquire,
                  "restore did not freeze devices after pause");
      internal_frozen_raw = 1'b1;
      cartridge_frozen_raw = 1'b1;
      sdram_quiescent = 1'b1;
      tick();
      expect_true((&device_frozen) && !stage_acquire,
                  "RTC raw ack did not observe its freeze-dominant edge");
      tick();
      expect_true((&device_frozen) && stage_acquire,
                  "restore did not acquire stage after all raw acks");
      stage_granted = 1'b1;
      tick();
      expect_true(restore_apply_start && !capture_start,
                  "restore apply barrier was not reached");
      tick();
      expect_true(!restore_apply_start && restore_busy,
                  "restore start was not a one-cycle pulse");
    end
  endtask

  task automatic begin_restore_wait_pause;
    begin
      restore_request = 1'b1;
      tick();
      restore_request = 1'b0;
      expect_true(restore_busy && runtime_pause_request &&
                  !device_freeze && !stage_acquire,
                  "restore did not stop in WAIT_PAUSE");
    end
  endtask

  task automatic advance_restore_wait_quiesce;
    begin
      runtime_pause_ack = 1'b1;
      tick();
      expect_true(device_freeze && !stage_acquire,
                  "restore did not stop in WAIT_QUIESCE");
      internal_frozen_raw = 1'b1;
      cartridge_frozen_raw = 1'b1;
      tick();
      expect_true((&device_frozen) && !stage_acquire,
                  "WAIT_QUIESCE did not acquire every raw device ack");
    end
  endtask

  task automatic advance_restore_wait_stage;
    begin
      sdram_quiescent = 1'b1;
      tick();
      expect_true(stage_acquire && !stage_granted &&
                  !restore_apply_start,
                  "restore did not stop in WAIT_STAGE");
    end
  endtask

  task automatic expect_prestart_fatal_abort(input string message);
    begin
      expect_true(fatal_reset_hold && restore_failed && !restore_busy &&
                  datapath_abort && stage_acquire && device_freeze &&
                  runtime_pause_request && !restore_apply_start,
                  message);
      // The abort is already quiescent, so release only the unused staging
      // route. Runtime pause and device freeze must remain asserted forever.
      tick();
      expect_true(fatal_reset_hold && !stage_acquire && device_freeze &&
                  runtime_pause_request && !restore_apply_start,
                  "pre-start fatal drain released runtime or devices");
      repeat (2) begin
        tick();
        expect_true(fatal_reset_hold && !stage_acquire && device_freeze &&
                    runtime_pause_request && !restore_apply_start,
                    "pre-start fatal hold was not sticky");
      end
    end
  endtask

  task automatic finish_successful_restore;
    begin
      expect_true(!stage_acquire && device_freeze,
                  "restore did not reach settled stage release");
      stage_granted = 1'b0;
      tick();
      expect_true(!device_freeze && runtime_pause_request,
                  "device freeze did not release after stage ownership");
      internal_frozen_raw = 1'b0;
      cartridge_frozen_raw = 1'b0;
      tick();
      expect_true(runtime_pause_request && !rtc_frozen_raw,
                  "RTC thaw edge was not observed before runtime release");
      tick();
      expect_true(!runtime_pause_request && restore_busy,
                  "runtime release did not wait for raw device thaw");
      runtime_pause_ack = 1'b0;
      tick();
      expect_true(restore_done && !restore_busy && !restore_failed &&
                  !fatal_reset_hold,
                  "settled restore did not publish success");
    end
  endtask

  initial begin
    clean_lifecycle_reset();

    // A load outside an acknowledged freeze is rejected and never creates an
    // ownership-retention window.
    internal_load = 1'b1;
    tick();
    internal_load = 1'b0;
    expect_true(internal_protocol_fault && !internal_settling,
                "unfrozen EEPROM load did not fail closed");

    // WAIT_PAUSE has not requested device freeze, so an EEPROM reset is an
    // ordinary console-domain event rather than an ownership violation. A
    // load is reachable and forbidden: it may mutate live device state and
    // must therefore convert the pending restore into a fatal hold.
    clean_lifecycle_reset();
    begin_restore_wait_pause();
    internal_load = 1'b1;
    tick();
    internal_load = 1'b0;
    tick();
    expect_prestart_fatal_abort(
        "early WAIT_PAUSE load did not enter fatal hold");
    prestart_load_cases = prestart_load_cases + 1;

    // Once WAIT_QUIESCE has acquired raw device acknowledgements, even a
    // bounded and otherwise legal load/settle window is a pre-start mutation.
    // It must never unwind through normal runtime release.
    clean_lifecycle_reset();
    begin_restore_wait_pause();
    advance_restore_wait_quiesce();
    internal_load = 1'b1;
    tick();
    internal_load = 1'b0;
    internal_frozen_raw = 1'b0;
    tick();
    expect_prestart_fatal_abort(
        "early WAIT_QUIESCE load did not enter fatal hold");
    prestart_load_cases = prestart_load_cases + 1;

    clean_lifecycle_reset();
    begin_restore_wait_pause();
    advance_restore_wait_quiesce();
    internal_reset = 1'b1;
    internal_frozen_raw = 1'b0;
    tick();
    internal_reset = 1'b0;
    tick();
    expect_prestart_fatal_abort(
        "early WAIT_QUIESCE reset did not enter fatal hold");
    prestart_reset_cases = prestart_reset_cases + 1;

    // The same rule applies while waiting for the staging mux grant. A load
    // is visible as settling on the following owner edge and must be fatal.
    clean_lifecycle_reset();
    begin_restore_wait_pause();
    advance_restore_wait_quiesce();
    advance_restore_wait_stage();
    internal_load = 1'b1;
    tick();
    internal_load = 1'b0;
    internal_frozen_raw = 1'b0;
    tick();
    expect_prestart_fatal_abort(
        "early WAIT_STAGE load did not enter fatal hold");
    prestart_load_cases = prestart_load_cases + 1;

    // Reset and raw-ack loss are synchronous in the device. The owner may
    // enter ABORT_DRAIN from the raw drop one edge before the guard's sticky
    // fault becomes visible; ABORT_DRAIN must upgrade that race to fatal
    // before any runtime/device release occurs.
    clean_lifecycle_reset();
    begin_restore_wait_pause();
    advance_restore_wait_quiesce();
    advance_restore_wait_stage();
    internal_reset = 1'b1;
    internal_frozen_raw = 1'b0;
    tick();
    internal_reset = 1'b0;
    expect_true(internal_protocol_fault && datapath_abort && stage_acquire &&
                runtime_pause_request && !restore_apply_start,
                "WAIT_STAGE reset/raw-drop race did not enter abort drain");
    tick();
    expect_true(fatal_reset_hold && restore_failed && !restore_busy &&
                !stage_acquire && device_freeze && runtime_pause_request &&
                !restore_apply_start,
                "WAIT_STAGE reset fault escaped through recoverable release");
    repeat (2) begin
      tick();
      expect_true(fatal_reset_hold && !stage_acquire && device_freeze &&
                  runtime_pause_request && !restore_apply_start,
                  "WAIT_STAGE reset fatal hold released runtime or devices");
    end
    prestart_reset_cases = prestart_reset_cases + 1;

    clean_lifecycle_reset();
    begin_restore();

    // RTC reset is deliberately freeze-deferred by rtc.vhd.  Its raw ack
    // remains high and the owner must not mistake it for EEPROM settling.
    rtc_device_reset = 1'b1;
    tick();
    rtc_device_reset = 1'b0;
    expect_true(rtc_frozen_raw && rtc_reset_events == 1 &&
                restore_busy && !datapath_abort && !fatal_reset_hold,
                "RTC freeze-dominant reset semantics were not preserved");
    rtc_reset_cases = rtc_reset_cases + 1;

    // A full two-cycle defensive EEPROM gap remains owned.  This covers the
    // real controller's noncanonical hidden-state normalization bound.
    cartridge_load = 1'b1;
    tick();
    cartridge_load = 1'b0;
    cartridge_frozen_raw = 1'b0;
    repeat (2) begin
      tick();
      expect_true(cartridge_settling && !cartridge_protocol_fault &&
                  restore_busy && !datapath_abort,
                  "bounded cartridge settle gap lost atomic ownership");
    end
    cartridge_frozen_raw = 1'b1;
    tick();
    expect_true(!cartridge_settling && !cartridge_protocol_fault,
                "cartridge settle did not close on raw re-ack");

    // Completion on the exact raw-reack edge must enter finish drain, not
    // release from the pre-edge masked view.  Release occurs one owner edge
    // later, after the guard has actually reported settled.
    internal_load = 1'b1;
    tick();
    internal_load = 1'b0;
    internal_frozen_raw = 1'b0;
    tick();
    expect_true(internal_settling && stage_acquire,
                "canonical internal settle gap was not retained");
    internal_frozen_raw = 1'b1;
    restore_apply_complete = 1'b1;
    tick();
    restore_apply_complete = 1'b0;
    expect_true(!internal_settling && stage_acquire && stage_granted,
                "terminal/reack race released stage before settled edge");
    tick();
    expect_true(!stage_acquire && stage_granted,
                "settled terminal did not advance to stage release");
    finish_successful_restore();

    // An ack gap longer than the proved bound ends retention and is fatal
    // after the restore apply barrier.
    clean_lifecycle_reset();
    begin_restore();
    internal_load = 1'b1;
    tick();
    internal_load = 1'b0;
    internal_frozen_raw = 1'b0;
    repeat (3) tick();
    expect_true(internal_protocol_fault && !internal_settling,
                "overlong EEPROM settle gap did not poison the guard");
    tick();
    expect_true(fatal_reset_hold && restore_failed && datapath_abort,
                "overlong post-apply gap did not enter fatal drain");

    // A raw ack drop with no accepted load has no retention privilege at all.
    clean_lifecycle_reset();
    begin_restore();
    internal_frozen_raw = 1'b0;
    tick();
    expect_true(fatal_reset_hold && restore_failed && datapath_abort,
                "unrequested raw ack drop was incorrectly retained");
    tick();
    expect_true(internal_protocol_fault && !internal_settling,
                "unrequested raw ack drop did not poison the guard");

    // Lifecycle reset is the only operation allowed to clear an interrupted
    // post-apply guard/owner pair.
    clean_lifecycle_reset();
    begin_restore();
    cartridge_load = 1'b1;
    tick();
    cartridge_load = 1'b0;
    cartridge_frozen_raw = 1'b0;
    cancel = 1'b1;
    tick();
    cancel = 1'b0;
    expect_true(fatal_reset_hold && restore_failed && datapath_abort &&
                cartridge_settling,
                "cancel during retained settle was not a fatal abort");
    clean_lifecycle_reset();

    // EEPROM reset is unlike RTC reset: it interrupts freeze.  A completion
    // on the same edge may tentatively reach release, but the sticky guard
    // fault/raw-ack drop must win before ownership can be revoked.
    begin_restore();
    internal_load = 1'b1;
    tick();
    internal_load = 1'b0;
    internal_reset = 1'b1;
    restore_apply_complete = 1'b1;
    tick();
    restore_apply_complete = 1'b0;
    internal_frozen_raw = 1'b0;
    expect_true(internal_protocol_fault && !internal_settling,
                "EEPROM reset was incorrectly masked as load settling");
    expect_true(!stage_acquire && stage_granted,
                "terminal/reset race did not begin one-way stage release");
    // Model the mux dropping grant on the exact edge where the registered
    // guard fault becomes visible. The owner must never reassert acquire.
    stage_granted = 1'b0;
    tick();
    expect_true(fatal_reset_hold && restore_failed && !datapath_abort &&
                !stage_acquire && device_freeze && runtime_pause_request,
                "grant-drop/reset race released or reacquired ownership");
    tick();
    expect_true(fatal_reset_hold && !stage_acquire && device_freeze,
                "fatal release did not remain one-way after grant dropped");

    $display("PASS APF savestate v2 EEPROM settle guard normal=2 timeout=1 unrequested_drop=1 cancel=1 terminal_races=2 rtc_reset=%0d eeprom_reset=1 prestart_load=%0d prestart_reset=%0d",
             rtc_reset_cases, prestart_load_cases, prestart_reset_cases);
    $finish;
  end
endmodule

`default_nettype wire
