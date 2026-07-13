`timescale 1ns/1ps

module apf_video_bus_tb;
    localparam integer LINE_CYCLES = 401;
    localparam integer FRAME_LINES = 258;
    localparam integer FRAME_CYCLES = LINE_CYCLES * FRAME_LINES;
    localparam [23:0] SCALER_EOL_WORD = 24'h004000;

    reg clk_sys = 1'b0;
    reg clk_video = 1'b0;
    always #1 clk_sys = ~clk_sys;
    always #10 clk_video = ~clk_video;

    reg [23:0] core_rgb = 24'd0;
    reg core_hblank = 1'b1;
    reg core_vblank = 1'b1;
    reg core_hs = 1'b0;
    reg core_vs = 1'b0;
    reg grayscale_requested = 1'b0;

    wire [23:0] video_rgb;
    wire video_de;
    wire video_vs;
    wire video_hs;
    wire frame_start_video;
    wire grayscale_applied;

    integer cycle_count = 0;
    integer active_count = 0;
    integer eol_count = 0;
    integer hs_count = 0;
    integer vs_count = 0;
    integer first_vs_cycle = -1;
    integer second_vs_cycle = -1;
    integer last_hs_cycle = -1;
    integer last_active_cycle = -1;
    reg previous_active = 1'b0;
    reg previous_core_vs = 1'b0;
    reg previous_video_de = 1'b0;
    reg previous_video_hs = 1'b0;
    reg previous_video_vs = 1'b0;
    reg have_held_sample = 1'b0;
    reg [23:0] held_video_rgb = 24'd0;
    reg held_video_de = 1'b0;
    reg held_video_hs = 1'b0;
    reg held_video_vs = 1'b0;

    apf_video_bus dut (
        .clk_sys(clk_sys),
        .clk_video(clk_video),
        .core_rgb(core_rgb),
        .core_hblank(core_hblank),
        .core_vblank(core_vblank),
        .core_hs(core_hs),
        .core_vs(core_vs),
        .scaler_eol_word(SCALER_EOL_WORD),
        .displaymode_grayscale_requested(grayscale_requested),
        .video_rgb(video_rgb),
        .video_de(video_de),
        .video_vs(video_vs),
        .video_hs(video_hs),
        .frame_start_video(frame_start_video),
        .displaymode_grayscale_applied(grayscale_applied)
    );

    function automatic [23:0] grayscale(input [23:0] rgb);
        reg [9:0] sum;
        reg [7:0] luma;
        begin
            sum = rgb[23:16] + (rgb[15:8] << 1) + rgb[7:0];
            luma = sum[9:2];
            grayscale = {3{luma}};
        end
    endfunction

    // APF RGB/control must remain stable for the complete video-clock cycle.
    always @(negedge clk_video) begin
        if (have_held_sample &&
            ({video_rgb, video_de, video_hs, video_vs} !==
             {held_video_rgb, held_video_de, held_video_hs, held_video_vs})) begin
            $fatal(1, "video bus changed away from its active clock edge");
        end
    end

    task automatic drive_sample(
        input bit active,
        input bit hs,
        input bit vs,
        input bit expected_grayscale,
        input [23:0] rgb
    );
        reg expected_vs;
        reg [23:0] expected_rgb;
        begin
            @(negedge clk_video);
            #1;
            core_rgb = rgb;
            core_hblank = ~active;
            core_vblank = ~active;
            core_hs = hs;
            core_vs = vs;

            @(posedge clk_video);
            #1;
            cycle_count = cycle_count + 1;
            expected_vs = vs && ~previous_core_vs;

            if (video_de !== active) begin
                $fatal(1, "DE mismatch cycle=%0d got=%0b expected=%0b",
                       cycle_count, video_de, active);
            end

            if (active) begin
                active_count = active_count + 1;
                if (grayscale_applied !== expected_grayscale) begin
                    $fatal(1, "grayscale state changed during active frame cycle=%0d", cycle_count);
                end
                expected_rgb = expected_grayscale ? grayscale(rgb) : rgb;
                if (video_rgb !== expected_rgb) begin
                    $fatal(1, "active RGB mismatch cycle=%0d got=%06x expected=%06x",
                           cycle_count, video_rgb, expected_rgb);
                end
                last_active_cycle = cycle_count;
            end else if (previous_active) begin
                eol_count = eol_count + 1;
                if (video_rgb !== SCALER_EOL_WORD) begin
                    $fatal(1, "missing scaler EOL word cycle=%0d got=%06x",
                           cycle_count, video_rgb);
                end
            end else if (video_rgb !== 24'd0) begin
                $fatal(1, "reserved blanking word is nonzero cycle=%0d rgb=%06x",
                       cycle_count, video_rgb);
            end

            if (video_vs !== expected_vs) begin
                $fatal(1, "VS edge mismatch cycle=%0d got=%0b expected=%0b",
                       cycle_count, video_vs, expected_vs);
            end
            if (video_vs) begin
                vs_count = vs_count + 1;
                if (first_vs_cycle < 0)
                    first_vs_cycle = cycle_count;
                else if (second_vs_cycle < 0)
                    second_vs_cycle = cycle_count;
            end

            if (video_hs) begin
                hs_count = hs_count + 1;
                if (last_hs_cycle >= 0 && cycle_count - last_hs_cycle != LINE_CYCLES)
                    $fatal(1, "HS cadence %0d cycles", cycle_count - last_hs_cycle);
                if (last_active_cycle >= 0 && cycle_count - last_active_cycle < LINE_CYCLES &&
                    cycle_count - last_active_cycle != 14)
                    $fatal(1, "DE-to-HS gap %0d cycles", cycle_count - last_active_cycle);
                last_hs_cycle = cycle_count;
            end
            if (video_de && ~previous_video_de && last_hs_cycle >= 0 &&
                cycle_count - last_hs_cycle != 164)
                $fatal(1, "HS-to-DE gap %0d cycles", cycle_count - last_hs_cycle);
            if (video_hs && (video_de || video_vs || video_rgb != 24'd0)) begin
                $fatal(1, "HS overlapped DE/VS/reserved word cycle=%0d", cycle_count);
            end
            if (video_hs && previous_video_hs) begin
                $fatal(1, "HS lasted longer than one video cycle at cycle=%0d", cycle_count);
            end
            if (video_vs && previous_video_vs) begin
                $fatal(1, "VS lasted longer than one video cycle at cycle=%0d", cycle_count);
            end

            previous_active = active;
            previous_core_vs = vs;
            previous_video_de = video_de;
            previous_video_hs = video_hs;
            previous_video_vs = video_vs;
            held_video_rgb = video_rgb;
            held_video_de = video_de;
            held_video_hs = video_hs;
            held_video_vs = video_vs;
            have_held_sample = 1'b1;
        end
    endtask

    task automatic drive_frame(
        input bit requested_mode,
        input bit expected_active_mode
    );
        integer x;
        integer y;
        reg active;
        reg hs;
        reg vs;
        reg [23:0] rgb;
        begin
            grayscale_requested = requested_mode;
            for (y = 0; y < FRAME_LINES; y = y + 1) begin
                for (x = 0; x < LINE_CYCLES; x = x + 1) begin
                    active = y < 144 && x < 224;
                    hs = x == 230;
                    vs = y == 145 && x == 10;
                    rgb = {x[7:0], y[7:0], (x ^ y) & 8'hff};
                    drive_sample(active, hs, vs, expected_active_mode, rgb);
                end
            end
        end
    endtask

    initial begin
        // Prime the half-cycle stage with a known blank sample.
        repeat (4) drive_sample(1'b0, 1'b0, 1'b0, 1'b0, 24'd0);

        // The first frame remains color; its VS atomically enables grayscale
        // for the next complete active frame. The second VS disables it again.
        drive_frame(1'b1, 1'b0);
        drive_frame(1'b0, 1'b1);

        if (active_count != 2 * 224 * 144)
            $fatal(1, "active pixel count %0d", active_count);
        if (eol_count != 2 * 144)
            $fatal(1, "active-line EOL count %0d", eol_count);
        if (hs_count != 2 * FRAME_LINES)
            $fatal(1, "HS count %0d", hs_count);
        if (vs_count != 2)
            $fatal(1, "VS count %0d", vs_count);
        if (second_vs_cycle - first_vs_cycle != FRAME_CYCLES)
            $fatal(1, "frame cadence %0d cycles", second_vs_cycle - first_vs_cycle);

        // The second VS must restore color before the next active pixel.
        drive_sample(1'b1, 1'b0, 1'b0, 1'b0, 24'h12_34_56);
        drive_sample(1'b0, 1'b0, 1'b0, 1'b0, 24'd0);

        $display(
            "PASS APF video bus active=224x144 lines=258 cadence=103458@6.144MHz(59.386Hz) hs/vs=one-cycle gaps=14/164 eol=one-per-active-line grayscale=frame-atomic stable=full-cycle"
        );
        $finish;
    end
endmodule
