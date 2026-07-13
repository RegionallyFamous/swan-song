`timescale 1ns/1ps

module apf_save_metadata_cdc_tb;
    localparam integer CANONICAL_COUNT = 9;
    localparam integer EXPECTED_CAPACITY = 16;

    reg reset_n = 1'b0;
    reg clk_source = 1'b0;
    reg clk_74a = 1'b0;
    reg [19:0] save_size_bytes_source = 20'd0;
    reg has_rtc_source = 1'b0;
    reg commit_source = 1'b0;

    wire busy_source;
    wire rejected_source;
    wire [19:0] save_size_bytes_74a;
    wire has_rtc_74a;
    wire metadata_valid_74a;

    reg [19:0] canonical_size [0:CANONICAL_COUNT-1];
    reg canonical_rtc [0:CANONICAL_COUNT-1];
    reg [19:0] expected_size [0:EXPECTED_CAPACITY-1];
    reg expected_rtc [0:EXPECTED_CAPACITY-1];

    integer accepted_count = 0;
    integer delivered_count = 0;
    integer rejected_count = 0;
    integer canonical_index;
    reg [31:0] random_word;
    reg previous_destination_valid = 1'b0;
    reg previous_source_rejected = 1'b0;

    // Deliberately unrelated 7 ns and 11 ns periods.
    always #3.5 clk_source = ~clk_source;
    always #5.5 clk_74a = ~clk_74a;

    apf_save_metadata_cdc dut (
        .reset_n(reset_n),
        .clk_source(clk_source),
        .save_size_bytes_source(save_size_bytes_source),
        .has_rtc_source(has_rtc_source),
        .commit_source(commit_source),
        .busy_source(busy_source),
        .rejected_source(rejected_source),
        .clk_74a(clk_74a),
        .save_size_bytes_74a(save_size_bytes_74a),
        .has_rtc_74a(has_rtc_74a),
        .metadata_valid_74a(metadata_valid_74a)
    );

    always @(posedge clk_74a) begin
        #1ps;
        if (!reset_n) begin
            previous_destination_valid = 1'b0;
        end else begin
            if (metadata_valid_74a && previous_destination_valid) begin
                $fatal(1, "destination valid was not a one-cycle pulse");
            end
            if (metadata_valid_74a) begin
                if (delivered_count >= accepted_count) begin
                    $fatal(1, "duplicate or unsolicited metadata publication");
                end
                if (save_size_bytes_74a !== expected_size[delivered_count] ||
                    has_rtc_74a !== expected_rtc[delivered_count]) begin
                    $fatal(
                        1,
                        "torn/out-of-order metadata index=%0d expected=%b:%05x actual=%b:%05x",
                        delivered_count,
                        expected_rtc[delivered_count],
                        expected_size[delivered_count],
                        has_rtc_74a,
                        save_size_bytes_74a
                    );
                end
                delivered_count = delivered_count + 1;
            end
            previous_destination_valid = metadata_valid_74a;
        end
    end

    always @(posedge clk_source) begin
        #1ps;
        if (!reset_n) begin
            previous_source_rejected = 1'b0;
        end else begin
            if (rejected_source && previous_source_rejected) begin
                $fatal(1, "source rejection flag was not a one-cycle pulse");
            end
            if (rejected_source) rejected_count = rejected_count + 1;
            previous_source_rejected = rejected_source;
        end
    end

    task automatic send_accepted(
        input [19:0] size_bytes,
        input rtc_present
    );
        begin
            @(negedge clk_source);
            while (busy_source) begin
                @(negedge clk_source);
            end
            if (accepted_count >= EXPECTED_CAPACITY) begin
                $fatal(1, "test expectation capacity exceeded");
            end
            expected_size[accepted_count] = size_bytes;
            expected_rtc[accepted_count] = rtc_present;
            accepted_count = accepted_count + 1;
            save_size_bytes_source = size_bytes;
            has_rtc_source = rtc_present;
            commit_source = 1'b1;
            @(negedge clk_source);
            commit_source = 1'b0;
            // Poison both live fields immediately. The internal accepted
            // snapshot must remain unchanged throughout the transfer.
            save_size_bytes_source = ~size_bytes;
            has_rtc_source = ~rtc_present;
            #1ps;
            if (!busy_source) begin
                $fatal(1, "accepted metadata did not assert source busy");
            end
            if (dut.metadata_hold !== {rtc_present, size_bytes}) begin
                $fatal(1, "accepted metadata was not held atomically");
            end
        end
    endtask

    task automatic send_rejected_while_busy(
        input [19:0] size_bytes,
        input rtc_present
    );
        reg [20:0] held_before;
        begin
            if (!busy_source) begin
                $fatal(1, "rejection test began without an in-flight snapshot");
            end
            held_before = dut.metadata_hold;
            @(negedge clk_source);
            if (!busy_source) begin
                $fatal(1, "in-flight snapshot completed before rejection test");
            end
            save_size_bytes_source = size_bytes;
            has_rtc_source = rtc_present;
            commit_source = 1'b1;
            @(negedge clk_source);
            commit_source = 1'b0;
            #1ps;
            if (!rejected_source) begin
                $fatal(1, "overlapping commit was not explicitly rejected");
            end
            if (dut.metadata_hold !== held_before) begin
                $fatal(1, "rejected commit replaced the in-flight snapshot");
            end
            // Leave one complete low cycle so each rejection is a separate
            // deliberate commit pulse.
            @(negedge clk_source);
        end
    endtask

    task automatic hold_rejected_through_ack(
        input [19:0] size_bytes,
        input rtc_present
    );
        reg [20:0] held_before;
        integer rejected_before;
        begin
            if (!busy_source) begin
                $fatal(1, "held-commit test began without an in-flight snapshot");
            end
            held_before = dut.metadata_hold;
            rejected_before = rejected_count;
            @(negedge clk_source);
            if (!busy_source) begin
                $fatal(1, "in-flight snapshot completed before held-commit test");
            end
            save_size_bytes_source = size_bytes;
            has_rtc_source = rtc_present;
            commit_source = 1'b1;
            while (busy_source) begin
                @(negedge clk_source);
            end
            // Leave the commit level asserted after acknowledgement. Only its
            // original rising edge may be rejected; it must never become a
            // deferred second publication when busy falls.
            repeat (3) @(negedge clk_source);
            #1ps;
            if (busy_source) begin
                $fatal(1, "held rejected commit was accepted after acknowledgement");
            end
            if (dut.metadata_hold !== held_before) begin
                $fatal(1, "held rejected commit replaced the accepted snapshot");
            end
            if (rejected_count != rejected_before + 1) begin
                $fatal(1, "held commit did not produce exactly one rejection event");
            end
            commit_source = 1'b0;
            @(negedge clk_source);
        end
    endtask

    initial begin
        // The complete WonderSwan footer map, including both 32 KiB SRAM types.
        canonical_size[0] = 20'h00000; canonical_rtc[0] = 1'b0;
        canonical_size[1] = 20'h08000; canonical_rtc[1] = 1'b0;
        canonical_size[2] = 20'h08000; canonical_rtc[2] = 1'b1;
        canonical_size[3] = 20'h20000; canonical_rtc[3] = 1'b0;
        canonical_size[4] = 20'h40000; canonical_rtc[4] = 1'b1;
        canonical_size[5] = 20'h80000; canonical_rtc[5] = 1'b0;
        canonical_size[6] = 20'h00080; canonical_rtc[6] = 1'b1;
        canonical_size[7] = 20'h00800; canonical_rtc[7] = 1'b0;
        canonical_size[8] = 20'h00400; canonical_rtc[8] = 1'b1;

        #17.25;
        reset_n = 1'b1;
        repeat (4) @(posedge clk_source);
        repeat (4) @(posedge clk_74a);
        #1ps;
        if (busy_source !== 1'b0 || rejected_source !== 1'b0 ||
            metadata_valid_74a !== 1'b0 || save_size_bytes_74a !== 20'd0 ||
            has_rtc_74a !== 1'b0) begin
            $fatal(1, "metadata CDC reset state mismatch");
        end

        // Live metadata is not publication. Without commit, arbitrary input
        // changes must not alter the destination or emit a valid pulse.
        repeat (6) begin
            @(negedge clk_source);
            random_word = $urandom;
            save_size_bytes_source = random_word[19:0];
            has_rtc_source = random_word[20];
        end
        repeat (8) @(posedge clk_74a);
        #1ps;
        if (delivered_count != 0 || metadata_valid_74a ||
            save_size_bytes_74a !== 20'd0 || has_rtc_74a !== 1'b0) begin
            $fatal(1, "uncommitted live metadata was published");
        end

        send_accepted(canonical_size[0], canonical_rtc[0]);
        send_rejected_while_busy(20'h12345, 1'b1);
        hold_rejected_through_ack(20'h54321, 1'b0);

        for (canonical_index = 1;
             canonical_index < CANONICAL_COUNT;
             canonical_index = canonical_index + 1) begin
            send_accepted(
                canonical_size[canonical_index],
                canonical_rtc[canonical_index]
            );
        end

        while (delivered_count != accepted_count || busy_source) begin
            @(posedge clk_74a);
        end
        repeat (8) @(posedge clk_74a);
        #1ps;
        if (accepted_count != CANONICAL_COUNT ||
            delivered_count != CANONICAL_COUNT || rejected_count != 2) begin
            $fatal(
                1,
                "canonical phase count mismatch accepted=%0d delivered=%0d rejected=%0d",
                accepted_count,
                delivered_count,
                rejected_count
            );
        end
        if (save_size_bytes_74a !== canonical_size[CANONICAL_COUNT-1] ||
            has_rtc_74a !== canonical_rtc[CANONICAL_COUNT-1]) begin
            $fatal(1, "destination did not hold the final canonical snapshot");
        end

        // Reset an in-flight request before it can traverse both destination
        // synchronizer stages. It must be discarded, not delivered after reset.
        @(negedge clk_source);
        while (busy_source) @(negedge clk_source);
        save_size_bytes_source = 20'h3ABCD;
        has_rtc_source = 1'b1;
        commit_source = 1'b1;
        @(negedge clk_source);
        commit_source = 1'b0;
        #1ps;
        if (!busy_source) $fatal(1, "reset-abort request was not in flight");
        reset_n = 1'b0;
        repeat (3) @(posedge clk_source);
        repeat (3) @(posedge clk_74a);
        #1ps;
        if (busy_source !== 1'b0 || rejected_source !== 1'b0 ||
            metadata_valid_74a !== 1'b0 || save_size_bytes_74a !== 20'd0 ||
            has_rtc_74a !== 1'b0) begin
            $fatal(1, "asynchronous reset did not discard the in-flight request");
        end

        #2.75;
        reset_n = 1'b1;
        repeat (4) @(posedge clk_source);
        repeat (4) @(posedge clk_74a);
        if (delivered_count != CANONICAL_COUNT) begin
            $fatal(1, "reset-aborted metadata was delivered");
        end

        send_accepted(20'h00400, 1'b0);
        while (delivered_count != accepted_count || busy_source) begin
            @(posedge clk_74a);
        end
        repeat (8) @(posedge clk_74a);
        #1ps;
        if (accepted_count != CANONICAL_COUNT + 1 ||
            delivered_count != CANONICAL_COUNT + 1 || rejected_count != 2) begin
            $fatal(1, "post-reset transfer counts are incorrect");
        end

        $display(
            "PASS APF save metadata CDC canonical=%0d accepted=%0d delivered=%0d rejected=%0d async-clocks=7ns/11ns",
            CANONICAL_COUNT,
            accepted_count,
            delivered_count,
            rejected_count
        );
        $finish;
    end

    initial begin
        #100000;
        $fatal(1, "APF save metadata CDC test timeout");
    end
endmodule
