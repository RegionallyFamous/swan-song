//
// User core top-level
//
// Instantiated by the real top-level: apf_top
//

`default_nettype none

module core_top (

    //
    // physical connections
    //

    ///////////////////////////////////////////////////
    // clock inputs 74.25mhz. not phase aligned, so treat these domains as asynchronous

    input wire clk_74a,  // mainclk1
    input wire clk_74b,  // mainclk1 

    ///////////////////////////////////////////////////
    // cartridge interface
    // switches between 3.3v and 5v mechanically
    // output enable for multibit translators controlled by pic32

    // GBA AD[15:8]
    inout  wire [7:0] cart_tran_bank2,
    output wire       cart_tran_bank2_dir,

    // GBA AD[7:0]
    inout  wire [7:0] cart_tran_bank3,
    output wire       cart_tran_bank3_dir,

    // GBA A[23:16]
    inout  wire [7:0] cart_tran_bank1,
    output wire       cart_tran_bank1_dir,

    // GBA [7] PHI#
    // GBA [6] WR#
    // GBA [5] RD#
    // GBA [4] CS1#/CS#
    //     [3:0] unwired
    inout  wire [7:4] cart_tran_bank0,
    output wire       cart_tran_bank0_dir,

    // GBA CS2#/RES#
    inout  wire cart_tran_pin30,
    output wire cart_tran_pin30_dir,
    // when GBC cart is inserted, this signal when low or weak will pull GBC /RES low with a special circuit
    // the goal is that when unconfigured, the FPGA weak pullups won't interfere.
    // thus, if GBC cart is inserted, FPGA must drive this high in order to let the level translators
    // and general IO drive this pin.
    output wire cart_pin30_pwroff_reset,

    // GBA IRQ/DRQ
    inout  wire cart_tran_pin31,
    output wire cart_tran_pin31_dir,

    // infrared
    input  wire port_ir_rx,
    output wire port_ir_tx,
    output wire port_ir_rx_disable,

    // GBA link port
    inout  wire port_tran_si,
    output wire port_tran_si_dir,
    inout  wire port_tran_so,
    output wire port_tran_so_dir,
    inout  wire port_tran_sck,
    output wire port_tran_sck_dir,
    inout  wire port_tran_sd,
    output wire port_tran_sd_dir,

    ///////////////////////////////////////////////////
    // cellular psram 0 and 1, two chips (64mbit x2 dual die per chip)

    output wire [21:16] cram0_a,
    inout  wire [ 15:0] cram0_dq,
    input  wire         cram0_wait,
    output wire         cram0_clk,
    output wire         cram0_adv_n,
    output wire         cram0_cre,
    output wire         cram0_ce0_n,
    output wire         cram0_ce1_n,
    output wire         cram0_oe_n,
    output wire         cram0_we_n,
    output wire         cram0_ub_n,
    output wire         cram0_lb_n,

    output wire [21:16] cram1_a,
    inout  wire [ 15:0] cram1_dq,
    input  wire         cram1_wait,
    output wire         cram1_clk,
    output wire         cram1_adv_n,
    output wire         cram1_cre,
    output wire         cram1_ce0_n,
    output wire         cram1_ce1_n,
    output wire         cram1_oe_n,
    output wire         cram1_we_n,
    output wire         cram1_ub_n,
    output wire         cram1_lb_n,

    ///////////////////////////////////////////////////
    // sdram, 512mbit 16bit

    output wire [12:0] dram_a,
    output wire [ 1:0] dram_ba,
    inout  wire [15:0] dram_dq,
    output wire [ 1:0] dram_dqm,
    output wire        dram_clk,
    output wire        dram_cke,
    output wire        dram_ras_n,
    output wire        dram_cas_n,
    output wire        dram_we_n,

    ///////////////////////////////////////////////////
    // sram, 1mbit 16bit

    output wire [16:0] sram_a,
    inout  wire [15:0] sram_dq,
    output wire        sram_oe_n,
    output wire        sram_we_n,
    output wire        sram_ub_n,
    output wire        sram_lb_n,

    ///////////////////////////////////////////////////
    // vblank driven by dock for sync in a certain mode

    input wire vblank,

    ///////////////////////////////////////////////////
    // i/o to 6515D breakout usb uart

    output wire dbg_tx,
    input  wire dbg_rx,

    ///////////////////////////////////////////////////
    // i/o pads near jtag connector user can solder to

    output wire user1,
    input  wire user2,

    ///////////////////////////////////////////////////
    // RFU internal i2c bus 

    inout  wire aux_sda,
    output wire aux_scl,

    ///////////////////////////////////////////////////
    // RFU, do not use
    output wire vpll_feed,


    //
    // logical connections
    //

    ///////////////////////////////////////////////////
    // video, audio output to scaler
    output wire [23:0] video_rgb,
    output wire        video_rgb_clock,
    output wire        video_rgb_clock_90,
    output wire        video_de,
    output wire        video_skip,
    output wire        video_vs,
    output wire        video_hs,

    output wire audio_mclk,
    input  wire audio_adc,
    output wire audio_dac,
    output wire audio_lrck,

    ///////////////////////////////////////////////////
    // bridge bus connection
    // synchronous to clk_74a
    output wire        bridge_endian_little,
    input  wire [31:0] bridge_addr,
    input  wire        bridge_rd,
    output reg  [31:0] bridge_rd_data,
    input  wire        bridge_wr,
    input  wire [31:0] bridge_wr_data,

    ///////////////////////////////////////////////////
    // controller data
    // 
    // key bitmap:
    //   [0]    dpad_up
    //   [1]    dpad_down
    //   [2]    dpad_left
    //   [3]    dpad_right
    //   [4]    face_a
    //   [5]    face_b
    //   [6]    face_x
    //   [7]    face_y
    //   [8]    trig_l1
    //   [9]    trig_r1
    //   [10]   trig_l2
    //   [11]   trig_r2
    //   [12]   trig_l3
    //   [13]   trig_r3
    //   [14]   face_select
    //   [15]   face_start
    // joy values - unsigned
    //   [ 7: 0] lstick_x
    //   [15: 8] lstick_y
    //   [23:16] rstick_x
    //   [31:24] rstick_y
    // trigger values - unsigned
    //   [ 7: 0] ltrig
    //   [15: 8] rtrig
    //
    input wire [15:0] cont1_key,
    input wire [15:0] cont2_key,
    input wire [15:0] cont3_key,
    input wire [15:0] cont4_key,
    input wire [31:0] cont1_joy,
    input wire [31:0] cont2_joy,
    input wire [31:0] cont3_joy,
    input wire [31:0] cont4_joy,
    input wire [15:0] cont1_trig,
    input wire [15:0] cont2_trig,
    input wire [15:0] cont3_trig,
    input wire [15:0] cont4_trig

);

  // not using the IR port, so turn off both the LED, and
  // disable the receive circuit to save power
  assign port_ir_tx              = 0;
  assign port_ir_rx_disable      = 1;

  // bridge endianness
  assign bridge_endian_little    = 0;

  // cart is unused, so set all level translators accordingly
  // directions are 0:IN, 1:OUT
  assign cart_tran_bank3         = 8'hzz;
  assign cart_tran_bank3_dir     = 1'b0;
  assign cart_tran_bank2         = 8'hzz;
  assign cart_tran_bank2_dir     = 1'b0;
  assign cart_tran_bank1         = 8'hzz;
  assign cart_tran_bank1_dir     = 1'b0;
  assign cart_tran_bank0         = 4'hf;
  assign cart_tran_bank0_dir     = 1'b1;
  assign cart_tran_pin30         = 1'b0;  // reset or cs2, we let the hw control it by itself
  assign cart_tran_pin30_dir     = 1'bz;
  assign cart_pin30_pwroff_reset = 1'b0;  // hardware can control this
  assign cart_tran_pin31         = 1'bz;  // input
  assign cart_tran_pin31_dir     = 1'b0;  // input

  // link port is input only
  assign port_tran_so            = 1'bz;
  assign port_tran_so_dir        = 1'b0;  // SO is output only
  assign port_tran_si            = 1'bz;
  assign port_tran_si_dir        = 1'b0;  // SI is input only
  assign port_tran_sck           = 1'bz;
  assign port_tran_sck_dir       = 1'b0;  // clock direction can change
  assign port_tran_sd            = 1'bz;
  assign port_tran_sd_dir        = 1'b0;  // SD is input and not used

  // tie off the rest of the pins we are not using
  assign cram0_a                 = 'h0;
  assign cram0_dq                = {16{1'bZ}};
  assign cram0_clk               = 0;
  assign cram0_adv_n             = 1;
  assign cram0_cre               = 0;
  assign cram0_ce0_n             = 1;
  assign cram0_ce1_n             = 1;
  assign cram0_oe_n              = 1;
  assign cram0_we_n              = 1;
  assign cram0_ub_n              = 1;
  assign cram0_lb_n              = 1;

  assign cram1_a                 = 'h0;
  assign cram1_dq                = {16{1'bZ}};
  assign cram1_clk               = 0;
  assign cram1_adv_n             = 1;
  assign cram1_cre               = 0;
  assign cram1_ce0_n             = 1;
  assign cram1_ce1_n             = 1;
  assign cram1_oe_n              = 1;
  assign cram1_we_n              = 1;
  assign cram1_ub_n              = 1;
  assign cram1_lb_n              = 1;

  // assign dram_a                  = 'h0;
  // assign dram_ba                 = 'h0;
  // assign dram_dq                 = {16{1'bZ}};
  // assign dram_dqm                = 'h0;
  // assign dram_clk                = 'h0;
  // assign dram_cke                = 'h0;
  // assign dram_ras_n              = 'h1;
  // assign dram_cas_n              = 'h1;
  // assign dram_we_n               = 'h1;

  assign sram_a                  = 'h0;
  assign sram_dq                 = {16{1'bZ}};
  assign sram_oe_n               = 1;
  assign sram_we_n               = 1;
  assign sram_ub_n               = 1;
  assign sram_lb_n               = 1;

  assign dbg_tx                  = 1'bZ;
  assign user1                   = 1'bZ;
  assign aux_scl                 = 1'bZ;
  assign vpll_feed               = 1'bZ;


  // for bridge write data, we just broadcast it to all bus devices
  // for bridge read data, we have to mux it
  // add your own devices here
  always @(*) begin
    casex (bridge_addr)
      default: begin
        bridge_rd_data <= 0;
      end
      // Bridge
      32'hF8xxxxxx: begin
        bridge_rd_data <= cmd_bridge_rd_data;
      end
      32'h2xxxxxxx: begin
        bridge_rd_data <= sd_read_data;
      end
      32'h4xxxxxxx: begin
        bridge_rd_data <= save_state_bridge_read_data;
      end
    endcase
  end

  always @(posedge clk_74a) begin
    if (reset_delay > 0) begin
      reset_delay <= reset_delay - 1;
    end

    if (bridge_wr) begin
      casex (bridge_addr)
        32'h0: begin
          cart_download <= bridge_wr_data[0];
        end
        32'h4: begin
          is_color_cart <= bridge_wr_data[0];
        end
        32'h8: begin
          bw_bios_download <= bridge_wr_data[0];
        end
        32'hC: begin
          color_bios_download <= bridge_wr_data[0];
        end
        // Sent by CHIP32
        // 32'h10: begin
        //   save_download <= bridge_wr_data[0];
        // end

        32'h050: begin
          reset_delay <= 32'h100000;
        end

        32'h100: begin
          configured_system <= bridge_wr_data[1:0];
        end
        32'h110: begin
          use_cpu_turbo <= bridge_wr_data[0];
        end
        // 32'h114: begin
        //   use_rewind_capture <= bridge_wr_data[0];
        // end

        32'h200: begin
          use_triple_buffer <= bridge_wr_data[0];
        end
        32'h204: begin
          configured_flickerblend <= bridge_wr_data[1:0];
        end
        32'h208: begin
          configured_orientation <= bridge_wr_data[1:0];
        end
        32'h20C: begin
          use_flip_horizontal <= bridge_wr_data[0];
        end

        32'h300: begin
          use_fastforward_sound <= bridge_wr_data[0];
        end
      endcase
    end
  end


  //
  // host/target command handler
  //
  wire reset_n;  // driven by host commands, can be used as core-wide reset
  wire [31:0] cmd_bridge_rd_data;

  // bridge host commands
  // synchronous to clk_74a
  wire pll_core_ready_74a;
  wire pll_core_ready_mem;
  apf_reset_sync pll_ready_bridge (
      .clk(clk_74a),
      .reset_n_async(pll_core_locked),
      .reset_n_sync(pll_core_ready_74a)
  );
  apf_reset_sync pll_ready_memory (
      .clk(clk_mem_110_592),
      .reset_n_async(pll_core_locked),
      .reset_n_sync(pll_core_ready_mem)
  );
  wire status_boot_done = pll_core_ready_74a;
  wire status_setup_done;
  wire status_running;
  wire ready_to_run_complete;

  wire dataslot_requestread;
  wire [15:0] dataslot_requestread_id;
  wire dataslot_requestread_ack;
  wire [1:0] dataslot_requestread_result;

  wire dataslot_requestwrite;
  wire [15:0] dataslot_requestwrite_id;
  wire [47:0] dataslot_requestwrite_size;
  wire dataslot_requestwrite_ack;
  wire [1:0] dataslot_requestwrite_result;

  wire dataslot_allcomplete;
  wire dataslot_update;
  wire [15:0] dataslot_update_id;
  wire [31:0] dataslot_update_size;

  // Official APF request results are three-valued: ready (0), permanently
  // disallowed (1), and retry later (2). Evaluate every 0080/0082 against the
  // concrete WonderSwan slot policy instead of acknowledging unconditionally.
  wire dataslot_guard_ack;
  wire [1:0] dataslot_guard_result;
  wire dataslot_guard_busy;
  wire [15:0] dataslot_policy_id;
  reg dataslot_policy_known;
  reg dataslot_policy_allow_read;
  reg dataslot_policy_allow_write;
  reg dataslot_policy_bounds_ready;
  reg [1:0] dataslot_policy_size_mode;
  reg [47:0] dataslot_policy_exact_size;
  reg [47:0] dataslot_policy_min_size;
  reg [47:0] dataslot_policy_max_size;
  reg dataslot_policy_capture_length;
  wire captured_save_length_valid;
  wire [15:0] captured_save_id;
  wire [47:0] captured_save_length;
  wire captured_save_length_updated;

  wire dataslot_request_valid = dataslot_requestread || dataslot_requestwrite;
  wire [15:0] dataslot_request_id = dataslot_requestwrite ?
                                    dataslot_requestwrite_id :
                                    dataslot_requestread_id;
  wire [47:0] dataslot_request_size = dataslot_requestwrite ?
                                      dataslot_requestwrite_size : 48'd0;

  assign dataslot_requestread_ack = dataslot_guard_ack && dataslot_requestread;
  assign dataslot_requestread_result = dataslot_guard_result;
  assign dataslot_requestwrite_ack = dataslot_guard_ack && dataslot_requestwrite;
  assign dataslot_requestwrite_result = dataslot_guard_result;

  wire [31:0] rtc_epoch_seconds;
  wire [31:0] rtc_date_bcd;
  wire [31:0] rtc_time_bcd;
  wire rtc_valid;
  wire [31:0] rtc_epoch_seconds_sys;
  wire rtc_valid_sys;
  wire rtc_cdc_busy;
  wire rtc_cdc_rejected;

  wire [19:0] save_size_bytes;
  wire has_rtc;
  wire save_metadata_commit;
  wire save_initialization_resolved_mem;
  wire execution_ready_sys;

  wire [19:0] save_size_bytes_74a;
  wire has_rtc_74a;
  wire save_metadata_valid_74a;
  wire save_metadata_cdc_busy;
  wire save_metadata_cdc_busy_74a;
  wire save_metadata_cdc_rejected;
  reg save_metadata_commit_pending_mem = 1'b0;
  reg [19:0] save_size_bytes_snapshot_mem = 20'd0;
  reg has_rtc_snapshot_mem = 1'b0;
  reg save_metadata_ready_74a = 1'b0;
  reg save_metadata_publish_pending = 1'b0;
  reg save_metadata_table_published = 1'b0;

  wire dataslot_allcomplete_mem;
  wire save_initialization_resolved_74a;
  wire execution_ready_74a;
  reg [4:0] shutdown_quiesce_count = 5'd0;
  wire save_backend_quiesced = &shutdown_quiesce_count;

  reg rtc_transfer_seen_busy = 1'b0;
  reg rtc_transfer_delivered = 1'b0;
  reg rtc_transfer_failed = 1'b0;

  wire startup_ready_to_run_pulse;
  wire startup_complete;
  wire startup_data_slots_seen;
  wire startup_rtc_seen;
  wire [2:0] startup_status_code;
  wire startup_status_booting;
  wire startup_status_setup;
  wire startup_status_idle;
  wire startup_status_running;
  wire core_run_enable;

  assign status_setup_done = startup_complete;
  assign status_running = startup_status_running && execution_ready_74a;

  // The command handler remains regression-tested, but the end-to-end state
  // controller is not yet safe to advertise to Pocket for Memories/sleep.
  wire savestate_supported = 0;
  wire [31:0] savestate_addr = 32'h40000000;
  // TODO: Change size of save state based on memory size
  wire [31:0] savestate_size = 32'h90_200;
  // Add buffer of 0x1000 for extra data that we'll just discard on loading
  wire [31:0] savestate_maxloadsize = savestate_size + 32'h1_000;

  wire savestate_start;
  wire savestate_start_ack;
  wire savestate_start_busy;
  wire savestate_start_ok;
  wire savestate_start_err;

  wire savestate_load;
  wire savestate_load_ack;
  wire savestate_load_busy;
  wire savestate_load_ok;
  wire savestate_load_err;

  wire osnotify_inmenu;
  wire osnotify_docked;
  wire [7:0] osnotify_displaymode_id;
  wire osnotify_displaymode_grayscale;
  wire displaymode_grayscale_video;
  reg displaymode_grayscale_applied = 1'b0;
  wire displaymode_grayscale_ack;

  // bridge target commands
  // synchronous to clk_74a


  // bridge data slot access

  reg [9:0] datatable_addr;
  reg datatable_wren;
  reg [31:0] datatable_data;
  wire [31:0] datatable_q;

  core_bridge_cmd icb (

      .clk    (clk_74a),
      .reset_n(reset_n),

      .bridge_endian_little(bridge_endian_little),
      .bridge_addr         (bridge_addr),
      .bridge_rd           (bridge_rd),
      .bridge_rd_data      (cmd_bridge_rd_data),
      .bridge_wr           (bridge_wr),
      .bridge_wr_data      (bridge_wr_data),

      .status_boot_done (status_boot_done),
      .status_setup_done(status_setup_done),
      .status_running   (status_running),
      .ready_to_run_complete(ready_to_run_complete),

      .dataslot_requestread    (dataslot_requestread),
      .dataslot_requestread_id (dataslot_requestread_id),
      .dataslot_requestread_ack(dataslot_requestread_ack),
      .dataslot_requestread_result(dataslot_requestread_result),

      .dataslot_requestwrite    (dataslot_requestwrite),
      .dataslot_requestwrite_id (dataslot_requestwrite_id),
      .dataslot_requestwrite_size(dataslot_requestwrite_size),
      .dataslot_requestwrite_ack(dataslot_requestwrite_ack),
      .dataslot_requestwrite_result(dataslot_requestwrite_result),

      .dataslot_update(dataslot_update),
      .dataslot_update_id(dataslot_update_id),
      .dataslot_update_size(dataslot_update_size),

      .dataslot_allcomplete(dataslot_allcomplete),

      .rtc_epoch_seconds(rtc_epoch_seconds),
      .rtc_date_bcd(rtc_date_bcd),
      .rtc_time_bcd(rtc_time_bcd),
      .rtc_valid(rtc_valid),

      .savestate_supported  (savestate_supported),
      .savestate_addr       (savestate_addr),
      .savestate_size       (savestate_size),
      .savestate_maxloadsize(savestate_maxloadsize),

      .savestate_start     (savestate_start),
      .savestate_start_ack (savestate_start_ack),
      .savestate_start_busy(savestate_start_busy),
      .savestate_start_ok  (savestate_start_ok),
      .savestate_start_err (savestate_start_err),

      .savestate_load     (savestate_load),
      .savestate_load_ack (savestate_load_ack),
      .savestate_load_busy(savestate_load_busy),
      .savestate_load_ok  (savestate_load_ok),
      .savestate_load_err (savestate_load_err),

      .osnotify_inmenu(osnotify_inmenu),
      .osnotify_docked(osnotify_docked),
      .osnotify_displaymode_id(osnotify_displaymode_id),
      .osnotify_displaymode_grayscale(osnotify_displaymode_grayscale),
      .displaymode_grayscale_ack(displaymode_grayscale_ack),

      .datatable_addr(datatable_addr),
      .datatable_wren(datatable_wren),
      .datatable_data(datatable_data),
      .datatable_q   (datatable_q)
  );

  // Command 0090 arrives while APF still holds the console in Reset Enter.
  // Keep this bridge alive from PLL lock and move its event/payload into the
  // console domain with an acknowledged bundled-data transfer.
  apf_rtc_cdc rtc_command_cdc (
      .reset_n(pll_core_ready_74a),
      .clk_74a(clk_74a),
      .rtc_epoch_src(rtc_epoch_seconds),
      .rtc_valid_src(rtc_valid),
      .rtc_busy_src(rtc_cdc_busy),
      .rtc_rejected_src(rtc_cdc_rejected),
      .clk_sys(clk_sys_36_864),
      .rtc_epoch_dst(rtc_epoch_seconds_sys),
      .rtc_valid_dst(rtc_valid_sys)
  );

  // Hold footer-derived metadata locally until the previous bundled transfer
  // is acknowledged. This also turns a rapid title reload into a queued retry
  // instead of silently losing the new snapshot.
  wire save_metadata_commit_source = save_metadata_commit_pending_mem &&
                                     !save_metadata_cdc_busy;
  always @(posedge clk_mem_110_592 or negedge pll_core_ready_mem) begin
    if (!pll_core_ready_mem) begin
      save_metadata_commit_pending_mem <= 1'b0;
      save_size_bytes_snapshot_mem <= 20'd0;
      has_rtc_snapshot_mem <= 1'b0;
    end else if (save_metadata_commit) begin
      save_size_bytes_snapshot_mem <= save_size_bytes;
      has_rtc_snapshot_mem <= has_rtc;
      save_metadata_commit_pending_mem <= 1'b1;
    end else if (save_metadata_commit_source) begin
      save_metadata_commit_pending_mem <= 1'b0;
    end
  end

  apf_save_metadata_cdc save_metadata_command_cdc (
      .reset_n(pll_core_locked),
      .clk_source(clk_mem_110_592),
      .save_size_bytes_source(save_size_bytes_snapshot_mem),
      .has_rtc_source(has_rtc_snapshot_mem),
      .commit_source(save_metadata_commit_source),
      .busy_source(save_metadata_cdc_busy),
      .rejected_source(save_metadata_cdc_rejected),
      .clk_74a(clk_74a),
      .save_size_bytes_74a(save_size_bytes_74a),
      .has_rtc_74a(has_rtc_74a),
      .metadata_valid_74a(save_metadata_valid_74a)
  );

  synch_3 metadata_busy_to_bridge (
      save_metadata_cdc_busy,
      save_metadata_cdc_busy_74a,
      clk_74a
  );

  // 008F is both the end of APF slot traffic and the safe boundary for
  // absent-save initialization. Synchronize its persistent level to clk_mem.
  synch_3 dataslot_complete_to_memory (
      dataslot_allcomplete,
      dataslot_allcomplete_mem,
      clk_mem_110_592
  );

  synch_3 save_initialization_to_bridge (
      save_initialization_resolved_mem,
      save_initialization_resolved_74a,
      clk_74a
  );

  synch_3 execution_ready_to_bridge (
      execution_ready_sys,
      execution_ready_74a,
      clk_74a
  );

  // 0010 is acknowledged in the command clock before the synchronized console
  // reset and a final persistence write can fully drain. Return result 2 to an
  // immediate 0080 until the real execution-ready level is low and more than
  // twenty memory-clock opportunities have elapsed.
  always @(posedge clk_74a or negedge pll_core_ready_74a) begin
    if (!pll_core_ready_74a) begin
      shutdown_quiesce_count <= 5'd0;
    end else if (reset_n || execution_ready_74a) begin
      shutdown_quiesce_count <= 5'd0;
    end else if (!save_backend_quiesced) begin
      shutdown_quiesce_count <= shutdown_quiesce_count + 5'd1;
    end
  end

  // Do not treat receipt of 0090 as completion: wait until its acknowledged
  // bundled-data CDC has delivered the epoch into the console clock domain.
  always @(posedge clk_74a or negedge pll_core_ready_74a) begin
    if (!pll_core_ready_74a) begin
      rtc_transfer_seen_busy <= 1'b0;
      rtc_transfer_delivered <= 1'b0;
      rtc_transfer_failed <= 1'b0;
    end else if (cart_download) begin
      rtc_transfer_seen_busy <= 1'b0;
      rtc_transfer_delivered <= 1'b0;
      rtc_transfer_failed <= 1'b0;
    end else begin
      if (rtc_valid) begin
        rtc_transfer_seen_busy <= 1'b0;
        rtc_transfer_delivered <= 1'b0;
        rtc_transfer_failed <= 1'b0;
      end
      if (rtc_cdc_busy)
        rtc_transfer_seen_busy <= 1'b1;
      if (rtc_transfer_seen_busy && !rtc_cdc_busy)
        rtc_transfer_delivered <= 1'b1;
      if (rtc_cdc_rejected) begin
        rtc_transfer_failed <= 1'b1;
        rtc_transfer_delivered <= 1'b0;
      end
    end
  end

  // Publish the runtime save length only after Pocket has finished its setup
  // table writes. The metadata remains live across Reset Enter so shutdown can
  // request an 0080 nonvolatile flush.
  always @(posedge clk_74a or negedge pll_core_ready_74a) begin
    if (!pll_core_ready_74a) begin
      save_metadata_ready_74a <= 1'b0;
      save_metadata_publish_pending <= 1'b0;
      save_metadata_table_published <= 1'b0;
      datatable_addr <= 10'd0;
      datatable_data <= 32'd0;
      datatable_wren <= 1'b0;
    end else begin
      datatable_wren <= 1'b0;

      if (cart_download) begin
        save_metadata_ready_74a <= 1'b0;
        save_metadata_publish_pending <= 1'b0;
        save_metadata_table_published <= 1'b0;
      end else begin
        if (save_metadata_valid_74a) begin
          save_metadata_ready_74a <= 1'b1;
          save_metadata_publish_pending <= 1'b1;
          save_metadata_table_published <= 1'b0;
        end

        if (save_metadata_publish_pending && dataslot_allcomplete) begin
          // Slot index 3 is ID 11 in data.json; word 1 is its runtime length.
          datatable_addr <= 10'd7;
          datatable_data <= {12'd0, save_size_bytes_74a} +
                            (has_rtc_74a ? 32'd12 : 32'd0);
          datatable_wren <= 1'b1;
          save_metadata_publish_pending <= 1'b0;
          save_metadata_table_published <= 1'b1;
        end
      end
    end
  end

  apf_startup_sequencer pocket_startup (
      .clk(clk_74a),
      .reset_n_async(pll_core_locked),
      .host_reset_n_async(reset_n),
      .title_load_start(cart_download),
      .data_slots_all_complete(dataslot_allcomplete),
      .rtc_notification_observed(rtc_transfer_delivered),
      .loaders_ready(save_metadata_ready_74a &&
                     save_metadata_table_published &&
                     !save_metadata_cdc_busy_74a &&
                     rtc_transfer_delivered && !rtc_transfer_failed),
      .initializers_ready(save_initialization_resolved_74a),
      .ready_to_run_pulse(startup_ready_to_run_pulse),
      .startup_complete(startup_complete),
      .data_slots_seen(startup_data_slots_seen),
      .rtc_seen(startup_rtc_seen),
      .status_code(startup_status_code),
      .status_booting(startup_status_booting),
      .status_setup(startup_status_setup),
      .status_idle(startup_status_idle),
      .status_running(startup_status_running),
      .core_run_enable(core_run_enable)
  );

  wire cartridge_size_supported =
      (dataslot_requestwrite_size >= 48'd65536) &&
      (dataslot_requestwrite_size <= 48'd16777216) &&
      ((dataslot_requestwrite_size & (dataslot_requestwrite_size - 48'd1)) == 48'd0);
  wire [47:0] canonical_save_size =
      {28'd0, save_size_bytes_74a} + (has_rtc_74a ? 48'd12 : 48'd0);
  wire legacy_small_eeprom_save =
      has_rtc_74a &&
      ((save_size_bytes_74a == 20'd128) ||
       (save_size_bytes_74a == 20'd1024)) &&
      (dataslot_requestwrite_size == 48'd2060);
  wire save_write_size_supported =
      (dataslot_requestwrite_size == 48'd0) ||
      (dataslot_requestwrite_size == canonical_save_size) ||
      legacy_small_eeprom_save;

  always @(*) begin
    dataslot_policy_known = 1'b1;
    dataslot_policy_allow_read = 1'b0;
    dataslot_policy_allow_write = 1'b0;
    dataslot_policy_bounds_ready = 1'b1;
    dataslot_policy_size_mode = 2'd0;
    dataslot_policy_exact_size = 48'd0;
    dataslot_policy_min_size = 48'd0;
    dataslot_policy_max_size = 48'd0;
    dataslot_policy_capture_length = 1'b0;

    case (dataslot_policy_id)
      16'd0: begin
        // The implemented mapper is 24-bit: accept power-of-two ROM images
        // from 64 KiB through 16 MiB, host-to-core only.
        dataslot_policy_allow_write = cartridge_size_supported;
      end
      16'd9: begin
        dataslot_policy_allow_write = 1'b1;
        dataslot_policy_size_mode = 2'd1;
        dataslot_policy_exact_size = 48'd4096;
      end
      16'd10: begin
        dataslot_policy_allow_write = 1'b1;
        dataslot_policy_size_mode = 2'd1;
        dataslot_policy_exact_size = 48'd8192;
      end
      16'd11: begin
        dataslot_policy_allow_read = 1'b1;
        // Until the footer snapshot arrives, the same request can succeed
        // later. Once known, malformed/type-inconsistent lengths are result 1.
        dataslot_policy_allow_write = !save_metadata_ready_74a ||
                                      save_write_size_supported;
        dataslot_policy_bounds_ready = save_metadata_ready_74a;
        dataslot_policy_capture_length = 1'b1;
      end
      default: begin
        dataslot_policy_known = 1'b0;
      end
    endcase
  end

  apf_dataslot_guard pocket_dataslot_guard (
      .clk(clk_74a),
      .reset_n(pll_core_ready_74a),
      .request_valid(dataslot_request_valid),
      .request_write(dataslot_requestwrite),
      .request_id(dataslot_request_id),
      .request_size(dataslot_request_size),
      .request_ack(dataslot_guard_ack),
      .request_result(dataslot_guard_result),
      .request_busy(dataslot_guard_busy),
      .policy_slot_id(dataslot_policy_id),
      .policy_slot_known(dataslot_policy_known),
      .policy_allow_read(dataslot_policy_allow_read),
      .policy_allow_write(dataslot_policy_allow_write),
      .policy_bounds_ready(dataslot_policy_bounds_ready),
      .policy_size_mode(dataslot_policy_size_mode),
      .policy_exact_size(dataslot_policy_exact_size),
      .policy_min_size(dataslot_policy_min_size),
      .policy_max_size(dataslot_policy_max_size),
      .policy_capture_length(dataslot_policy_capture_length),
      .read_loader_ready(startup_complete && !reset_n &&
                         !execution_ready_74a && save_backend_quiesced &&
                         save_metadata_table_published &&
                         save_initialization_resolved_74a),
      .write_loader_ready(pll_core_ready_74a),
      .captured_length_clear(cart_download),
      .captured_save_length_valid(captured_save_length_valid),
      .captured_save_id(captured_save_id),
      .captured_save_length(captured_save_length),
      .captured_save_length_updated(captured_save_length_updated)
  );

  // Save states
  // Save state unloader
  wire ss_busy;
  wire [63:0] ss_din;
  wire [63:0] ss_dout;
  wire [25:0] ss_addr;
  wire ss_rnw;
  wire ss_req;
  wire [7:0] ss_be;
  wire ss_ack;

  wire ss_save;
  wire ss_load;

  wire [31:0] save_state_bridge_read_data;

  save_state_controller save_state_controller (
      .clk_74a(clk_74a),
      .clk_sys(clk_sys_36_864),

      // APF
      .bridge_wr(bridge_wr),
      .bridge_rd(bridge_rd),
      .bridge_endian_little(bridge_endian_little),
      .bridge_addr(bridge_addr),
      .bridge_wr_data(bridge_wr_data),
      .save_state_bridge_read_data(save_state_bridge_read_data),

      // APF Save States
      .savestate_load(savestate_load),
      .savestate_load_ack_s(savestate_load_ack),
      .savestate_load_busy_s(savestate_load_busy),
      .savestate_load_ok_s(savestate_load_ok),
      .savestate_load_err_s(savestate_load_err),

      .savestate_start(savestate_start),
      .savestate_start_ack_s(savestate_start_ack),
      .savestate_start_busy_s(savestate_start_busy),
      .savestate_start_ok_s(savestate_start_ok),
      .savestate_start_err_s(savestate_start_err),

      // Save States Manager
      .ss_save(ss_save),
      .ss_load(ss_load),

      .ss_din (ss_din),
      .ss_dout(ss_dout),
      .ss_addr(ss_addr),
      .ss_rnw (ss_rnw),
      .ss_req (ss_req),
      .ss_be  (ss_be),
      .ss_ack (ss_ack),

      .ss_busy(ss_busy)
  );

  wire ioctl_wr;
  wire [24:0] ioctl_addr;
  wire [15:0] ioctl_dout;

  wire rom_write_complete;

  data_loader #(
      .ADDRESS_MASK_UPPER_4(4'h1),
      .ADDRESS_SIZE(25),
      .OUTPUT_WORD_SIZE(2),
      .USE_WRITE_COMPLETE(1)
  ) data_loader (
      .clk_74a(clk_74a),
      .clk_memory(clk_mem_110_592),

      .bridge_wr(bridge_wr),
      .bridge_endian_little(bridge_endian_little),
      .bridge_addr(bridge_addr),
      .bridge_wr_data(bridge_wr_data),

      .write_complete(rom_write_complete),

      .write_en  (ioctl_wr),
      .write_addr(ioctl_addr),
      .write_data(ioctl_dout)
  );

  wire bios_wr;
  wire [12:0] bios_addr;
  wire [15:0] bios_dout;

  data_loader #(
      .ADDRESS_MASK_UPPER_4(4'h3),
      .ADDRESS_SIZE(13),
      .OUTPUT_WORD_SIZE(2),
      .WRITE_MEM_CLOCK_DELAY(4),
      .WRITE_MEM_EN_CYCLE_LENGTH(1)
  ) bios_data_loader (
      .clk_74a(clk_74a),
      .clk_memory(clk_sys_36_864),

      .bridge_wr(bridge_wr),
      .bridge_endian_little(bridge_endian_little),
      .bridge_addr(bridge_addr),
      .bridge_wr_data(bridge_wr_data),

      .write_en  (bios_wr),
      .write_addr(bios_addr),
      .write_data(bios_dout)
  );

  wire [31:0] sd_read_data;

  wire sd_buff_wr;
  wire sd_buff_rd;

  wire [20:0] sd_buff_addr_in;
  wire [20:0] sd_buff_addr_out;

  wire [20:0] sd_buff_addr = sd_buff_wr ? sd_buff_addr_in : sd_buff_addr_out;

  wire [15:0] sd_buff_din;
  wire [15:0] sd_buff_dout;

  wire save_ram_write_complete;

  data_loader #(
      .ADDRESS_MASK_UPPER_4(4'h2),
      .ADDRESS_SIZE(21),
      .OUTPUT_WORD_SIZE(2),
      .WRITE_MEM_CLOCK_DELAY(20),
      .USE_WRITE_COMPLETE(1)
  ) save_data_loader (
      .clk_74a(clk_74a),
      .clk_memory(clk_mem_110_592),

      .bridge_wr(bridge_wr),
      .bridge_endian_little(bridge_endian_little),
      .bridge_addr(bridge_addr),
      .bridge_wr_data(bridge_wr_data),

      .write_complete(save_ram_write_complete),

      .write_en  (sd_buff_wr),
      .write_addr(sd_buff_addr_in),
      .write_data(sd_buff_dout)
  );

  data_unloader #(
      .ADDRESS_MASK_UPPER_4(4'h2),
      .ADDRESS_SIZE(21),
      .INPUT_WORD_SIZE(2),
      .READ_MEM_CLOCK_DELAY(20)
  ) save_data_unloader (
      .clk_74a(clk_74a),
      .clk_memory(clk_sys_36_864),

      .bridge_rd(bridge_rd),
      .bridge_endian_little(bridge_endian_little),
      .bridge_addr(bridge_addr),
      .bridge_rd_data(sd_read_data),

      .read_en  (sd_buff_rd),
      .read_addr(sd_buff_addr_out),
      .read_data(sd_buff_din)
  );

  wire [15:0] audio_l;
  wire [15:0] audio_r;

  // Driven by CHIP32
  reg cart_download = 0;
  reg is_color_cart = 0;

  reg bw_bios_download = 0;
  reg color_bios_download = 0;

  // Unused
  // reg save_download = 0;

  wire [1:0] bios_download = {color_bios_download, bw_bios_download};
  wire [1:0] ext_cart_download = is_color_cart ? {cart_download, 1'b0} : {1'b0, cart_download};

  // Settings
  reg [31:0] reset_delay = 0;
  wire external_reset = reset_delay > 0;

  reg [1:0] configured_system;

  reg use_cpu_turbo;
  // reg use_rewind_capture;

  reg use_triple_buffer;
  reg [1:0] configured_flickerblend;
  reg [1:0] configured_orientation;
  reg use_flip_horizontal;

  reg use_fastforward_sound;

  // Reset and download controls are consumed in two clock domains. Keep a
  // dedicated copy in each destination domain; a signal synchronized to the
  // memory clock is not a safe reset or control input for clk_sys logic.
  wire reset_n_mem_s;
  wire reset_n_sys_s;
  wire external_reset_sys_s;

  wire [1:0] ext_cart_download_mem_s;
  wire [1:0] ext_cart_download_sys_s;
  wire [1:0] bios_download_sys_s;

  wire [1:0] configured_system_s;

  wire use_cpu_turbo_s;
  // wire use_rewind_capture_s;

  wire use_triple_buffer_s;
  wire [1:0] configured_flickerblend_s;
  wire [1:0] configured_orientation_s;
  wire use_flip_horizontal_s;

  wire use_fastforward_sound_s;

  apf_reset_sync core_reset_memory (
      .clk(clk_mem_110_592),
      .reset_n_async(reset_n),
      .reset_n_sync(reset_n_mem_s)
  );

  apf_reset_sync core_reset_system (
      .clk(clk_sys_36_864),
      .reset_n_async(reset_n),
      .reset_n_sync(reset_n_sys_s)
  );

  synch_3 #(
      .WIDTH(2)
  ) cart_download_memory_s (
      ext_cart_download,
      ext_cart_download_mem_s,
      clk_mem_110_592
  );

  synch_3 #(
      .WIDTH(5)
  ) download_system_s (
      {external_reset, ext_cart_download, bios_download},
      {external_reset_sys_s, ext_cart_download_sys_s, bios_download_sys_s},
      clk_sys_36_864
  );

  synch_3 #(
      .WIDTH(10)
  ) settings_s (
      {
        configured_system,
        use_cpu_turbo,
        // use_rewind_capture,
        use_triple_buffer,
        configured_flickerblend,
        configured_orientation,
        use_flip_horizontal,
        use_fastforward_sound
      },
      {
        configured_system_s,
        use_cpu_turbo_s,
        // use_rewind_capture_s,
        use_triple_buffer_s,
        configured_flickerblend_s,
        configured_orientation_s,
        use_flip_horizontal_s,
        use_fastforward_sound_s
      },
      clk_sys_36_864
  );

  wire [15:0] cont1_key_s;

  synch_3 #(
      .WIDTH(16)
  ) cont1_s (
      cont1_key,
      cont1_key_s,
      clk_sys_36_864
  );

  wonderswan wonderswan (
      .clk_sys_36_864 (clk_sys_36_864),
      .clk_mem_110_592(clk_mem_110_592),

      .reset_n(reset_n_mem_s),
      .reset_n_sys(reset_n_sys_s),
      .pll_core_locked(pll_core_ready_mem),
      .external_reset(external_reset_sys_s),

      .ioctl_wr  (ioctl_wr),
      .ioctl_addr(ioctl_addr),
      .ioctl_dout(ioctl_dout),

      .ext_cart_download(ext_cart_download_mem_s),
      .ext_cart_download_sys(ext_cart_download_sys_s),

      .bios_wr(bios_wr),
      .bios_addr(bios_addr),
      .bios_dout(bios_dout),
      .bios_download(bios_download_sys_s),

      .rom_write_complete(rom_write_complete),

      .rtc_epoch_seconds(rtc_epoch_seconds_sys),
      .rtc_epoch_valid(rtc_valid_sys),

      // Inputs
      .button_a(cont1_key_s[4]),
      .button_b(cont1_key_s[5]),
      .button_x(cont1_key_s[6]),
      .button_y(cont1_key_s[7]),
      .button_trig_l(cont1_key_s[8]),
      .button_trig_r(cont1_key_s[9]),
      .button_start(cont1_key_s[15]),
      .button_select(cont1_key_s[14]),
      .dpad_up(cont1_key_s[0]),
      .dpad_down(cont1_key_s[1]),
      .dpad_left(cont1_key_s[2]),
      .dpad_right(cont1_key_s[3]),

      // Settings
      .configured_system(configured_system_s),
      .use_cpu_turbo(use_cpu_turbo_s),
      // .use_rewind_capture(use_rewind_capture_s),

      .use_triple_buffer(use_triple_buffer_s),
      .configured_flickerblend(configured_flickerblend_s),
      .use_flip_horizontal(use_flip_horizontal_s),

      .use_fastforward_sound(use_fastforward_sound_s),

      // Saves
      .save_size_bytes(save_size_bytes),
      .has_rtc(has_rtc),
      .load_complete(dataslot_allcomplete_mem),
      .save_metadata_commit(save_metadata_commit),
      .save_initialization_resolved(save_initialization_resolved_mem),
      .execution_ready(execution_ready_sys),
      .sd_buff_wr(sd_buff_wr),
      .sd_buff_rd(sd_buff_rd),
      .sd_buff_addr(sd_buff_addr),
      .sd_buff_din(sd_buff_din),
      .sd_buff_dout(sd_buff_dout),

      .save_ram_write_complete(save_ram_write_complete),

      // Save states
      .ss_save(ss_save),
      .ss_load(ss_load),

      .ss_busy(ss_busy),

      .ss_din (ss_din),
      .ss_dout(ss_dout),
      .ss_addr(ss_addr),
      .ss_rnw (ss_rnw),
      .ss_req (ss_req),
      .ss_be  (ss_be),
      .ss_ack (ss_ack),

      // SDRAM
      .dram_a(dram_a),
      .dram_ba(dram_ba),
      .dram_dq(dram_dq),
      .dram_dqm(dram_dqm),
      .dram_clk(dram_clk),
      .dram_cke(dram_cke),
      .dram_ras_n(dram_ras_n),
      .dram_cas_n(dram_cas_n),
      .dram_we_n(dram_we_n),

      .hblank(h_blank),
      .vblank(v_blank),
      .hsync(video_hs_core),
      .vsync(video_vs_core),
      .video_r(vid_rgb_core[23:16]),
      .video_g(vid_rgb_core[15:8]),
      .video_b(vid_rgb_core[7:0]),
      .is_vertical(is_vertical),

      .audio_l(audio_l),
      .audio_r(audio_r)
  );

  ////////////////////////////////////////////////////////////////////////////////////////

  // Video
  wire h_blank;
  wire v_blank;
  wire video_hs_core;
  wire video_vs_core;
  wire [23:0] vid_rgb_core;
  wire is_vertical;

  reg video_de_reg;
  reg video_hs_reg;
  reg video_vs_reg;
  reg [23:0] video_rgb_reg;

  assign video_rgb_clock = clk_vid_3_75;
  assign video_rgb_clock_90 = clk_vid_3_75_90deg;
  assign video_rgb = video_rgb_reg;
  assign video_de = video_de_reg;
  assign video_skip = 0;
  assign video_vs = video_vs_reg;
  assign video_hs = video_hs_reg;

  reg [2:0] hs_delay;
  reg hs_prev;
  reg vs_prev;
  reg de_prev;

  wire de = ~(h_blank || v_blank);
  wire [23:0] displaymode_video_rgb;
  apf_grayscale_video displaymode_video (
      .rgb(vid_rgb_core),
      .enabled(displaymode_grayscale_applied),
      .rgb_out(displaymode_video_rgb)
  );
  // If any vertical orientation, use second slot
  wire video_orientation = configured_orientation_s == 0 ?  // Auto
  is_vertical : configured_orientation_s == 2;  // Vertical
  wire [23:0] video_slot_rgb = {10'b0, video_orientation, 10'b0, 3'b0};

  always @(posedge clk_vid_3_75) begin
    video_hs_reg  <= 0;
    video_de_reg  <= 0;
    video_rgb_reg <= 24'h0;

    if (de) begin
      video_de_reg  <= 1;

      video_rgb_reg <= displaymode_video_rgb;
    end else if (de_prev && ~de) begin
      video_rgb_reg <= video_slot_rgb;
    end

    if (hs_delay > 0) begin
      hs_delay <= hs_delay - 1;
    end

    if (hs_delay == 1) begin
      video_hs_reg <= 1;
    end

    if (~hs_prev && video_hs_core) begin
      // HSync went high. Delay by 3 cycles to prevent overlapping with VSync
      hs_delay <= 7;
    end

    // Set VSync to be high for a single cycle on the rising edge of the VSync coming out of the core
    video_vs_reg <= ~vs_prev && video_vs_core;
    if (~vs_prev && video_vs_core) begin
      displaymode_grayscale_applied <= displaymode_grayscale_video;
    end
    hs_prev <= video_hs_core;
    vs_prev <= video_vs_core;
    de_prev <= de;
  end

  ///////////////////////////////////////////////

  sound_i2s #(
      .CHANNEL_WIDTH(16),
      .SIGNED_INPUT (1)
  ) sound_i2s (
      .clk_74a  (clk_74a),
      .clk_audio(clk_sys_36_864),

      .audio_l(audio_l),
      .audio_r(audio_r),

      .audio_mclk(audio_mclk),
      .audio_lrck(audio_lrck),
      .audio_dac (audio_dac)
  );

  ///////////////////////////////////////////////

  wire clk_mem_110_592;
  wire clk_sys_36_864;
  wire clk_vid_3_75;
  wire clk_vid_3_75_90deg;

  wire pll_core_locked;

  // B8 is received on the 74.25 MHz BRIDGE clock.  Apply it only after the
  // request crosses into the pixel domain and is applied on a frame boundary,
  // then synchronize that applied state back before core_bridge_cmd returns
  // Pocket's 0x444D affirmation.
  synch_3 displaymode_grayscale_to_video (
      osnotify_displaymode_grayscale,
      displaymode_grayscale_video,
      clk_vid_3_75
  );

  synch_3 displaymode_grayscale_to_bridge (
      displaymode_grayscale_applied,
      displaymode_grayscale_ack,
      clk_74a
  );

  mf_pllbase mp1 (
      .refclk(clk_74a),
      .rst   (0),

      .outclk_0(clk_mem_110_592),
      .outclk_1(clk_sys_36_864),
      .outclk_2(clk_vid_3_75),
      .outclk_3(clk_vid_3_75_90deg),

      .locked(pll_core_locked)
  );

endmodule
