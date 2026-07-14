`timescale 1ns/1ps

// Focused stand-ins for the two APF primitives instantiated by
// core_bridge_cmd.  The lifecycle contract under test does not depend on CDC
// latency or data-table storage contents.
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

module apf_boot_lifecycle_tb;
    localparam [31:0] HOST_STATUS = 32'hF800_0000;
    localparam [31:0] HOST_PARAM0 = 32'hF800_0020;
    localparam [31:0] HOST_PARAM1 = 32'hF800_0024;
    localparam [31:0] HOST_PARAM2 = 32'hF800_0028;
    localparam [31:0] TARGET_STATUS = 32'hF800_1000;

    reg         clk = 1'b0;
    reg         bridge_endian_little = 1'b0;
    reg  [31:0] bridge_addr = 32'h0000_0000;
    reg         bridge_rd = 1'b0;
    wire [31:0] bridge_rd_data;
    reg         bridge_wr = 1'b0;
    reg  [31:0] bridge_wr_data = 32'h0000_0000;

    reg status_boot_done = 1'b0;
    reg status_setup_done = 1'b0;
    reg status_running = 1'b0;
    wire reset_n;
    wire ready_to_run_complete;

    wire        dataslot_requestread;
    wire [15:0] dataslot_requestread_id;
    reg         dataslot_requestread_ack = 1'b0;
    reg  [1:0]  dataslot_requestread_result = 2'd0;

    wire        dataslot_requestwrite;
    wire [15:0] dataslot_requestwrite_id;
    wire [47:0] dataslot_requestwrite_size;
    reg         dataslot_requestwrite_ack = 1'b0;
    reg  [1:0]  dataslot_requestwrite_result = 2'd0;

    wire        dataslot_update;
    wire [15:0] dataslot_update_id;
    wire [31:0] dataslot_update_size;
    wire        dataslot_allcomplete;

    wire [31:0] rtc_epoch_seconds;
    wire [31:0] rtc_date_bcd;
    wire [31:0] rtc_time_bcd;
    wire        rtc_valid;

    wire        target_dataslot_ack;
    wire        target_dataslot_done;
    wire [2:0]  target_dataslot_err;

    reg [31:0] readback;
    integer update_count = 0;
    reg [15:0] last_update_id = 16'h0000;
    reg [31:0] last_update_size = 32'h0000_0000;
    reg previous_dataslot_update = 1'b0;
    integer rtc_valid_rise_count = 0;
    integer rtc_valid_high_cycles = 0;
    reg previous_rtc_valid = 1'b0;

    always #5 clk = ~clk;

    always @(posedge clk) begin
        if (dataslot_update && !previous_dataslot_update) begin
            update_count <= update_count + 1;
            last_update_id <= dataslot_update_id;
            last_update_size <= dataslot_update_size;
        end
        previous_dataslot_update <= dataslot_update;

        if (rtc_valid && !previous_rtc_valid)
            rtc_valid_rise_count <= rtc_valid_rise_count + 1;
        if (rtc_valid)
            rtc_valid_high_cycles <= rtc_valid_high_cycles + 1;
        previous_rtc_valid <= rtc_valid;
    end

    core_bridge_cmd dut (
        .clk(clk),
        .reset_n(reset_n),

        .bridge_endian_little(bridge_endian_little),
        .bridge_addr(bridge_addr),
        .bridge_rd(bridge_rd),
        .bridge_rd_data(bridge_rd_data),
        .bridge_wr(bridge_wr),
        .bridge_wr_data(bridge_wr_data),

        .status_boot_done(status_boot_done),
        .status_setup_done(status_setup_done),
        .status_running(status_running),
        .reset_exit_ready(1'b1),
        .ready_to_run_complete(ready_to_run_complete),

        .dataslot_requestread(dataslot_requestread),
        .dataslot_requestread_id(dataslot_requestread_id),
        .dataslot_requestread_ack(dataslot_requestread_ack),
        .dataslot_requestread_result(dataslot_requestread_result),

        .dataslot_requestwrite(dataslot_requestwrite),
        .dataslot_requestwrite_id(dataslot_requestwrite_id),
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
        .target_dataslot_ack(target_dataslot_ack),
        .target_dataslot_done(target_dataslot_done),
        .target_dataslot_err(target_dataslot_err),
        .target_dataslot_id(16'h0000),
        .target_dataslot_slotoffset(32'h0000_0000),
        .target_dataslot_bridgeaddr(32'h0000_0000),
        .target_dataslot_length(32'h0000_0000),

        .datatable_addr(10'h000),
        .datatable_wren(1'b0),
        .datatable_data(32'h0000_0000),

        .displaymode_grayscale_ack(1'b0)
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

    task automatic start_host_command(input [15:0] command);
        begin
            host_write(HOST_STATUS, {16'h434D, command});
        end
    endtask

    task automatic wait_host_done(output [31:0] status);
        integer attempt;
        begin : wait_block
            status = 32'h0000_0000;
            for (attempt = 0; attempt < 80; attempt = attempt + 1) begin
                host_read(HOST_STATUS, status);
                if (status[31:16] == 16'h4F4B)
                    disable wait_block;
            end
            $fatal(1, "host command timeout: status=%08x hstate=%0d", status, dut.hstate);
        end
    endtask

    task automatic expect_command_result(
        input [15:0] command,
        input [15:0] expected_result
    );
        reg [31:0] status;
        begin
            start_host_command(command);
            wait_host_done(status);
            if (status !== {16'h4F4B, expected_result})
                $fatal(1, "command %04x result=%08x expected=4F4B%04x",
                       command, status, expected_result);
        end
    endtask

    task automatic wait_read_request(input [15:0] expected_id);
        integer cycle;
        begin : wait_block
            for (cycle = 0; cycle < 40; cycle = cycle + 1) begin
                @(posedge clk);
                if (dataslot_requestread) begin
                    if (dataslot_requestread_id !== expected_id)
                        $fatal(1, "0080 slot id=%04x expected=%04x",
                               dataslot_requestread_id, expected_id);
                    disable wait_block;
                end
            end
            $fatal(1, "0080 request was not asserted");
        end
    endtask

    task automatic wait_write_request(
        input [15:0] expected_id,
        input [47:0] expected_size
    );
        integer cycle;
        begin : wait_block
            for (cycle = 0; cycle < 40; cycle = cycle + 1) begin
                @(posedge clk);
                if (dataslot_requestwrite) begin
                    if (dataslot_requestwrite_id !== expected_id ||
                        dataslot_requestwrite_size !== expected_size)
                        $fatal(1,
                               "0082 request id/size=%04x/%012x expected=%04x/%012x",
                               dataslot_requestwrite_id, dataslot_requestwrite_size,
                               expected_id, expected_size);
                    disable wait_block;
                end
            end
            $fatal(1, "0082 request was not asserted");
        end
    endtask

    task automatic expect_host_busy(input [15:0] command);
        begin
            host_read(HOST_STATUS, readback);
            if (readback !== {16'h4255, command})
                $fatal(1, "command %04x did not remain busy: %08x",
                       command, readback);
        end
    endtask

    task automatic service_ready_to_run;
        integer attempt;
        begin : wait_block
            readback = 32'h0000_0000;
            for (attempt = 0; attempt < 80; attempt = attempt + 1) begin
                host_read(TARGET_STATUS, readback);
                if (readback === 32'h636D_0140)
                    disable wait_block;
            end
            $fatal(1, "setup edge did not issue target 0140: %08x tstate=%0d",
                   readback, dut.tstate);
        end

        host_write(TARGET_STATUS, 32'h6275_0140);
        repeat (3) @(posedge clk);
        host_write(TARGET_STATUS, 32'h6F6B_0000);
        repeat (4) @(posedge clk);
        if (dut.tstate !== 4'd0)
            $fatal(1, "target 0140 did not return to idle: tstate=%0d", dut.tstate);
    endtask

    initial begin
        repeat (5) @(posedge clk);

        if (reset_n !== 1'b0 || rtc_valid !== 1'b0)
            $fatal(1, "initial reset/RTC state invalid: reset_n=%b rtc_valid=%b",
                   reset_n, rtc_valid);

        // Official Request Status progression: booting, setup, idle, running.
        expect_command_result(16'h0000, 16'h0001);

        @(negedge clk);
        status_boot_done = 1'b1;
        expect_command_result(16'h0000, 16'h0002);

        @(negedge clk);
        status_setup_done = 1'b1;
        expect_command_result(16'h0000, 16'h0002);
        // Even after internal setup completes, Reset Exit must remain busy and
        // reset asserted until Pocket acknowledges target command 0140.
        start_host_command(16'h0011);
        repeat (4) @(posedge clk);
        expect_host_busy(16'h0011);
        if (reset_n !== 1'b0)
            $fatal(1, "0011 bypassed target 0140 acknowledgement");
        service_ready_to_run();
        wait_host_done(readback);
        if (readback !== 32'h4F4B_0000 || reset_n !== 1'b1)
            $fatal(1, "0011 did not complete after target 0140: %08x", readback);
        expect_command_result(16'h0000, 16'h0003);

        // core_top keeps setup_done at PLL lock while running follows reset_n.
        // Running must therefore take precedence when both inputs are high.
        @(negedge clk);
        status_running = 1'b1;
        expect_command_result(16'h0000, 16'h0004);

        // Running has priority while persistent startup_complete remains high.
        expect_command_result(16'h0000, 16'h0004);

        // A held setup level must not emit a second 0140 without another edge.
        repeat (8) @(posedge clk);
        if (dut.tstate !== 4'd0)
            $fatal(1, "target 0140 retriggered without a setup edge");

        // A new title's falling startup_complete must invalidate the previous
        // target acknowledgement before the next rising edge reissues 0140.
        @(negedge clk);
        status_setup_done = 1'b0;
        repeat (2) @(posedge clk);
        if (ready_to_run_complete !== 1'b0)
            $fatal(1, "new setup retained stale target 0140 acknowledgement");
        @(negedge clk);
        status_setup_done = 1'b1;
        service_ready_to_run();

        expect_command_result(16'h0010, 16'h0000);
        if (reset_n !== 1'b0)
            $fatal(1, "0010 Reset Enter did not clear reset_n");
        expect_command_result(16'h0011, 16'h0000);
        if (reset_n !== 1'b1)
            $fatal(1, "0011 Reset Exit did not set reset_n");

        // 0080: delayed success, then delayed retry/check-later result.
        host_write(HOST_PARAM0, 32'h0000_1234);
        start_host_command(16'h0080);
        wait_read_request(16'h1234);
        repeat (7) @(posedge clk);
        expect_host_busy(16'h0080);
        @(negedge clk);
        dataslot_requestread_result = 2'd0;
        dataslot_requestread_ack = 1'b1;
        wait_host_done(readback);
        if (readback !== 32'h4F4B_0000)
            $fatal(1, "0080 success result mismatch: %08x", readback);
        @(negedge clk);
        dataslot_requestread_ack = 1'b0;
        dataslot_requestread_result = 2'd0;
        repeat (3) @(posedge clk);

        host_write(HOST_PARAM0, 32'h0000_5678);
        start_host_command(16'h0080);
        wait_read_request(16'h5678);
        repeat (5) @(posedge clk);
        expect_host_busy(16'h0080);
        @(negedge clk);
        dataslot_requestread_result = 2'd2;
        dataslot_requestread_ack = 1'b1;
        wait_host_done(readback);
        if (readback !== 32'h4F4B_0002)
            $fatal(1, "0080 check-later result mismatch: %08x", readback);
        @(negedge clk);
        dataslot_requestread_ack = 1'b0;
        dataslot_requestread_result = 2'd0;
        repeat (3) @(posedge clk);

        host_write(HOST_PARAM0, 32'h0000_BEEF);
        start_host_command(16'h0080);
        wait_read_request(16'hBEEF);
        @(negedge clk);
        dataslot_requestread_result = 2'd1;
        dataslot_requestread_ack = 1'b1;
        wait_host_done(readback);
        if (readback !== 32'h4F4B_0001)
            $fatal(1, "0080 not-allowed result mismatch: %08x", readback);
        @(negedge clk);
        dataslot_requestread_ack = 1'b0;
        dataslot_requestread_result = 2'd0;
        repeat (3) @(posedge clk);

        // 0082: delayed success and retry/check-later, including exact size.
        host_write(HOST_PARAM0, 32'h1234_9ABC);
        host_write(HOST_PARAM1, 32'h0012_3456);
        start_host_command(16'h0082);
        wait_write_request(16'h9ABC, 48'h1234_0012_3456);
        repeat (6) @(posedge clk);
        expect_host_busy(16'h0082);
        @(negedge clk);
        dataslot_requestwrite_result = 2'd0;
        dataslot_requestwrite_ack = 1'b1;
        wait_host_done(readback);
        if (readback !== 32'h4F4B_0000)
            $fatal(1, "0082 success result mismatch: %08x", readback);
        @(negedge clk);
        dataslot_requestwrite_ack = 1'b0;
        dataslot_requestwrite_result = 2'd0;
        repeat (3) @(posedge clk);

        host_write(HOST_PARAM0, 32'h0000_DEF0);
        host_write(HOST_PARAM1, 32'h89AB_CDEF);
        start_host_command(16'h0082);
        wait_write_request(16'hDEF0, 32'h89AB_CDEF);
        repeat (4) @(posedge clk);
        expect_host_busy(16'h0082);
        @(negedge clk);
        dataslot_requestwrite_result = 2'd2;
        dataslot_requestwrite_ack = 1'b1;
        wait_host_done(readback);
        if (readback !== 32'h4F4B_0002)
            $fatal(1, "0082 check-later result mismatch: %08x", readback);
        @(negedge clk);
        dataslot_requestwrite_ack = 1'b0;
        dataslot_requestwrite_result = 2'd0;
        repeat (3) @(posedge clk);

        // 008A creates one update event carrying the current ID/size.
        host_write(HOST_PARAM0, 32'h0000_00A5);
        host_write(HOST_PARAM1, 32'h0102_0304);
        expect_command_result(16'h008A, 16'h0000);
        repeat (3) @(posedge clk);
        if (update_count !== 1 || last_update_id !== 16'h00A5 ||
            last_update_size !== 32'h0102_0304)
            $fatal(1, "008A count/id/size=%0d/%04x/%08x",
                   update_count, last_update_id, last_update_size);

        expect_command_result(16'h008F, 16'h0000);
        if (dataslot_allcomplete !== 1'b1)
            $fatal(1, "008F did not assert dataslot_allcomplete");

        // A later slot request begins a new access epoch and clears complete.
        host_write(HOST_PARAM0, 32'h0000_0001);
        start_host_command(16'h0080);
        wait_read_request(16'h0001);
        if (dataslot_allcomplete !== 1'b0)
            $fatal(1, "0080 did not clear dataslot_allcomplete");
        @(negedge clk);
        dataslot_requestread_result = 2'd0;
        dataslot_requestread_ack = 1'b1;
        wait_host_done(readback);
        @(negedge clk);
        dataslot_requestread_ack = 1'b0;
        dataslot_requestread_result = 2'd0;
        repeat (3) @(posedge clk);

        // 0090 carries epoch, date, and time.  rtc_valid is required here as a
        // one-cycle notification so a future RTC update can create a new edge.
        host_write(HOST_PARAM0, 32'h65A1_2345);
        host_write(HOST_PARAM1, 32'h2026_0713);
        host_write(HOST_PARAM2, 32'h0321_5948);
        expect_command_result(16'h0090, 16'h0000);
        if (rtc_epoch_seconds !== 32'h65A1_2345 ||
            rtc_date_bcd !== 32'h2026_0713 ||
            rtc_time_bcd !== 32'h0321_5948)
            $fatal(1, "0090 words=%08x/%08x/%08x",
                   rtc_epoch_seconds, rtc_date_bcd, rtc_time_bcd);
        if (rtc_valid_rise_count !== 1)
            $fatal(1, "0090 rtc_valid rise count=%0d expected=1",
                   rtc_valid_rise_count);

        repeat (3) @(posedge clk);
        if (rtc_valid !== 1'b0 || rtc_valid_high_cycles !== 1)
            $fatal(1,
                   "0090 rtc_valid must pulse once: level=%b high_cycles=%0d",
                   rtc_valid, rtc_valid_high_cycles);

        $display("PASS APF boot lifecycle status/reset/slots/RTC/0140");
        $finish;
    end
endmodule
