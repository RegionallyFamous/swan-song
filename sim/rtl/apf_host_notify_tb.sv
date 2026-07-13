`timescale 1ns/1ps

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
    assign q_a = 32'h0000_0000;
    assign q_b = 32'h0000_0000;
endmodule

module apf_host_notify_tb;
    reg         clk = 1'b0;
    reg         bridge_endian_little = 1'b0;
    reg  [31:0] bridge_addr = 32'h0000_0000;
    reg         bridge_rd = 1'b0;
    wire [31:0] bridge_rd_data;
    reg         bridge_wr = 1'b0;
    reg  [31:0] bridge_wr_data = 32'h0000_0000;

    wire        osnotify_inmenu;
    wire        osnotify_docked;
    wire [7:0]  osnotify_displaymode_id;
    wire        osnotify_displaymode_grayscale;
    integer     grayscale_ack_phase = 0;
    wire        displaymode_grayscale_ack =
        grayscale_ack_phase == 1 ? 1'b1 :
        grayscale_ack_phase == 2 ? 1'b0 : 1'bz;

    reg  [31:0] readback;

    always #5 clk = ~clk;

    core_bridge_cmd dut (
        .clk(clk),
        .bridge_endian_little(bridge_endian_little),
        .bridge_addr(bridge_addr),
        .bridge_rd(bridge_rd),
        .bridge_rd_data(bridge_rd_data),
        .bridge_wr(bridge_wr),
        .bridge_wr_data(bridge_wr_data),

        .status_boot_done(1'b1),
        .status_setup_done(1'b1),
        .status_running(1'b0),

        .dataslot_requestread_ack(1'b0),
        .dataslot_requestread_result(2'd0),
        .dataslot_requestwrite_ack(1'b0),
        .dataslot_requestwrite_result(2'd0),

        .savestate_supported(1'b0),
        .savestate_addr(32'h0000_0000),
        .savestate_size(32'h0000_0000),
        .savestate_maxloadsize(32'h0000_0000),
        .savestate_start_ack(1'b0),
        .savestate_start_busy(1'b0),
        .savestate_start_ok(1'b0),
        .savestate_start_err(1'b0),
        .savestate_load_ack(1'b0),
        .savestate_load_busy(1'b0),
        .savestate_load_ok(1'b0),
        .savestate_load_err(1'b0),

        .target_dataslot_read(1'b0),
        .target_dataslot_write(1'b0),
        .target_dataslot_id(16'h0000),
        .target_dataslot_slotoffset(32'h0000_0000),
        .target_dataslot_bridgeaddr(32'h0000_0000),
        .target_dataslot_length(32'h0000_0000),

        .datatable_addr(10'h000),
        .datatable_wren(1'b0),
        .datatable_data(32'h0000_0000),

        .osnotify_inmenu(osnotify_inmenu),
        .osnotify_docked(osnotify_docked),
        .osnotify_displaymode_id(osnotify_displaymode_id),
        .osnotify_displaymode_grayscale(osnotify_displaymode_grayscale),
        .displaymode_grayscale_ack(displaymode_grayscale_ack)
    );

    task automatic host_write(input [31:0] address, input [31:0] data);
        begin
            @(negedge clk);
            bridge_addr = address;
            bridge_wr_data = data;
            bridge_wr = 1'b1;
            @(negedge clk);
            bridge_wr = 1'b0;
        end
    endtask

    task automatic host_read(input [31:0] address, output [31:0] data);
        begin
            @(negedge clk);
            bridge_addr = address;
            bridge_rd = 1'b1;
            @(negedge clk);
            data = bridge_rd_data;
            bridge_rd = 1'b0;
        end
    endtask

    task automatic issue_command(input [15:0] command, input [31:0] param_data);
        begin
            host_write(32'hF800_0020, param_data);
            host_write(32'hF800_0000, {16'h434D, command});
            repeat (4) @(posedge clk);
        end
    endtask

    task automatic expect_ok;
        begin
            host_read(32'hF800_0000, readback);
            if (readback !== 32'h4F4B_0000) begin
                $fatal(1,
                       "expected OK status, got %08x hstate=%0d param=%08x ack=%b",
                       readback, dut.hstate, dut.host_20,
                       displaymode_grayscale_ack);
            end
        end
    endtask

    initial begin
        repeat (4) @(posedge clk);

        if (osnotify_docked !== 1'b0) begin
            $fatal(1, "docked state did not initialize clear");
        end

        // Pocket sends B1 on every startup even when core.json declares no
        // cartridge adapter. Its play/power/adapter fields must be accepted as
        // an intentional no-op, without perturbing any other OS notification.
        issue_command(16'h00B1, 32'h0101_0003);
        expect_ok();
        if (osnotify_inmenu !== 1'b0 || osnotify_docked !== 1'b0 ||
            osnotify_displaymode_id !== 8'h00 ||
            osnotify_displaymode_grayscale !== 1'b0) begin
            $fatal(1, "B1 changed unrelated OS-notify state");
        end

        issue_command(16'h00B2, 32'h0000_0001);
        expect_ok();
        if (osnotify_docked !== 1'b1) begin
            $fatal(1, "B2 did not store docked=1");
        end

        issue_command(16'h00B2, 32'h0000_0000);
        expect_ok();
        if (osnotify_docked !== 1'b0) begin
            $fatal(1, "B2 did not store docked=0");
        end

        host_write(32'hF800_0020, 32'h0000_2001);
        host_write(32'hF800_0000, 32'h434D_00B8);
        repeat (6) @(posedge clk);
        if (osnotify_displaymode_id !== 8'h20) begin
            $fatal(1, "B8 did not store display mode ID 20");
        end
        if (osnotify_displaymode_grayscale !== 1'b1) begin
            $fatal(1, "B8 did not store grayscale request");
        end
        host_read(32'hF800_0000, readback);
        if (readback !== 32'h4255_00B8) begin
            $fatal(1, "B8 did not remain busy without grayscale ack: %08x", readback);
        end
        host_read(32'hF800_0040, readback);
        if (readback !== 32'h0000_0000) begin
            $fatal(1, "unsupported grayscale request was falsely affirmed: %08x", readback);
        end

        repeat (5) @(posedge clk);
        host_read(32'hF800_0000, readback);
        if (readback !== 32'h4255_00B8) begin
            $fatal(1, "B8 stopped waiting before delayed grayscale ack: %08x", readback);
        end

        @(negedge clk);
        grayscale_ack_phase = 1;
        repeat (3) @(posedge clk);
        expect_ok();
        host_read(32'hF800_0040, readback);
        if (readback !== 32'h0000_444D) begin
            $fatal(1, "delayed grayscale implementation ack was not affirmed: %08x", readback);
        end

        host_write(32'hF800_0020, 32'h0000_3000);
        host_write(32'hF800_0000, 32'h434D_00B8);
        repeat (5) @(posedge clk);
        host_read(32'hF800_0000, readback);
        if (readback !== 32'h4255_00B8) begin
            $fatal(1, "B8 color mode did not wait for grayscale disable: %08x", readback);
        end
        @(negedge clk);
        grayscale_ack_phase = 2;
        repeat (5) @(posedge clk);
        expect_ok();
        if (osnotify_displaymode_id !== 8'h30) begin
            $fatal(1, "B8 did not store display mode ID 30");
        end
        if (osnotify_displaymode_grayscale !== 1'b0) begin
            $fatal(1, "B8 did not clear grayscale request");
        end
        host_read(32'hF800_0040, readback);
        if (readback !== 32'h0000_0000) begin
            $fatal(1, "non-grayscale mode returned grayscale affirmation: %08x", readback);
        end

        issue_command(16'h00B7, 32'h0000_0000);
        host_read(32'hF800_0000, readback);
        if (readback !== 32'h4F4B_FFFF) begin
            $fatal(1, "unknown command contract changed: %08x", readback);
        end

        $display("PASS APF host notify B1=no-op B2=docked B8=busy-until-applied grayscale state");
        $finish;
    end
endmodule
