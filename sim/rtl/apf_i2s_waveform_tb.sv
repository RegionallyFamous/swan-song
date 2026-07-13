`timescale 1ns/1ps

// Behavioral stand-in for Intel's dcfifo-backed sync_fifo.  The waveform test
// covers the I2S generator; physical FIFO CDC timing remains a hardware gate.
module sync_fifo #(
    parameter WIDTH = 2
) (
    input  wire               clk_write,
    input  wire               clk_read,
    input  wire               write_en,
    input  wire [WIDTH - 1:0] data,
    output reg  [WIDTH - 1:0] data_s = 0,
    output reg                write_en_s = 0
);
    reg [WIDTH - 1:0] pending = 0;
    reg pending_toggle = 0;
    reg toggle_sync_1 = 0;
    reg toggle_sync_2 = 0;
    reg toggle_seen = 0;

    always @(posedge clk_write) begin
        if (write_en) begin
            pending <= data;
            pending_toggle <= ~pending_toggle;
        end
    end

    always @(posedge clk_read) begin
        toggle_sync_1 <= pending_toggle;
        toggle_sync_2 <= toggle_sync_1;
        write_en_s <= 1'b0;
        if (toggle_sync_2 != toggle_seen) begin
            data_s <= pending;
            toggle_seen <= toggle_sync_2;
            write_en_s <= 1'b1;
        end
    end
endmodule

module apf_i2s_waveform_tb;
    localparam [15:0] LEFT_SAMPLE = 16'h8123;
    localparam [15:0] RIGHT_SAMPLE = 16'h4567;
    localparam integer WINDOW_CLK_74A_CYCLES = 742500;

    reg clk_74a = 1'b0;
    reg clk_audio = 1'b0;
    reg [15:0] audio_l = LEFT_SAMPLE;
    reg [15:0] audio_r = RIGHT_SAMPLE;

    wire audio_mclk;
    wire audio_lrck;
    wire audio_dac;

    integer source_cycles = 0;
    integer mclk_rises = 0;
    integer mclk_falls = 0;
    integer sclk_rises = 0;
    integer sclk_falls = 0;
    integer lrck_toggles = 0;
    integer verified_left = 0;
    integer verified_right = 0;
    integer last_mclk_transition = 0;
    integer slot_index = 0;

    reg prev_mclk;
    reg prev_sclk;
    reg prev_lrck;
    reg prev_dac;
    reg slot_valid = 1'b0;
    reg verify_requested = 1'b0;
    reg checking_samples = 1'b0;
    reg [15:0] captured_word = 16'h0000;

    always #1 clk_74a = ~clk_74a;
    always #2 clk_audio = ~clk_audio;

    sound_i2s #(
        .CHANNEL_WIDTH(16),
        .SIGNED_INPUT(1)
    ) dut (
        .clk_74a(clk_74a),
        .clk_audio(clk_audio),
        .audio_l(audio_l),
        .audio_r(audio_r),
        .audio_mclk(audio_mclk),
        .audio_lrck(audio_lrck),
        .audio_dac(audio_dac)
    );

    always @(posedge clk_74a) begin
        #1ps;
        source_cycles = source_cycles + 1;

        if ((audio_mclk !== 1'b0 && audio_mclk !== 1'b1) ||
            (dut.audgen_sclk !== 1'b0 && dut.audgen_sclk !== 1'b1) ||
            (audio_lrck !== 1'b0 && audio_lrck !== 1'b1) ||
            (audio_dac !== 1'b0 && audio_dac !== 1'b1)) begin
            $fatal(1, "I2S output became unknown at clk_74a cycle %0d", source_cycles);
        end

        if (!prev_mclk && audio_mclk) begin
            mclk_rises = mclk_rises + 1;
            if (last_mclk_transition != 0 &&
                source_cycles - last_mclk_transition != 3 &&
                source_cycles - last_mclk_transition != 4) begin
                $fatal(1, "MCLK fractional cadence interval=%0d", source_cycles - last_mclk_transition);
            end
            last_mclk_transition = source_cycles;
        end else if (prev_mclk && !audio_mclk) begin
            mclk_falls = mclk_falls + 1;
            if (source_cycles - last_mclk_transition != 3 &&
                source_cycles - last_mclk_transition != 4) begin
                $fatal(1, "MCLK fractional cadence interval=%0d", source_cycles - last_mclk_transition);
            end
            last_mclk_transition = source_cycles;
        end

        if (dut.audgen_sclk != prev_sclk) begin
            if (!(!prev_mclk && audio_mclk)) begin
                $fatal(1, "SCLK edge was not aligned to an MCLK rising edge");
            end

            if (!prev_sclk && dut.audgen_sclk) begin
                sclk_rises = sclk_rises + 1;

                if (slot_valid) begin
                    if (slot_index == 0 || slot_index >= 17) begin
                        if (audio_dac !== 1'b0) begin
                            $fatal(
                                1,
                                "nonzero I2S spacer bit channel=%s slot=%0d",
                                audio_lrck ? "right" : "left",
                                slot_index
                            );
                        end
                    end else begin
                        captured_word = {captured_word[14:0], audio_dac};
                        if (slot_index == 16 && checking_samples) begin
                            if (!audio_lrck) begin
                                if (captured_word !== LEFT_SAMPLE) begin
                                    $fatal(1, "left sample mismatch %04x", captured_word);
                                end
                                verified_left = verified_left + 1;
                            end else begin
                                if (captured_word !== RIGHT_SAMPLE) begin
                                    $fatal(1, "right sample mismatch %04x", captured_word);
                                end
                                verified_right = verified_right + 1;
                            end
                        end
                    end
                    slot_index = slot_index + 1;
                end
            end else begin
                sclk_falls = sclk_falls + 1;
                if (audio_lrck != prev_lrck) begin
                    lrck_toggles = lrck_toggles + 1;
                    if (slot_valid && slot_index != 32) begin
                        $fatal(1, "LRCK channel width was %0d SCLK cycles", slot_index);
                    end
                    slot_valid = 1'b1;
                    slot_index = 0;
                    captured_word = 16'h0000;
                    if (verify_requested) begin
                        checking_samples = 1'b1;
                    end
                end
            end
        end

        if (audio_lrck != prev_lrck && !(prev_sclk && !dut.audgen_sclk)) begin
            $fatal(1, "LRCK edge was not aligned to an SCLK falling edge");
        end
        if (audio_dac != prev_dac && !(prev_sclk && !dut.audgen_sclk)) begin
            $fatal(1, "DAC changed away from an SCLK falling edge");
        end

        prev_mclk = audio_mclk;
        prev_sclk = dut.audgen_sclk;
        prev_lrck = audio_lrck;
        prev_dac = audio_dac;
    end

    initial begin
        #100ps;
        if (audio_mclk !== 1'b0 || dut.audgen_sclk !== 1'b0 ||
            audio_lrck !== 1'b0 || audio_dac !== 1'b0) begin
            $fatal(1, "I2S startup state is not deterministic zero");
        end
        if ($signed(LEFT_SAMPLE) >= 0 || $signed(RIGHT_SAMPLE) <= 0) begin
            $fatal(1, "test samples are not signed asymmetric values");
        end

        prev_mclk = audio_mclk;
        prev_sclk = dut.audgen_sclk;
        prev_lrck = audio_lrck;
        prev_dac = audio_dac;

        repeat (2000) @(posedge clk_74a);
        verify_requested = 1'b1;
        repeat (WINDOW_CLK_74A_CYCLES - 2000) @(posedge clk_74a);
        #2ps;

        if (source_cycles != WINDOW_CLK_74A_CYCLES) begin
            $fatal(1, "source clock window mismatch %0d", source_cycles);
        end
        if (mclk_rises != 122880 || mclk_falls != 122879) begin
            $fatal(1, "MCLK cadence mismatch rises=%0d falls=%0d", mclk_rises, mclk_falls);
        end
        if (sclk_rises != 30720 || sclk_falls != 30720) begin
            $fatal(1, "SCLK cadence mismatch rises=%0d falls=%0d", sclk_rises, sclk_falls);
        end
        if (lrck_toggles != 960) begin
            $fatal(1, "LRCK cadence mismatch toggles=%0d", lrck_toggles);
        end
        if (verified_left < 400 || verified_right < 400) begin
            $fatal(
                1,
                "insufficient decoded samples left=%0d right=%0d",
                verified_left,
                verified_right
            );
        end

        $display(
            "PASS APF I2S MCLK=12.288MHz SCLK=3.072MHz frames=480 left=%04x right=%04x decoded=%0d/%0d",
            LEFT_SAMPLE,
            RIGHT_SAMPLE,
            verified_left,
            verified_right
        );
        $finish;
    end
endmodule
