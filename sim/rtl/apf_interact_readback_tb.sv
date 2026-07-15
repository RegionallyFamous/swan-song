`timescale 1ns/1ps
`default_nettype none

module apf_interact_readback_tb;
    reg [31:0] bridge_addr = 32'd0;
    reg [12:0] settings_source = 13'd0;
    wire hit;
    wire [31:0] data;

    integer settings_word;
    integer checked_reads = 0;
    integer checked_misses = 0;

    apf_interact_readback dut (
        .bridge_addr(bridge_addr),
        .settings_source(settings_source),
        .hit(hit),
        .data(data)
    );

    task automatic expect_read(
        input [31:0] address,
        input [31:0] expected
    );
        begin
            bridge_addr = address;
            #1ps;
            if (hit !== 1'b1 || data !== expected) begin
                $fatal(
                    1,
                    "interact read mismatch settings=%04x address=%08x hit=%b expected=%08x actual=%08x",
                    settings_source,
                    address,
                    hit,
                    expected,
                    data
                );
            end
            checked_reads = checked_reads + 1;
        end
    endtask

    task automatic expect_miss(input [31:0] address);
        begin
            bridge_addr = address;
            #1ps;
            if (hit !== 1'b0 || data !== 32'd0) begin
                $fatal(
                    1,
                    "interact alias unexpectedly decoded address=%08x hit=%b data=%08x",
                    address,
                    hit,
                    data
                );
            end
            checked_misses = checked_misses + 1;
        end
    endtask

    initial begin
        // Exhaust every possible source image. This includes invalid legacy
        // two-bit encodings, proving readback is an exact view of the stored
        // request while core_top remains responsible for write-time clamps.
        for (settings_word = 0; settings_word < 8192;
             settings_word = settings_word + 1) begin
            settings_source = settings_word[12:0];
            expect_read(32'h00000100, {30'd0, settings_source[12:11]});
            expect_read(32'h00000110, {31'd0, settings_source[10]});
            expect_read(32'h00000200, {31'd0, settings_source[9]});
            expect_read(32'h00000204, {30'd0, settings_source[8:7]});
            expect_read(32'h00000208, {30'd0, settings_source[6:5]});
            expect_read(32'h0000020c, {31'd0, settings_source[2]});
            expect_read(32'h00000210, {31'd0, settings_source[1]});
            expect_read(32'h00000214, {30'd0, settings_source[4:3]});
            expect_read(32'h00000300, {31'd0, settings_source[0]});
        end

        // Exact decode is part of the bridge ownership contract: neither a
        // nearby byte nor a broad 0x2... peripheral address is claimed.
        settings_source = 13'h1fff;
        expect_miss(32'h00000000);
        expect_miss(32'h000000ff);
        expect_miss(32'h00000101);
        expect_miss(32'h0000010c);
        expect_miss(32'h00000111);
        expect_miss(32'h00000201);
        expect_miss(32'h0000020d);
        expect_miss(32'h00000215);
        expect_miss(32'h00000301);
        expect_miss(32'h20000000);
        expect_miss(32'hf8000000);

        if (checked_reads != 8192 * 9 || checked_misses != 11) begin
            $fatal(
                1,
                "interact coverage mismatch reads=%0d misses=%0d",
                checked_reads,
                checked_misses
            );
        end

        $display(
            "PASS APF interact readback settings=8192 reads=%0d misses=%0d",
            checked_reads,
            checked_misses
        );
        $finish;
    end
endmodule

`default_nettype wire
