`timescale 1ns/1ps

// Focused stand-ins for primitives used by core_bridge_cmd. The settings CDC
// itself is instantiated below with genuinely unrelated clocks.
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

module apf_settings_boot_barrier_tb;
    localparam [12:0] DEFAULT_SETTINGS = 13'h0201;
    localparam [31:0] HOST_STATUS = 32'hf800_0000;
    localparam [31:0] TARGET_STATUS = 32'hf800_1000;

    reg clk_source = 1'b0;
    reg clk_destination = 1'b0;
    reg pll_ready = 1'b0;

    reg         bridge_endian_little = 1'b0;
    reg  [31:0] bridge_addr = 32'd0;
    reg         bridge_rd = 1'b0;
    wire [31:0] bridge_rd_data;
    reg         bridge_wr = 1'b0;
    reg  [31:0] bridge_wr_data = 32'd0;

    reg status_setup_done = 1'b0;
    wire reset_n;
    wire ready_to_run_complete;
    wire status_running = reset_n;

    reg [1:0] configured_system = 2'd0;
    reg       use_cpu_turbo = 1'b0;
    reg       use_triple_buffer = 1'b1;
    reg [1:0] configured_flickerblend = 2'd0;
    reg [1:0] configured_orientation = 2'd0;
    reg [1:0] configured_control_layout = 2'd0;
    reg       use_flip_horizontal = 1'b0;
    reg       configured_color_profile = 1'b0;
    reg       use_fastforward_sound = 1'b1;

    wire [12:0] settings_source = {
        configured_system,
        use_cpu_turbo,
        use_triple_buffer,
        configured_flickerblend,
        configured_orientation,
        configured_control_layout,
        use_flip_horizontal,
        configured_color_profile,
        use_fastforward_sound
    };
    wire [12:0] settings_destination;
    wire settings_update_pending;

    wire settings_write = bridge_wr &&
        ((bridge_addr == 32'h0000_0100) ||
         (bridge_addr == 32'h0000_0110) ||
         (bridge_addr == 32'h0000_0200) ||
         (bridge_addr == 32'h0000_0204) ||
         (bridge_addr == 32'h0000_0208) ||
         (bridge_addr == 32'h0000_020c) ||
         (bridge_addr == 32'h0000_0210) ||
         (bridge_addr == 32'h0000_0214) ||
         (bridge_addr == 32'h0000_0300));
    wire reset_exit_ready = !settings_write && !settings_update_pending;

    reg [31:0] readback;
    reg [12:0] no_op_settings_snapshot;
    integer timeout;
    integer reset_release_count = 0;
    reg reset_n_previous = 1'b0;

    // 7 ns and 23 ns are deliberately unrelated. The slow destination makes
    // the boot fence observable even for back-to-back APF transactions.
    always #3.5 clk_source = ~clk_source;
    always #11.5 clk_destination = ~clk_destination;

    always @(posedge clk_source) begin
        #1ps;
        if (reset_n && !reset_n_previous) begin
            reset_release_count = reset_release_count + 1;
            if (settings_update_pending ||
                settings_destination !== settings_source) begin
                $fatal(1,
                       "console released before final settings ack source=%04x destination=%04x pending=%b",
                       settings_source, settings_destination,
                       settings_update_pending);
            end
        end
        reset_n_previous = reset_n;
    end

    always @(posedge clk_source) begin
        if (bridge_wr) begin
            case (bridge_addr)
                32'h0000_0100:
                    configured_system <= bridge_wr_data[1:0] > 2'd2 ?
                                         2'd0 : bridge_wr_data[1:0];
                32'h0000_0110: use_cpu_turbo <= bridge_wr_data[0];
                32'h0000_0200: use_triple_buffer <= bridge_wr_data[0];
                32'h0000_0204:
                    configured_flickerblend <= bridge_wr_data[1:0] > 2'd2 ?
                                               2'd0 : bridge_wr_data[1:0];
                32'h0000_0208:
                    configured_orientation <= bridge_wr_data[1:0] > 2'd2 ?
                                              2'd0 : bridge_wr_data[1:0];
                32'h0000_020c: use_flip_horizontal <= bridge_wr_data[0];
                32'h0000_0210: configured_color_profile <= bridge_wr_data[0];
                32'h0000_0214:
                    configured_control_layout <= bridge_wr_data > 32'd2 ?
                                                 2'd0 : bridge_wr_data[1:0];
                32'h0000_0300: use_fastforward_sound <= bridge_wr_data[0];
            endcase
        end
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

    core_bridge_cmd bridge_commands (
        .clk(clk_source),
        .reset_n(reset_n),
        .bridge_endian_little(bridge_endian_little),
        .bridge_addr(bridge_addr),
        .bridge_rd(bridge_rd),
        .bridge_rd_data(bridge_rd_data),
        .bridge_wr(bridge_wr),
        .bridge_wr_data(bridge_wr_data),
        .status_boot_done(pll_ready),
        .status_setup_done(status_setup_done),
        .status_running(status_running),
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
            for (attempt = 0; attempt < 160; attempt = attempt + 1) begin
                host_read(HOST_STATUS, readback);
                if (readback[31:16] == 16'h4f4b)
                    disable wait_block;
            end
            $fatal(1, "host command timeout status=%08x hstate=%0d",
                   readback, bridge_commands.hstate);
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

    task automatic expect_reset_exit_busy;
        integer attempt;
        begin : wait_busy
            for (attempt = 0; attempt < 24; attempt = attempt + 1) begin
                host_read(HOST_STATUS, readback);
                if (reset_n !== 1'b0)
                    $fatal(1,
                           "Reset Exit released before BUSY status=%08x pending=%b",
                           readback, settings_update_pending);
                if (readback === 32'h4255_0011)
                    disable wait_busy;
            end
            if (readback !== 32'h4255_0011)
                $fatal(1,
                       "Reset Exit never reached BUSY status=%08x pending=%b",
                       readback, settings_update_pending);
        end
    endtask

    task automatic wait_settings(input [12:0] expected);
        begin : wait_block
            for (timeout = 0; timeout < 320; timeout = timeout + 1) begin
                @(posedge clk_source);
                #1ps;
                if (!settings_update_pending &&
                    settings_destination === expected)
                    disable wait_block;
            end
            $fatal(1,
                   "settings timeout expected=%04x source=%04x destination=%04x pending=%b",
                   expected, settings_source, settings_destination,
                   settings_update_pending);
        end
    endtask

    task automatic service_ready_to_run;
        integer attempt;
        begin : wait_target
            for (attempt = 0; attempt < 160; attempt = attempt + 1) begin
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

    initial begin
        #17.25;
        pll_ready = 1'b1;
        repeat (5) @(posedge clk_source);
        repeat (4) @(posedge clk_destination);
        #1ps;
        if (settings_source !== DEFAULT_SETTINGS ||
            settings_destination !== DEFAULT_SETTINGS ||
            settings_update_pending || reset_n)
            $fatal(1, "cold default state mismatch");

        status_setup_done = 1'b1;
        service_ready_to_run();

        // Pocket writes persistent/write-only values even when they still equal
        // package defaults. Those same-value writes require no synthetic CDC
        // transfer and must never deadlock cold boot.
        host_write(32'h0000_0100, 32'd0);
        host_write(32'h0000_0110, 32'd0);
        host_write(32'h0000_0200, 32'd1);
        host_write(32'h0000_0204, 32'd0);
        host_write(32'h0000_0208, 32'd0);
        host_write(32'h0000_020c, 32'd0);
        host_write(32'h0000_0210, 32'd0);
        host_write(32'h0000_0214, 32'd0);
        host_write(32'h0000_0300, 32'd1);
        if (settings_update_pending)
            $fatal(1, "same-value default writes launched a false transfer");
        expect_command_done(16'h0011);
        if (!reset_n || reset_release_count != 1)
            $fatal(1, "default Reset Exit did not release exactly once");

        // The disabled Video/Sound section rows are schema-complete actions,
        // but their aligned addresses are intentionally outside every command
        // and settings decode. Even an unexpected write must be inert.
        no_op_settings_snapshot = settings_source;
        host_write(32'h0000_0058, 32'd0);
        host_write(32'h0000_005c, 32'd0);
        repeat (8) @(posedge clk_source);
        #1ps;
        if (!reset_n || reset_release_count != 1 ||
            settings_source !== no_op_settings_snapshot ||
            settings_destination !== no_op_settings_snapshot ||
            settings_update_pending)
            $fatal(1,
                   "disabled heading write had side effects reset=%b releases=%0d source=%04x destination=%04x pending=%b",
                   reset_n, reset_release_count, settings_source,
                   settings_destination, settings_update_pending);

        // Runtime menu changes cross the CDC but never retract reset or Running.
        host_write(32'h0000_0110, 32'd1);
        repeat (3) @(posedge clk_source);
        if (!reset_n)
            $fatal(1, "runtime settings update stalled the running console");
        wait_settings(settings_source);
        if (!reset_n)
            $fatal(1, "runtime settings completion retracted reset");

        // Host Reset Enter is immediate. A settings write immediately before
        // Reset Exit holds the command BUSY until destination capture + ack.
        expect_command_done(16'h0010);
        if (reset_n)
            $fatal(1, "Reset Enter did not stop execution");
        host_write(32'h0000_0100, 32'd2);
        start_host_command(16'h0011);
        repeat (2) @(posedge clk_source);
        expect_reset_exit_busy();
        wait_host_done();
        if (!reset_n || settings_destination !== settings_source)
            $fatal(1, "pre-Reset-Exit settings were not fenced");

        // A write on the command's ST_PARSE cycle is caught by the explicit
        // source-write guard before update_pending can reflect the register NBA.
        expect_command_done(16'h0010);
        start_host_command(16'h0011);
        host_write(32'h0000_0214, 32'd2);
        expect_reset_exit_busy();
        wait_host_done();
        if (!reset_n || settings_destination !== settings_source)
            $fatal(1, "same-cycle Reset Exit/settings write raced the fence");

        // A later write while Reset Exit is already waiting supersedes the
        // in-flight snapshot. Release is legal only after the final payload.
        expect_command_done(16'h0010);
        host_write(32'h0000_0204, 32'd1);
        start_host_command(16'h0011);
        host_write(32'h0000_0208, 32'd1);
        host_write(32'h0000_0204, 32'd2);
        host_write(32'h0000_0208, 32'd2);
        host_write(32'h0000_0300, 32'd0);
        expect_reset_exit_busy();
        wait_host_done();
        if (!reset_n || settings_destination !== settings_source ||
            settings_destination[8:7] !== 2'd2 ||
            settings_destination[6:5] !== 2'd2 ||
            settings_destination[0] !== 1'b0)
            $fatal(1, "coalesced post-command settings did not win");

        // A new title invalidates 0140. Its next Reset Exit needs both a fresh
        // lifecycle acknowledgement and any newly loaded persistent settings.
        expect_command_done(16'h0010);
        status_setup_done = 1'b0;
        repeat (3) @(posedge clk_source);
        if (ready_to_run_complete)
            $fatal(1, "title reload retained stale 0140 acknowledgement");
        status_setup_done = 1'b1;
        service_ready_to_run();
        host_write(32'h0000_0200, 32'd0);
        start_host_command(16'h0011);
        expect_reset_exit_busy();
        wait_host_done();
        if (!reset_n || settings_destination !== settings_source)
            $fatal(1, "title reload escaped the settings fence");

        // Host Reset Enter/Exit with no intervening setting change remains a
        // fast no-transfer path and proves the barrier cannot self-deadlock.
        expect_command_done(16'h0010);
        expect_command_done(16'h0011);
        if (!reset_n || reset_release_count != 6)
            $fatal(1, "unchanged host reset cycle failed releases=%0d",
                   reset_release_count);

        $display("PASS APF settings boot barrier releases=%0d final=%04x",
                 reset_release_count, settings_destination);
        $finish;
    end
endmodule
