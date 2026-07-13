// Analogue Pocket startup lifecycle sequencer.
//
// The official startup order is Setup -> 008F data slots all complete ->
// one 0090 RTC notification -> target 0140 Ready to Run -> Idle -> 0011
// Reset Exit -> Running.  0010 Reset Enter returns the core to Idle.
//
// Event inputs are latched in either order.  Loader and initializer inputs are
// readiness levels and must be high together before the one-shot 0140 request.
// An early Reset Exit is harmless: execution remains gated until startup is
// complete, then passes through Idle before entering Running.
module apf_startup_sequencer (
    input  wire       clk,

    // Bitstream/PLL reset. Assertion is asynchronous; all state is held reset
    // until the three-stage synchronizer releases it in this clock domain.
    input  wire       reset_n_async,

    // Level produced by the APF Reset Enter/Exit command handler. Assertion
    // (Reset Enter) is asynchronous so execution stops immediately. Reset Exit
    // is released through a separate three-stage synchronizer.
    input  wire       host_reset_n_async,

    // Synchronous title-load level. A new cartridge lifecycle returns to
    // Setup and re-arms exactly one Ready-to-Run request without misreporting
    // a healthy PLL as Booting.
    input  wire       title_load_start,

    // One-cycle notifications in this clock domain.
    input  wire       data_slots_all_complete,
    input  wire       rtc_notification_observed,

    // Stable aggregate readiness levels for every load and initialization path.
    input  wire       loaders_ready,
    input  wire       initializers_ready,

    // One-cycle target-command request and persistent lifecycle evidence.
    output reg        ready_to_run_pulse,
    output reg        startup_complete,
    output reg        data_slots_seen,
    output reg        rtc_seen,

    // Exact Request Status result values from the APF command specification.
    output reg  [2:0] status_code,
    output wire       status_booting,
    output wire       status_setup,
    output wire       status_idle,
    output wire       status_running,

    // Safe execution enable: asynchronously cleared by either reset source and
    // asserted only after synchronized Reset Exit in the Running state.
    output wire       core_run_enable
);

  localparam [1:0] STATE_SETUP = 2'd0;
  localparam [1:0] STATE_IDLE = 2'd1;
  localparam [1:0] STATE_RUNNING = 2'd2;

  localparam [2:0] STATUS_BOOTING = 3'd1;
  localparam [2:0] STATUS_SETUP = 3'd2;
  localparam [2:0] STATUS_IDLE = 3'd3;
  localparam [2:0] STATUS_RUNNING = 3'd4;

  (* ASYNC_REG = "TRUE" *) reg [2:0] reset_sync;
  (* ASYNC_REG = "TRUE" *) reg [2:0] host_reset_sync;
  reg [1:0] state;

  always @(posedge clk or negedge reset_n_async) begin
    if (!reset_n_async) begin
      reset_sync <= 3'b000;
    end else begin
      reset_sync <= {reset_sync[1:0], 1'b1};
    end
  end

  wire reset_n = reset_sync[2];
  wire host_reset_assert_n = reset_n_async && host_reset_n_async;

  always @(posedge clk or negedge host_reset_assert_n) begin
    if (!host_reset_assert_n) begin
      host_reset_sync <= 3'b000;
    end else begin
      host_reset_sync <= {host_reset_sync[1:0], 1'b1};
    end
  end

  wire host_reset_n = host_reset_sync[2];
  wire all_startup_requirements =
      (data_slots_seen || data_slots_all_complete) &&
      (rtc_seen || rtc_notification_observed) &&
      loaders_ready && initializers_ready;

  always @(posedge clk or negedge reset_n_async) begin
    if (!reset_n_async) begin
      state <= STATE_SETUP;
      ready_to_run_pulse <= 1'b0;
      startup_complete <= 1'b0;
      data_slots_seen <= 1'b0;
      rtc_seen <= 1'b0;
    end else if (!reset_n) begin
      // Synchronous release: ignore notifications until this domain is live.
      state <= STATE_SETUP;
      ready_to_run_pulse <= 1'b0;
      startup_complete <= 1'b0;
      data_slots_seen <= 1'b0;
      rtc_seen <= 1'b0;
    end else if (title_load_start) begin
      state <= STATE_SETUP;
      ready_to_run_pulse <= 1'b0;
      startup_complete <= 1'b0;
      data_slots_seen <= 1'b0;
      rtc_seen <= 1'b0;
    end else begin
      ready_to_run_pulse <= 1'b0;

      case (state)
        STATE_SETUP: begin
          if (data_slots_all_complete) data_slots_seen <= 1'b1;
          if (rtc_notification_observed) rtc_seen <= 1'b1;

          if (!startup_complete && all_startup_requirements) begin
            // This is the only assignment that raises the 0140 request.
            ready_to_run_pulse <= 1'b1;
            startup_complete <= 1'b1;
            state <= STATE_IDLE;
          end
        end

        STATE_IDLE: begin
          // A synchronized Reset Exit is honored only after the explicit Idle
          // transition. An early Exit therefore cannot bypass startup.
          if (host_reset_n) state <= STATE_RUNNING;
        end

        STATE_RUNNING: begin
          if (!host_reset_n) state <= STATE_IDLE;
        end

        default: begin
          // Corrupt state fails closed without re-arming Ready to Run.
          state <= startup_complete ? STATE_IDLE : STATE_SETUP;
        end
      endcase
    end
  end

  assign status_booting = !reset_n;
  assign status_setup = reset_n && (state == STATE_SETUP);
  assign status_running = reset_n && (state == STATE_RUNNING) && host_reset_n;
  assign status_idle = reset_n && startup_complete && !status_running;
  assign core_run_enable = status_running;

  always @(*) begin
    if (status_booting) begin
      status_code = STATUS_BOOTING;
    end else if (status_running) begin
      status_code = STATUS_RUNNING;
    end else if (status_idle) begin
      status_code = STATUS_IDLE;
    end else begin
      status_code = STATUS_SETUP;
    end
  end

endmodule
