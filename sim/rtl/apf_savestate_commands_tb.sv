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

module apf_savestate_commands_tb;
    localparam [31:0] SAVESTATE_ADDR = 32'h4000_0000;
    localparam [31:0] SAVESTATE_SIZE = 32'h0009_0200;
    localparam [31:0] SAVESTATE_MAXLOAD = 32'h0009_1200;

    reg         clk = 1'b0;
    reg         bridge_endian_little = 1'b0;
    reg  [31:0] bridge_addr = 32'h0000_0000;
    reg         bridge_rd = 1'b0;
    wire [31:0] bridge_rd_data;
    reg         bridge_wr = 1'b0;
    reg  [31:0] bridge_wr_data = 32'h0000_0000;

    reg savestate_supported = 1'b1;
    reg savestate_start_ack = 1'b0;
    reg savestate_start_busy = 1'b0;
    reg savestate_start_ok = 1'b0;
    reg savestate_start_err = 1'b0;
    reg savestate_load_ack = 1'b0;
    reg savestate_load_busy = 1'b0;
    reg savestate_load_ok = 1'b0;
    reg savestate_load_err = 1'b0;

    wire savestate_start;
    wire savestate_load;
    reg [31:0] readback;

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

        .savestate_supported(savestate_supported),
        .savestate_addr(SAVESTATE_ADDR),
        .savestate_size(SAVESTATE_SIZE),
        .savestate_maxloadsize(SAVESTATE_MAXLOAD),
        .savestate_start(savestate_start),
        .savestate_start_ack(savestate_start_ack),
        .savestate_start_busy(savestate_start_busy),
        .savestate_start_ok(savestate_start_ok),
        .savestate_start_err(savestate_start_err),
        .savestate_load(savestate_load),
        .savestate_load_ack(savestate_load_ack),
        .savestate_load_busy(savestate_load_busy),
        .savestate_load_ok(savestate_load_ok),
        .savestate_load_err(savestate_load_err),

        .displaymode_grayscale_ack(1'b0),
        .target_dataslot_read(1'b0),
        .target_dataslot_write(1'b0),
        .target_dataslot_id(16'h0000),
        .target_dataslot_slotoffset(32'h0000_0000),
        .target_dataslot_bridgeaddr(32'h0000_0000),
        .target_dataslot_length(32'h0000_0000),
        .datatable_addr(10'h000),
        .datatable_wren(1'b0),
        .datatable_data(32'h0000_0000)
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

    task automatic issue_command(input [15:0] command, input request);
        begin
            host_write(32'hF800_0020, {31'h0000_0000, request});
            host_write(32'hF800_0000, {16'h434D, command});
        end
    endtask

    task automatic expect_status(input [15:0] code);
        begin
            host_read(32'hF800_0000, readback);
            if (readback !== {16'h4F4B, code}) begin
                $fatal(1, "expected status OK/%04x, got %08x", code, readback);
            end
        end
    endtask

    task automatic expect_query_fields(input [15:0] command);
        begin
            host_read(32'hF800_0040, readback);
            if (readback !== {31'h0000_0000, savestate_supported}) begin
                $fatal(1, "command %04x support field mismatch %08x", command, readback);
            end
            host_read(32'hF800_0044, readback);
            if (readback !== SAVESTATE_ADDR) begin
                $fatal(1, "command %04x address mismatch %08x", command, readback);
            end
            host_read(32'hF800_0048, readback);
            if (command == 16'h00A0 && readback !== SAVESTATE_SIZE) begin
                $fatal(1, "A0 size mismatch %08x", readback);
            end
            if (command == 16'h00A4 && readback !== SAVESTATE_MAXLOAD) begin
                $fatal(1, "A4 maxload mismatch %08x", readback);
            end
        end
    endtask

    task automatic set_result_flags(
        input [15:0] command,
        input busy,
        input done_ok,
        input done_err
    );
        begin
            if (command == 16'h00A0) begin
                savestate_start_busy = busy;
                savestate_start_ok = done_ok;
                savestate_start_err = done_err;
            end else begin
                savestate_load_busy = busy;
                savestate_load_ok = done_ok;
                savestate_load_err = done_err;
            end
        end
    endtask

    task automatic check_query_result(
        input [15:0] command,
        input busy,
        input done_ok,
        input done_err,
        input [15:0] expected_code
    );
        begin
            set_result_flags(command, busy, done_ok, done_err);
            issue_command(command, 1'b0);
            repeat (4) @(posedge clk);
            expect_status(expected_code);
            if (savestate_start !== 1'b0 || savestate_load !== 1'b0) begin
                $fatal(1, "query command %04x asserted an operation request", command);
            end
        end
    endtask

    initial begin
        repeat (4) @(posedge clk);
        if (savestate_start !== 1'b0 || savestate_load !== 1'b0) begin
            $fatal(1, "savestate requests did not initialize deasserted");
        end

        // A0 query: supported flag, address, exact state size, and idle result.
        check_query_result(16'h00A0, 1'b0, 1'b0, 1'b0, 16'h0000);
        expect_query_fields(16'h00A0);

        // Result precedence must be error > done > busy > idle.
        check_query_result(16'h00A0, 1'b1, 1'b0, 1'b0, 16'h0001);
        check_query_result(16'h00A0, 1'b1, 1'b1, 1'b0, 16'h0002);
        check_query_result(16'h00A0, 1'b1, 1'b1, 1'b1, 16'h0003);

        // A0 start request remains asserted and command remains busy until ack.
        set_result_flags(16'h00A0, 1'b1, 1'b0, 1'b0);
        issue_command(16'h00A0, 1'b1);
        repeat (7) @(posedge clk);
        if (savestate_start !== 1'b1 || savestate_load !== 1'b0) begin
            $fatal(1, "A0 request was not held exclusively before ack");
        end
        host_read(32'hF800_0000, readback);
        if (readback !== 32'h4255_00A0) begin
            $fatal(1, "A0 command did not remain busy before ack: %08x", readback);
        end
        repeat (5) @(posedge clk);
        if (savestate_start !== 1'b1) begin
            $fatal(1, "A0 request deasserted without ack");
        end
        @(negedge clk);
        savestate_start_ack = 1'b1;
        repeat (3) @(posedge clk);
        expect_status(16'h0001);
        savestate_start_ack = 1'b0;
        repeat (2) @(posedge clk);
        if (savestate_start !== 1'b0) begin
            $fatal(1, "A0 request did not deassert after completion");
        end
        expect_query_fields(16'h00A0);

        // A4 query mirrors A0 but returns maximum load size.
        set_result_flags(16'h00A0, 1'b0, 1'b0, 1'b0);
        check_query_result(16'h00A4, 1'b0, 1'b0, 1'b0, 16'h0000);
        expect_query_fields(16'h00A4);
        check_query_result(16'h00A4, 1'b1, 1'b0, 1'b0, 16'h0001);
        check_query_result(16'h00A4, 1'b1, 1'b1, 1'b0, 16'h0002);
        check_query_result(16'h00A4, 1'b1, 1'b1, 1'b1, 16'h0003);

        // A4 load request also holds until ack and reports sampled error state.
        set_result_flags(16'h00A4, 1'b0, 1'b0, 1'b1);
        issue_command(16'h00A4, 1'b1);
        repeat (7) @(posedge clk);
        if (savestate_load !== 1'b1 || savestate_start !== 1'b0) begin
            $fatal(1, "A4 request was not held exclusively before ack");
        end
        host_read(32'hF800_0000, readback);
        if (readback !== 32'h4255_00A4) begin
            $fatal(1, "A4 command did not remain busy before ack: %08x", readback);
        end
        repeat (5) @(posedge clk);
        if (savestate_load !== 1'b1) begin
            $fatal(1, "A4 request deasserted without ack");
        end
        @(negedge clk);
        savestate_load_ack = 1'b1;
        repeat (3) @(posedge clk);
        expect_status(16'h0003);
        savestate_load_ack = 1'b0;
        repeat (2) @(posedge clk);
        if (savestate_load !== 1'b0) begin
            $fatal(1, "A4 request did not deassert after completion");
        end
        expect_query_fields(16'h00A4);

        // Unsupported is exposed in the response field and fails closed even
        // if a hostile host skips the query and sets Request Start/Load. Stale
        // controller flags must not leak a busy/done/error result either.
        savestate_supported = 1'b0;
        set_result_flags(16'h00A0, 1'b1, 1'b1, 1'b1);
        issue_command(16'h00A0, 1'b1);
        repeat (7) @(posedge clk);
        expect_status(16'h0000);
        if (savestate_start !== 1'b0 || savestate_load !== 1'b0) begin
            $fatal(1, "unsupported A0 request reached the controller");
        end
        expect_query_fields(16'h00A0);

        set_result_flags(16'h00A4, 1'b1, 1'b1, 1'b1);
        issue_command(16'h00A4, 1'b1);
        repeat (7) @(posedge clk);
        expect_status(16'h0000);
        if (savestate_start !== 1'b0 || savestate_load !== 1'b0) begin
            $fatal(1, "unsupported A4 request reached the controller");
        end
        expect_query_fields(16'h00A4);

        set_result_flags(16'h00A4, 1'b0, 1'b0, 1'b0);
        issue_command(16'h00A4, 1'b0);
        repeat (4) @(posedge clk);
        expect_status(16'h0000);
        expect_query_fields(16'h00A4);

        $display(
            "PASS APF savestate A0/A4 query-fields precedence=err>ok>busy requests=hold-until-ack+unsupported-fail-closed"
        );
        $finish;
    end
endmodule
