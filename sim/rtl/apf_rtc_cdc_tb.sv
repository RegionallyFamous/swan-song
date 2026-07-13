`timescale 1ns/1ps

module apf_rtc_cdc_tb;
    localparam integer PAYLOAD_COUNT = 6;
    localparam [31:0] REJECTED_PAYLOAD = 32'hBAD0_C0DE;

    reg reset_n = 1'b0;
    reg clk_74a = 1'b0;
    reg clk_sys = 1'b0;
    reg [31:0] rtc_epoch_src = 32'h0000_0000;
    reg rtc_valid_src = 1'b0;

    wire rtc_busy_src;
    wire rtc_rejected_src;
    wire [31:0] rtc_epoch_dst;
    wire rtc_valid_dst;

    reg [31:0] expected [0:PAYLOAD_COUNT-1];
    integer expected_count = 0;
    integer delivered_count = 0;
    integer rejected_count = 0;
    reg previous_dst_valid = 1'b0;

    always #3.5 clk_74a = ~clk_74a;
    always #5.5 clk_sys = ~clk_sys;

    apf_rtc_cdc dut (
        .reset_n(reset_n),
        .clk_74a(clk_74a),
        .rtc_epoch_src(rtc_epoch_src),
        .rtc_valid_src(rtc_valid_src),
        .rtc_busy_src(rtc_busy_src),
        .rtc_rejected_src(rtc_rejected_src),
        .clk_sys(clk_sys),
        .rtc_epoch_dst(rtc_epoch_dst),
        .rtc_valid_dst(rtc_valid_dst)
    );

    always @(posedge clk_sys) begin
        #1ps;
        if (reset_n) begin
            if (rtc_valid_dst && previous_dst_valid) begin
                $fatal(1, "destination valid was not a one-cycle pulse");
            end
            if (rtc_valid_dst) begin
                if (delivered_count >= expected_count) begin
                    $fatal(1, "duplicate or unsolicited destination event");
                end
                if (rtc_epoch_dst !== expected[delivered_count]) begin
                    $fatal(
                        1,
                        "torn/out-of-order payload index=%0d expected=%08x actual=%08x",
                        delivered_count,
                        expected[delivered_count],
                        rtc_epoch_dst
                    );
                end
                delivered_count = delivered_count + 1;
            end
            previous_dst_valid = rtc_valid_dst;
        end else begin
            previous_dst_valid = 1'b0;
        end
    end

    always @(posedge clk_74a) begin
        #1ps;
        if (reset_n && rtc_rejected_src) begin
            rejected_count = rejected_count + 1;
        end
    end

    task automatic send_accepted(input [31:0] payload);
        begin
            @(negedge clk_74a);
            while (rtc_busy_src) begin
                @(negedge clk_74a);
            end
            expected[expected_count] = payload;
            expected_count = expected_count + 1;
            rtc_epoch_src = payload;
            rtc_valid_src = 1'b1;
            @(negedge clk_74a);
            rtc_valid_src = 1'b0;
            // Deliberately disturb the external bus while the internal held
            // payload is in flight; the destination must still see `payload`.
            rtc_epoch_src = ~payload;
            #1ps;
            if (!rtc_busy_src) begin
                $fatal(1, "accepted payload did not assert source busy");
            end
        end
    endtask

    task automatic send_rejected_while_busy(input [31:0] payload);
        begin
            if (!rtc_busy_src) begin
                $fatal(1, "backpressure test began without an in-flight event");
            end
            rtc_epoch_src = payload;
            rtc_valid_src = 1'b1;
            @(negedge clk_74a);
            rtc_valid_src = 1'b0;
            rtc_epoch_src = 32'h55AA_55AA;
            #1ps;
            if (!rtc_rejected_src) begin
                $fatal(1, "second in-flight event was not explicitly rejected");
            end
        end
    endtask

    initial begin
        #17.25;
        reset_n = 1'b1;
        repeat (3) @(posedge clk_74a);
        #1ps;
        if (rtc_busy_src !== 1'b0 || rtc_rejected_src !== 1'b0 ||
            rtc_valid_dst !== 1'b0 || rtc_epoch_dst !== 32'h0000_0000) begin
            $fatal(1, "RTC CDC reset state mismatch");
        end

        send_accepted(32'h0000_0001);
        send_rejected_while_busy(REJECTED_PAYLOAD);

        send_accepted(32'h7FFF_FFFF);
        send_accepted(32'h8000_0000);
        send_accepted(32'hDEAD_BEEF);
        send_accepted(32'h0123_4567);
        send_accepted(32'hFFFF_FFFF);

        while (delivered_count != PAYLOAD_COUNT || rtc_busy_src) begin
            @(posedge clk_sys);
        end
        repeat (20) @(posedge clk_sys);
        #1ps;

        if (expected_count != PAYLOAD_COUNT || delivered_count != PAYLOAD_COUNT) begin
            $fatal(
                1,
                "event count mismatch accepted=%0d delivered=%0d",
                expected_count,
                delivered_count
            );
        end
        if (rejected_count != 1) begin
            $fatal(1, "rejection pulse count mismatch %0d", rejected_count);
        end
        if (rtc_epoch_dst !== 32'hFFFF_FFFF) begin
            $fatal(1, "destination did not hold final coherent payload");
        end

        $display(
            "PASS APF RTC CDC accepted=%0d delivered=%0d rejected=%0d async-clocks=7ns/11ns",
            expected_count,
            delivered_count,
            rejected_count
        );
        $finish;
    end

    initial begin
        #100000;
        $fatal(1, "RTC CDC test timeout");
    end
endmodule
