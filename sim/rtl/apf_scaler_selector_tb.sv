`timescale 1ns/1ps

module apf_scaler_selector_tb;
    reg reset_n = 1'b0;
    reg clk_sys = 1'b0;
    reg clk_video = 1'b0;
    reg effective_vertical_sys = 1'b0;
    reg landscape_180_sys = 1'b0;
    reg frame_start_video = 1'b0;

    wire update_pending_sys;
    wire [2:0] scaler_slot_video;
    wire [23:0] eol_word_video;

    integer frame_count = 0;
    integer update_count = 0;
    reg [2:0] slot_before_frame;

    // Deliberately unrelated clocks and non-integral phase offsets.
    always #3.5 clk_sys = ~clk_sys;
    always #5.5 clk_video = ~clk_video;

    apf_scaler_selector dut (
        .reset_n(reset_n),
        .clk_sys(clk_sys),
        .effective_vertical_sys(effective_vertical_sys),
        .landscape_180_sys(landscape_180_sys),
        .update_pending_sys(update_pending_sys),
        .clk_video(clk_video),
        .frame_start_video(frame_start_video),
        .scaler_slot_video(scaler_slot_video),
        .eol_word_video(eol_word_video)
    );

    task automatic check_eol(input [2:0] expected_slot);
        reg [23:0] expected_word;
        begin
            expected_word = {8'd0, expected_slot, 10'd0, 3'b000};
            #1ps;
            if (scaler_slot_video !== expected_slot ||
                eol_word_video !== expected_word) begin
                $fatal(
                    1,
                    "slot/EOL mismatch expected_slot=%0d expected_word=%06x actual_slot=%0d actual_word=%06x",
                    expected_slot,
                    expected_word,
                    scaler_slot_video,
                    eol_word_video
                );
            end
            if (eol_word_video[12:3] !== 10'd0 ||
                eol_word_video[2:0] !== 3'b000 ||
                eol_word_video[23:16] !== 8'd0) begin
                $fatal(1, "reserved EOL bits or function code were nonzero");
            end
        end
    endtask

    task automatic pulse_frame_start;
        begin
            @(negedge clk_video);
            frame_start_video = 1'b1;
            @(negedge clk_video);
            frame_start_video = 1'b0;
            frame_count = frame_count + 1;
            #1ps;
        end
    endtask

    task automatic wait_for_video_pending;
        integer timeout;
        begin
            timeout = 0;
            while (!dut.pending_valid_video && timeout < 64) begin
                @(posedge clk_video);
                #1ps;
                timeout = timeout + 1;
            end
            if (!dut.pending_valid_video) begin
                $fatal(1, "timed out waiting for atomic video-domain update");
            end
        end
    endtask

    task automatic wait_for_source_idle;
        integer timeout;
        begin
            timeout = 0;
            while (update_pending_sys && timeout < 96) begin
                @(posedge clk_sys);
                #1ps;
                timeout = timeout + 1;
            end
            if (update_pending_sys) begin
                $fatal(1, "timed out waiting for scaler source acknowledgement");
            end
        end
    endtask

    always @(scaler_slot_video) begin
        if (reset_n) update_count = update_count + 1;
    end

    initial begin
        #17.25;
        reset_n = 1'b1;
        repeat (4) @(posedge clk_sys);
        repeat (4) @(posedge clk_video);
        check_eol(3'd0);

        // Portrait wins over the landscape-only 180-degree option.
        @(negedge clk_sys);
        effective_vertical_sys = 1'b1;
        landscape_180_sys = 1'b1;
        wait_for_video_pending();
        slot_before_frame = scaler_slot_video;
        repeat (5) @(posedge clk_video);
        #1ps;
        if (scaler_slot_video !== slot_before_frame) begin
            $fatal(1, "slot changed outside a video frame boundary");
        end
        pulse_frame_start();
        check_eol(3'd1);
        wait_for_source_idle();

        // Disabling the ignored landscape option while portrait is active
        // must not create a redundant CDC transaction or output change.
        @(negedge clk_sys);
        landscape_180_sys = 1'b0;
        repeat (8) @(posedge clk_sys);
        #1ps;
        if (update_pending_sys) begin
            $fatal(1, "ignored portrait flip created an update");
        end
        check_eol(3'd1);

        // Landscape plus the legacy flip selects the dedicated rotation-180
        // scaler mode; the exact APF EOL word is 0x004000.
        @(negedge clk_sys);
        effective_vertical_sys = 1'b0;
        landscape_180_sys = 1'b1;
        wait_for_video_pending();
        check_eol(3'd1);
        pulse_frame_start();
        check_eol(3'd2);
        if (eol_word_video !== 24'h004000) begin
            $fatal(1, "landscape-180 EOL encoding was not exact");
        end
        wait_for_source_idle();

        // Return to ordinary landscape.
        @(negedge clk_sys);
        landscape_180_sys = 1'b0;
        wait_for_video_pending();
        pulse_frame_start();
        check_eol(3'd0);
        if (eol_word_video !== 24'h000000) begin
            $fatal(1, "landscape slot-zero EOL encoding was not exact");
        end
        wait_for_source_idle();

        // If a complete CDC request arrives on the frame boundary itself, the
        // destination must not bypass its canonical payload register or apply
        // an older pending slot. It holds this frame and applies the newly
        // captured portrait slot on the following boundary.
        @(negedge clk_sys);
        effective_vertical_sys = 1'b1;
        landscape_180_sys = 1'b0;
        while (dut.request_sync_video == dut.request_seen_video) begin
            @(negedge clk_video);
        end
        frame_start_video = 1'b1;
        @(negedge clk_video);
        frame_start_video = 1'b0;
        frame_count = frame_count + 1;
        #1ps;
        check_eol(3'd0);
        if (!dut.pending_valid_video || dut.pending_slot_video !== 2'd1) begin
            $fatal(1, "coincident request was not held in canonical pending state");
        end
        pulse_frame_start();
        check_eol(3'd1);
        wait_for_source_idle();

        // Return to landscape before the rapid-supersession phase.
        @(negedge clk_sys);
        effective_vertical_sys = 1'b0;
        wait_for_video_pending();
        pulse_frame_start();
        check_eol(3'd0);
        wait_for_source_idle();

        // Rapidly request portrait, landscape-180, then portrait again while
        // withholding frame boundaries. Complete payloads may supersede one
        // another, but no intermediate/torn slot may leak to the output.
        @(negedge clk_sys);
        effective_vertical_sys = 1'b1;
        landscape_180_sys = 1'b0;
        repeat (2) @(negedge clk_sys);
        effective_vertical_sys = 1'b0;
        landscape_180_sys = 1'b1;
        repeat (2) @(negedge clk_sys);
        effective_vertical_sys = 1'b1;
        landscape_180_sys = 1'b1;

        slot_before_frame = scaler_slot_video;
        repeat (32) begin
            @(posedge clk_video);
            #1ps;
            if (scaler_slot_video !== slot_before_frame) begin
                $fatal(1, "rapid update changed slot away from frame boundary");
            end
            if (dut.pending_valid_video && dut.pending_slot_video == 2'd3) begin
                $fatal(1, "torn/reserved slot crossed into video domain");
            end
        end
        wait_for_source_idle();
        if (!dut.pending_valid_video || dut.pending_slot_video !== 2'd1) begin
            $fatal(1, "rapid update did not retain the newest complete slot");
        end
        pulse_frame_start();
        check_eol(3'd1);

        // An asynchronous reset during an in-flight update discards both the
        // transfer and pending video state, returning to safe slot zero.
        @(negedge clk_sys);
        effective_vertical_sys = 1'b0;
        landscape_180_sys = 1'b1;
        @(posedge clk_sys);
        #1ps;
        if (!update_pending_sys) begin
            $fatal(1, "reset test failed to launch an update");
        end
        #2.25;
        reset_n = 1'b0;
        #1ps;
        check_eol(3'd0);
        repeat (3) @(posedge clk_sys);
        repeat (3) @(posedge clk_video);
        reset_n = 1'b1;
        // Restore source default before synchronized reset release so no new
        // post-reset update is legitimately generated.
        effective_vertical_sys = 1'b0;
        landscape_180_sys = 1'b0;
        repeat (5) @(posedge clk_sys);
        repeat (5) @(posedge clk_video);
        #1ps;
        if (update_pending_sys || dut.pending_valid_video) begin
            $fatal(1, "reset left a stale scaler update pending");
        end
        check_eol(3'd0);

        if (frame_count < 4 || update_count < 3) begin
            $fatal(
                1,
                "insufficient scaler coverage frames=%0d updates=%0d",
                frame_count,
                update_count
            );
        end

        $display(
            "PASS APF scaler selector frames=%0d output_updates=%0d",
            frame_count,
            update_count
        );
        $finish;
    end
endmodule
