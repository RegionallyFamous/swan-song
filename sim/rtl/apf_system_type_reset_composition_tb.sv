`timescale 1ps/1ps

// Unrelated primitives needed by core_bridge_cmd/wonderswan are intentionally
// inert. The settings CDC, Reset Exit handler, reset synchronizer, and
// configured_system_active latch are the production modules.
module synch_3 (
    input  wire in,
    output wire out,
    input  wire clk
);
    assign out = in;
endmodule

module mf_datatable (
    input  wire [9:0]  address_a,
    input  wire [9:0]  address_b,
    input  wire        clock_a,
    input  wire        clock_b,
    input  wire [31:0] data_a,
    input  wire [31:0] data_b,
    input  wire        wren_a,
    input  wire        wren_b,
    output wire [31:0] q_a,
    output wire [31:0] q_b
);
    assign q_a = 32'd0;
    assign q_b = 32'd0;
endmodule

module apf_system_type_reset_composition_tb;
    localparam [12:0] DEFAULT_SETTINGS = 13'h0201;
    localparam [31:0] HOST_STATUS = 32'hf800_0000;
    localparam [31:0] TARGET_STATUS = 32'hf800_1000;

    reg clk_source = 1'b0;
    reg clk_destination = 1'b0;
    reg pll_ready = 1'b0;
    integer destination_phase_ps = 0;

    reg  [31:0] bridge_addr = 32'd0;
    reg         bridge_rd = 1'b0;
    wire [31:0] bridge_rd_data;
    reg         bridge_wr = 1'b0;
    reg  [31:0] bridge_wr_data = 32'd0;

    reg status_setup_done = 1'b0;
    wire reset_n;
    wire reset_n_sys;
    wire ready_to_run_complete;

    reg [1:0] configured_system = 2'd0;
    wire [12:0] settings_source = {
        configured_system,
        1'b0,       // CPU Turbo
        1'b1,       // Triple Buffer
        2'b00,      // LCD Response
        2'b00,      // Display Orientation
        2'b00,      // Control Layout
        1'b0,       // Landscape 180
        1'b0,       // Color Profile
        1'b1        // Audio in Fast Forward
    };
    wire [12:0] settings_destination;
    wire settings_update_pending;

    // This is the production core_top Reset Exit fence for the System Type
    // register under test. Its command-side consumer is the real handler below.
    wire settings_write = bridge_wr && bridge_addr == 32'h0000_0100;
    wire reset_exit_ready = !settings_write && !settings_update_pending;

    reg [31:0] readback;
    integer timeout;
    integer release_checks = 0;
    reg release_watch = 1'b0;
    reg release_seen = 1'b0;
    reg [1:0] expected_active_system = 2'b00;

    always #3500 clk_source = ~clk_source;
    initial begin
        if (!$value$plusargs("destination_phase_ps=%d", destination_phase_ps))
            destination_phase_ps = 0;
        #(destination_phase_ps);
        forever #11500 clk_destination = ~clk_destination;
    end

    // Use the source-domain register semantics from core_top. Invalid persisted
    // encodings fail back to Auto before entering the atomic settings bundle.
    always @(posedge clk_source) begin
        if (bridge_wr && bridge_addr == 32'h0000_0100)
            configured_system <= bridge_wr_data[1:0] > 2'd2 ?
                                 2'd0 : bridge_wr_data[1:0];
    end

    apf_settings_cdc #(
        .DEFAULT_SETTINGS(DEFAULT_SETTINGS)
    ) settings_cdc (
        .reset_n(pll_ready),
        .clk_source(clk_source),
        .settings_source(settings_source),
        .update_pending_source(settings_update_pending),
        .clk_destination(clk_destination),
        .settings_destination(settings_destination)
    );

    apf_reset_sync system_reset_sync (
        .clk(clk_destination),
        .reset_n_async(reset_n),
        .reset_n_sync(reset_n_sys)
    );

    core_bridge_cmd bridge_commands (
        .clk(clk_source),
        .reset_n(reset_n),
        .bridge_endian_little(1'b0),
        .bridge_addr(bridge_addr),
        .bridge_rd(bridge_rd),
        .bridge_rd_data(bridge_rd_data),
        .bridge_wr(bridge_wr),
        .bridge_wr_data(bridge_wr_data),
        .status_boot_done(pll_ready),
        .status_setup_done(status_setup_done),
        .status_running(reset_n_sys),
        .reset_exit_ready(reset_exit_ready),
        .ready_to_run_complete(ready_to_run_complete),
        .dataslot_requestread_ack(1'b0),
        .dataslot_requestread_result(2'd0),
        .dataslot_requestwrite_ack(1'b0),
        .dataslot_requestwrite_result(2'd0),
        .savestate_supported(1'b0),
        .savestate_addr(32'd0),
        .savestate_size(32'd0),
        .savestate_maxloadsize(32'd0),
        .savestate_start_ack(1'b0),
        .savestate_start_busy(1'b0),
        .savestate_start_ok(1'b0),
        .savestate_start_err(1'b0),
        .savestate_load_ack(1'b0),
        .savestate_load_busy(1'b0),
        .savestate_load_ok(1'b0),
        .savestate_load_err(1'b0),
        .displaymode_grayscale_ack(1'b0),
        .target_dataslot_read(1'b0),
        .target_dataslot_write(1'b0),
        .target_dataslot_id(16'd0),
        .target_dataslot_slotoffset(32'd0),
        .target_dataslot_bridgeaddr(32'd0),
        .target_dataslot_length(32'd0),
        .datatable_addr(10'd0),
        .datatable_wren(1'b0),
        .datatable_data(32'd0)
    );

    // This is the production latch path. Other WonderSwan subsystems are
    // black boxes in this focused build, as in footer_snapshot_tb.
    wonderswan model_path (
        .clk_sys_36_864(clk_destination),
        .clk_mem_110_592(clk_destination),
        .reset_n(reset_n_sys),
        .reset_n_sys(reset_n_sys),
        .pll_core_locked(pll_ready),
        .external_reset(1'b0),
        .ioctl_wr(1'b0),
        .ioctl_addr(25'd0),
        .ioctl_dout(16'd0),
        .rom_size_mem(25'd0),
        .rom_plan_valid_mem(1'b0),
        .rom_size_sys(25'd0),
        .rom_plan_valid_sys(1'b0),
        .ext_cart_download(2'b00),
        .ext_cart_download_sys(2'b00),
        .rtc_epoch_seconds(32'd0),
        .rtc_epoch_valid(1'b0),
        .button_a(1'b0),
        .button_b(1'b0),
        .button_x(1'b0),
        .button_y(1'b0),
        .button_trig_l(1'b0),
        .button_trig_r(1'b0),
        .button_start(1'b0),
        .button_select(1'b0),
        .dpad_up(1'b0),
        .dpad_down(1'b0),
        .dpad_left(1'b0),
        .dpad_right(1'b0),
        .physical_input_blocked(1'b0),
        .menu_focus_paused(1'b0),
        .configured_system(settings_destination[12:11]),
        .use_cpu_turbo(settings_destination[10]),
        .use_rewind_capture(1'b0),
        .use_triple_buffer(settings_destination[9]),
        .configured_flickerblend(settings_destination[8:7]),
        .configured_orientation(settings_destination[6:5]),
        .configured_control_layout(settings_destination[4:3]),
        .use_flip_horizontal(settings_destination[2]),
        .configured_color_profile(settings_destination[1]),
        .use_fastforward_sound(settings_destination[0]),
        .load_complete(1'b0),
        .sd_buff_wr(1'b0),
        .sd_buff_rd(1'b0),
        .sd_buff_addr(21'd0),
        .sd_buff_dout(16'd0),
        .console_eeprom_wr(1'b0),
        .console_eeprom_rd(1'b0),
        .console_eeprom_bank(1'b0),
        .console_eeprom_addr(11'd0),
        .console_eeprom_dout(16'd0),
        .ss_save(1'b0),
        .ss_load(1'b0),
        .ss_dout(64'd0),
        .ss_ack(1'b0)
    );

    // The assertion is sampled after destination-domain nonblocking updates.
    // Therefore this is exactly the first cycle on which reset is inactive to
    // SwanTop, not a later observation hidden behind a testbench delay.
    always @(posedge clk_destination) begin
        #1;
        if (release_watch && !model_path.reset) begin
            if (release_seen)
                $fatal(1, "release watcher observed a duplicate first cycle");
            release_seen = 1'b1;
            release_watch = 1'b0;
            release_checks = release_checks + 1;
            if (model_path.configured_system_active !== expected_active_system)
                $fatal(1,
                       "first non-reset cycle used stale System Type phase=%0d expected=%0d active=%0d requested=%0d destination=%0d",
                       destination_phase_ps, expected_active_system,
                       model_path.configured_system_active, configured_system,
                       settings_destination[12:11]);
        end
    end

    task automatic host_write(input [31:0] address, input [31:0] data);
        begin
            @(negedge clk_source);
            bridge_addr = address;
            bridge_wr_data = data;
            bridge_wr = 1'b1;
            @(negedge clk_source);
            bridge_wr = 1'b0;
        end
    endtask

    task automatic host_read(input [31:0] address, output [31:0] data);
        begin
            @(negedge clk_source);
            bridge_addr = address;
            bridge_rd = 1'b1;
            @(negedge clk_source);
            data = bridge_rd_data;
            bridge_rd = 1'b0;
        end
    endtask

    task automatic start_host_command(input [15:0] command);
        begin
            host_write(HOST_STATUS, {16'h434d, command});
        end
    endtask

    task automatic wait_host_done;
        integer attempt;
        begin : wait_block
            for (attempt = 0; attempt < 256; attempt = attempt + 1) begin
                host_read(HOST_STATUS, readback);
                if (readback[31:16] == 16'h4f4b)
                    disable wait_block;
            end
            $fatal(1, "host command timeout status=%08x", readback);
        end
    endtask

    task automatic expect_command_done(input [15:0] command);
        begin
            start_host_command(command);
            wait_host_done();
            if (readback !== 32'h4f4b_0000)
                $fatal(1, "command %04x result=%08x", command, readback);
        end
    endtask

    task automatic service_ready_to_run;
        integer attempt;
        begin : wait_target
            for (attempt = 0; attempt < 256; attempt = attempt + 1) begin
                host_read(TARGET_STATUS, readback);
                if (readback === 32'h636d_0140)
                    disable wait_target;
            end
            $fatal(1, "target 0140 was not issued");
        end
        host_write(TARGET_STATUS, 32'h6275_0140);
        repeat (3) @(posedge clk_source);
        host_write(TARGET_STATUS, 32'h6f6b_0000);
        repeat (4) @(posedge clk_source);
        if (!ready_to_run_complete)
            $fatal(1, "target 0140 was not acknowledged");
    endtask

    task automatic arm_release(input [1:0] expected);
        begin
            expected_active_system = expected;
            release_seen = 1'b0;
            release_watch = 1'b1;
        end
    endtask

    task automatic wait_release(input [1:0] expected);
        begin : release_wait
            for (timeout = 0; timeout < 64; timeout = timeout + 1) begin
                @(posedge clk_destination);
                #2;
                if (release_seen)
                    disable release_wait;
            end
            $fatal(1, "System Type release was not observed expected=%0d", expected);
        end
        if (model_path.configured_system_active !== expected ||
            settings_destination[12:11] !== expected)
            $fatal(1, "post-release System Type mismatch expected=%0d", expected);
    endtask

    task automatic enter_reset;
        begin
            expect_command_done(16'h0010);
            #1;
            if (reset_n || reset_n_sys || !model_path.reset)
                $fatal(1, "Reset Enter did not reach the production latch path");
        end
    endtask

    initial begin
        #17250;
        pll_ready = 1'b1;
        repeat (5) @(posedge clk_source);
        repeat (4) @(posedge clk_destination);

        status_setup_done = 1'b1;
        service_ready_to_run();
        expect_command_done(16'h0011);
        repeat (4) @(posedge clk_destination);
        if (!reset_n_sys || model_path.configured_system_active !== 2'b00)
            $fatal(1, "cold Auto boot failed");

        // 1. System Type is written before Reset Exit begins.
        enter_reset();
        arm_release(2'b10);
        host_write(32'h0000_0100, 32'd2);
        start_host_command(16'h0011);
        wait_host_done();
        wait_release(2'b10);

        // 2. The setting write occupies the command's ST_PARSE cycle.
        enter_reset();
        arm_release(2'b01);
        start_host_command(16'h0011);
        host_write(32'h0000_0100, 32'd1);
        wait_host_done();
        wait_release(2'b01);

        // 3. Reset Exit is already waiting on one transfer when a newer value
        // supersedes it. The final value, not the in-flight one, must boot.
        enter_reset();
        arm_release(2'b10);
        host_write(32'h0000_0100, 32'd0);
        start_host_command(16'h0011);
        host_write(32'h0000_0100, 32'd2);
        wait_host_done();
        wait_release(2'b10);

        if (release_checks != 3)
            $fatal(1, "composition matrix incomplete releases=%0d", release_checks);

        $display(
            "PASS APF System Type reset composition phase=%0d releases=%0d scenarios=pre/same/waiting",
            destination_phase_ps, release_checks
        );
        $finish;
    end
endmodule
