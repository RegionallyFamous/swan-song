`timescale 1ns / 1ps

module apf_startup_sequencer_tb;

  reg clk = 1'b0;
  always #5 clk = ~clk;

  reg reset_n_async = 1'b0;
  reg host_reset_n_async = 1'b0;
  reg title_load_start = 1'b0;
  reg data_slots_all_complete = 1'b0;
  reg rtc_notification_observed = 1'b0;
  reg loaders_ready = 1'b0;
  reg initializers_ready = 1'b0;

  wire ready_to_run_pulse;
  wire startup_complete;
  wire data_slots_seen;
  wire rtc_seen;
  wire [2:0] status_code;
  wire status_booting;
  wire status_setup;
  wire status_idle;
  wire status_running;
  wire core_run_enable;

  apf_startup_sequencer dut (
      .clk(clk),
      .reset_n_async(reset_n_async),
      .host_reset_n_async(host_reset_n_async),
      .title_load_start(title_load_start),
      .data_slots_all_complete(data_slots_all_complete),
      .rtc_notification_observed(rtc_notification_observed),
      .loaders_ready(loaders_ready),
      .initializers_ready(initializers_ready),
      .ready_to_run_pulse(ready_to_run_pulse),
      .startup_complete(startup_complete),
      .data_slots_seen(data_slots_seen),
      .rtc_seen(rtc_seen),
      .status_code(status_code),
      .status_booting(status_booting),
      .status_setup(status_setup),
      .status_idle(status_idle),
      .status_running(status_running),
      .core_run_enable(core_run_enable)
  );

  integer ready_pulse_count = 0;
  reg previous_ready_pulse = 1'b0;

  always @(posedge clk) begin
    if (ready_to_run_pulse) ready_pulse_count <= ready_pulse_count + 1;
    if (ready_to_run_pulse && previous_ready_pulse)
      $fatal(1, "Ready-to-Run request lasted longer than one clock");
    previous_ready_pulse <= ready_to_run_pulse;
  end

  task automatic tick;
    begin
      @(posedge clk);
      #1;
    end
  endtask

  task automatic expect_status(input [2:0] expected, input string label_text);
    begin
      if (status_code !== expected)
        $fatal(1, "%0s: status=%0d expected=%0d", label_text, status_code, expected);
      if ({status_running, status_idle, status_setup, status_booting} == 4'b0000 ||
          ({status_running, status_idle, status_setup, status_booting} &
           ({status_running, status_idle, status_setup, status_booting} - 1'b1)) != 0)
        $fatal(1, "%0s: lifecycle outputs are not one-hot", label_text);
      if (core_run_enable !== status_running)
        $fatal(1, "%0s: core_run_enable disagrees with Running status", label_text);
    end
  endtask

  task automatic assert_global_reset;
    begin
      reset_n_async = 1'b0;
      #1;
      if (ready_to_run_pulse || startup_complete || data_slots_seen || rtc_seen ||
          core_run_enable)
        $fatal(1, "global reset did not assert lifecycle state asynchronously");
      expect_status(3'd1, "asynchronous global reset");
      ready_pulse_count = 0;
      previous_ready_pulse = 1'b0;
      data_slots_all_complete = 1'b0;
      rtc_notification_observed = 1'b0;
      loaders_ready = 1'b0;
      initializers_ready = 1'b0;
      title_load_start = 1'b0;
    end
  endtask

  task automatic release_global_reset;
    begin
      reset_n_async = 1'b1;
      tick();
      expect_status(3'd1, "global release stage 1");
      tick();
      expect_status(3'd1, "global release stage 2");
      tick();
      expect_status(3'd2, "synchronized Setup release");
    end
  endtask

  task automatic pulse_data_complete;
    begin
      data_slots_all_complete = 1'b1;
      tick();
      data_slots_all_complete = 1'b0;
    end
  endtask

  task automatic pulse_rtc;
    begin
      rtc_notification_observed = 1'b1;
      tick();
      rtc_notification_observed = 1'b0;
    end
  endtask

  task automatic wait_host_release;
    begin
      tick();
      tick();
      tick();
      tick();
    end
  endtask

  initial begin
    // Ordered official path: 008F, 0090, aggregate loaders, aggregate init,
    // 0140/Idle, then Reset Exit/Running.
    assert_global_reset();
    release_global_reset();
    pulse_data_complete();
    if (!data_slots_seen || startup_complete) $fatal(1, "008F was not latched in Setup");
    pulse_rtc();
    if (!rtc_seen || startup_complete) $fatal(1, "0090 was not latched in Setup");
    loaders_ready = 1'b1;
    tick();
    if (startup_complete) $fatal(1, "initializer readiness was bypassed");
    initializers_ready = 1'b1;
    tick();
    if (!ready_to_run_pulse || !startup_complete)
      $fatal(1, "complete startup did not issue Ready to Run");
    expect_status(3'd3, "Ready to Run enters Idle");
    tick();
    if (ready_to_run_pulse || ready_pulse_count != 1)
      $fatal(1, "Ready to Run was not exactly one pulse");

    host_reset_n_async = 1'b1;
    tick();
    expect_status(3'd3, "Reset Exit release stage 1");
    tick();
    expect_status(3'd3, "Reset Exit release stage 2");
    tick();
    expect_status(3'd3, "Reset Exit synchronized before state advance");
    tick();
    expect_status(3'd4, "Reset Exit enters Running");

    // Reset Enter must stop execution asynchronously and duplicate Enter must
    // remain harmless. Reset Exit releases only after synchronization.
    host_reset_n_async = 1'b0;
    #1;
    expect_status(3'd3, "asynchronous Reset Enter");
    if (core_run_enable) $fatal(1, "Reset Enter did not stop execution immediately");
    host_reset_n_async = 1'b0;
    repeat (3) tick();
    expect_status(3'd3, "duplicate Reset Enter");
    host_reset_n_async = 1'b1;
    wait_host_release();
    expect_status(3'd4, "second synchronized Reset Exit");

    // All duplicate startup events after completion are ignored forever.
    pulse_rtc();
    pulse_rtc();
    pulse_data_complete();
    pulse_data_complete();
    repeat (3) tick();
    if (ready_pulse_count != 1) $fatal(1, "duplicate events reissued Ready to Run");

    // Reordered path with an early Reset Exit and readiness that was once high
    // but withdrew before the other prerequisites. It must fail closed until
    // every requirement is simultaneously true.
    assert_global_reset();
    host_reset_n_async = 1'b1;
    release_global_reset();
    repeat (2) tick();
    expect_status(3'd2, "early Reset Exit remains Setup");
    if (core_run_enable) $fatal(1, "early Reset Exit bypassed startup");

    pulse_rtc();
    pulse_rtc();
    loaders_ready = 1'b1;
    initializers_ready = 1'b1;
    tick();
    loaders_ready = 1'b0;
    pulse_data_complete();
    pulse_data_complete();
    if (startup_complete || ready_pulse_count != 0)
      $fatal(1, "withdrawn loader readiness was incorrectly latched");
    loaders_ready = 1'b1;
    tick();
    if (!ready_to_run_pulse || ready_pulse_count != 0)
      $fatal(1, "reordered prerequisites did not issue one Ready to Run pulse");
    expect_status(3'd3, "early Reset Exit still observes Idle transition");
    tick();
    if (ready_to_run_pulse || ready_pulse_count != 1)
      $fatal(1, "reordered Ready to Run pulse count is wrong");
    expect_status(3'd4, "latched early Reset Exit runs only after Idle");

    // Events arriving while reset release is still synchronizing are ignored.
    assert_global_reset();
    reset_n_async = 1'b1;
    data_slots_all_complete = 1'b1;
    rtc_notification_observed = 1'b1;
    loaders_ready = 1'b1;
    initializers_ready = 1'b1;
    tick();
    tick();
    data_slots_all_complete = 1'b0;
    rtc_notification_observed = 1'b0;
    tick();
    expect_status(3'd2, "pre-Setup events ignored");
    if (data_slots_seen || rtc_seen || startup_complete)
      $fatal(1, "events were captured before synchronized reset release");

    // Same-cycle events at a legal Setup boundary are accepted atomically.
    data_slots_all_complete = 1'b1;
    rtc_notification_observed = 1'b1;
    tick();
    data_slots_all_complete = 1'b0;
    rtc_notification_observed = 1'b0;
    if (!ready_to_run_pulse || !data_slots_seen || !rtc_seen || !startup_complete)
      $fatal(1, "same-cycle legal prerequisites were not accepted atomically");
    expect_status(3'd3, "same-cycle completion enters Idle");
    tick();
    if (ready_pulse_count != 1) $fatal(1, "same-cycle Ready to Run count is wrong");

    // A new title returns a running core to Setup without misreporting the
    // still-locked PLL as Booting, and re-arms exactly one 0140 request.
    title_load_start = 1'b1;
    tick();
    expect_status(3'd2, "new title returns to Setup");
    if (startup_complete || data_slots_seen || rtc_seen)
      $fatal(1, "new title did not clear prior lifecycle evidence");
    title_load_start = 1'b0;
    pulse_data_complete();
    pulse_rtc();
    tick();
    if (!startup_complete || ready_pulse_count != 2)
      $fatal(1, "new title did not re-arm exactly one startup request");

    // A new bitstream reset also re-arms the one-shot.
    assert_global_reset();
    release_global_reset();
    loaders_ready = 1'b1;
    initializers_ready = 1'b1;
    data_slots_all_complete = 1'b1;
    rtc_notification_observed = 1'b1;
    tick();
    data_slots_all_complete = 1'b0;
    rtc_notification_observed = 1'b0;
    tick();
    if (ready_pulse_count != 1)
      $fatal(1, "global reset did not re-arm exactly one startup request");

    $display("PASS APF startup sequencing, one-shot Ready to Run, and reset lifecycle");
    $finish;
  end

endmodule
