`timescale 1ns/1ps

module apf_settings_cdc_tb;
    localparam [9:0] DEFAULT_SETTINGS = 10'h041;
    localparam integer EXPECTED_CAPACITY = 64;

    reg reset_n = 1'b0;
    reg clk_source = 1'b0;
    reg clk_destination = 1'b0;
    reg [9:0] settings_source = DEFAULT_SETTINGS;

    wire update_pending_source;
    wire [9:0] settings_destination;

    reg [9:0] expected [0:EXPECTED_CAPACITY-1];
    integer accepted_count = 0;
    integer delivered_count = 0;
    integer destination_change_count = 0;
    integer seed_index;
    integer timeout;
    reg [9:0] destination_previous = DEFAULT_SETTINGS;
    reg request_previous = 1'b0;

    // Deliberately unrelated 7 ns and 11 ns periods.
    always #3.5 clk_source = ~clk_source;
    always #5.5 clk_destination = ~clk_destination;

    apf_settings_cdc #(
        .DEFAULT_SETTINGS(DEFAULT_SETTINGS)
    ) dut (
        .reset_n(reset_n),
        .clk_source(clk_source),
        .settings_source(settings_source),
        .update_pending_source(update_pending_source),
        .clk_destination(clk_destination),
        .settings_destination(settings_destination)
    );

    // Record exactly the payload accepted by the source protocol. This makes
    // rapid superseding changes legal while still proving that every delivered
    // word is coherent, ordered, and captured exactly once.
    always @(posedge clk_source) begin
        #1ps;
        if (!reset_n) begin
            request_previous = 1'b0;
        end else begin
            if (dut.request_toggle_source != request_previous) begin
                if (accepted_count >= EXPECTED_CAPACITY) begin
                    $fatal(1, "settings expectation capacity exceeded");
                end
                expected[accepted_count] = dut.settings_hold_source;
                accepted_count = accepted_count + 1;
                request_previous = dut.request_toggle_source;
            end
        end
    end

    always @(posedge clk_destination) begin
        #1ps;
        if (!reset_n) begin
            destination_previous = DEFAULT_SETTINGS;
        end else if (settings_destination !== destination_previous) begin
            if (delivered_count >= accepted_count) begin
                $fatal(1, "unsolicited settings destination update");
            end
            if (settings_destination !== expected[delivered_count]) begin
                $fatal(
                    1,
                    "torn/out-of-order settings index=%0d expected=%03x actual=%03x",
                    delivered_count,
                    expected[delivered_count],
                    settings_destination
                );
            end
            destination_previous = settings_destination;
            delivered_count = delivered_count + 1;
            destination_change_count = destination_change_count + 1;
        end
    end

    task automatic set_and_wait(input [9:0] value);
        begin
            @(negedge clk_source);
            settings_source = value;
            timeout = 0;
            while ((update_pending_source || settings_destination !== value) &&
                   timeout < 192) begin
                @(posedge clk_source);
                #1ps;
                timeout = timeout + 1;
            end
            if (update_pending_source || settings_destination !== value) begin
                $fatal(1, "timed out delivering settings value %03x", value);
            end
        end
    endtask

    initial begin
        #17.25;
        reset_n = 1'b1;
        repeat (5) @(posedge clk_source);
        repeat (5) @(posedge clk_destination);
        #1ps;
        if (settings_destination !== DEFAULT_SETTINGS ||
            update_pending_source !== 1'b0 || accepted_count != 0 ||
            delivered_count != 0) begin
            $fatal(1, "settings CDC reset/default state mismatch");
        end

        // Exact interact.json defaults unpack to Auto, normal CPU, triple
        // buffer on, blend off, orientation Auto, landscape-180 off, sound on.
        if (settings_destination[9:8] !== 2'd0 ||
            settings_destination[7] !== 1'b0 ||
            settings_destination[6] !== 1'b1 ||
            settings_destination[5:4] !== 2'd0 ||
            settings_destination[3:2] !== 2'd0 ||
            settings_destination[1] !== 1'b0 ||
            settings_destination[0] !== 1'b1) begin
            $fatal(1, "default bundle does not match interact.json");
        end

        // Exercise every field and both legal nonzero two-bit encodings.
        set_and_wait(10'b01_1_0_01_01_1_0);
        set_and_wait(10'b10_0_1_10_10_0_1);
        set_and_wait(DEFAULT_SETTINGS);

        // Adversarial 01 -> 10 transitions change both bits of system,
        // flicker, and orientation at once. Poison the live source repeatedly
        // while the first snapshot is in flight; the held payload cannot tear.
        @(negedge clk_source);
        settings_source = 10'b01_1_1_01_01_1_1;
        @(posedge clk_source);
        #1ps;
        if (!update_pending_source) begin
            $fatal(1, "adversarial settings transfer did not start");
        end
        for (seed_index = 0; seed_index < 12; seed_index = seed_index + 1) begin
            @(negedge clk_source);
            case (seed_index % 4)
                0: settings_source = 10'b10_0_0_10_10_0_0;
                1: settings_source = 10'b01_0_1_10_01_0_1;
                2: settings_source = 10'b10_1_0_01_10_1_0;
                default: settings_source = 10'b10_1_1_10_10_1_1;
            endcase
        end
        settings_source = 10'b10_1_1_10_10_1_1;

        timeout = 0;
        while ((update_pending_source ||
                settings_destination !== settings_source) && timeout < 256) begin
            @(posedge clk_source);
            #1ps;
            timeout = timeout + 1;
        end
        if (update_pending_source ||
            settings_destination !== 10'b10_1_1_10_10_1_1) begin
            $fatal(1, "rapid settings did not converge on final complete bundle");
        end

        // A host Reset Enter is deliberately absent from this module's reset
        // interface. Holding the stable bundle for many clocks models that
        // interval and proves the destination does not revert to defaults.
        repeat (24) @(posedge clk_destination);
        #1ps;
        if (settings_destination !== 10'b10_1_1_10_10_1_1) begin
            $fatal(1, "stable settings changed without loss of PLL readiness");
        end

        // Loss of PLL readiness is the only reset contract. An in-flight update
        // is discarded and both domains return to the package defaults.
        @(negedge clk_source);
        settings_source = 10'b01_0_0_01_01_0_0;
        @(posedge clk_source);
        #1ps;
        if (!update_pending_source) begin
            $fatal(1, "reset test did not launch an in-flight update");
        end
        #2.25;
        reset_n = 1'b0;
        #1ps;
        if (settings_destination !== DEFAULT_SETTINGS) begin
            $fatal(1, "asynchronous reset did not restore destination defaults");
        end
        settings_source = DEFAULT_SETTINGS;
        repeat (3) @(posedge clk_source);
        repeat (3) @(posedge clk_destination);
        reset_n = 1'b1;
        repeat (5) @(posedge clk_source);
        repeat (5) @(posedge clk_destination);
        #1ps;
        if (settings_destination !== DEFAULT_SETTINGS || update_pending_source) begin
            $fatal(1, "post-reset settings state mismatch");
        end

        if (accepted_count < 5 || delivered_count < 5 ||
            destination_change_count != delivered_count) begin
            $fatal(
                1,
                "insufficient settings coverage accepted=%0d delivered=%0d changes=%0d",
                accepted_count,
                delivered_count,
                destination_change_count
            );
        end

        $display(
            "PASS APF settings CDC accepted=%0d delivered=%0d destination_changes=%0d",
            accepted_count,
            delivered_count,
            destination_change_count
        );
        $finish;
    end
endmodule
