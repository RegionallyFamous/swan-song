`timescale 1ps/1ps

module footer_snapshot_tb;
    localparam integer RAM_TYPE_COUNT = 9;

    reg clk_mem_110_592 = 1'b0;
    reg clk_sys_36_864 = 1'b0;
    reg reset_n = 1'b1;
    reg reset_n_sys = 1'b1;
    reg pll_core_locked = 1'b0;
    reg [1:0] ext_cart_download = 2'b00;
    reg [1:0] ext_cart_download_sys = 2'b00;
    reg ioctl_wr = 1'b0;
    reg [24:0] ioctl_addr = 25'd0;
    reg [15:0] ioctl_dout = 16'd0;
    reg [1:0] configured_system = 2'b00;

    wire [19:0] save_size_bytes;
    wire has_rtc;
    wire save_metadata_commit;

    integer sys_phase_ps = 250;
    integer case_count = 0;
    integer ram_index;
    integer rtc_index;
    integer color_index;
    reg [7:0] ram_types [0:RAM_TYPE_COUNT-1];
    reg [19:0] expected_sizes [0:RAM_TYPE_COUNT-1];

    // 110.592 MHz and 36.864 MHz are exactly 3:1. The run script moves the
    // system-clock phase through a complete memory-clock interval so the
    // footer handoff is checked on both sides of every relative edge.
    always #1500 clk_mem_110_592 = ~clk_mem_110_592;
    initial begin
        if (!$value$plusargs("sys_phase_ps=%d", sys_phase_ps)) begin
            sys_phase_ps = 250;
        end
        #(sys_phase_ps);
        forever #4500 clk_sys_36_864 = ~clk_sys_36_864;
    end

    wonderswan dut (
        .clk_sys_36_864(clk_sys_36_864),
        .clk_mem_110_592(clk_mem_110_592),
        .reset_n(reset_n),
        .reset_n_sys(reset_n_sys),
        .pll_core_locked(pll_core_locked),
        .external_reset(1'b0),
        .ioctl_wr(ioctl_wr),
        .ioctl_addr(ioctl_addr),
        .ioctl_dout(ioctl_dout),
        .rom_size_mem(25'd0),
        .rom_plan_valid_mem(1'b0),
        .rom_size_sys(25'd0),
        .rom_plan_valid_sys(1'b0),
        .ext_cart_download(ext_cart_download),
        .ext_cart_download_sys(ext_cart_download_sys),
        .bios_download(2'b00),
        .bios_wr(1'b0),
        .bios_addr(13'd0),
        .bios_dout(16'd0),
        .rtc_epoch_seconds(32'd0),
        .rtc_epoch_valid(1'b0),
        .configured_system(configured_system),
        .use_cpu_turbo(1'b0),
        .use_rewind_capture(1'b0),
        .use_triple_buffer(1'b0),
        .configured_flickerblend(2'b00),
        .configured_orientation(2'b00),
        .configured_control_layout(2'b00),
        .use_flip_horizontal(1'b0),
        .configured_color_profile(1'b0),
        .use_fastforward_sound(1'b0),
        .load_complete(1'b0),
        .sd_buff_wr(1'b0),
        .sd_buff_rd(1'b0),
        .sd_buff_addr(21'd0),
        .sd_buff_dout(16'd0),
        .console_eeprom_wr(1'b0),
        .console_eeprom_rd(1'b0),
        .console_eeprom_bank(1'b0),
        .console_eeprom_addr(11'd0),
        .console_eeprom_dout(16'd0),
        .ss_save(1'b0),
        .ss_load(1'b0),
        .ss_dout(64'd0),
        .ss_ack(1'b0),
        .save_size_bytes(save_size_bytes),
        .has_rtc(has_rtc),
        .save_metadata_commit(save_metadata_commit)
    );

    task automatic write_footer_word(input [15:0] word_data);
        begin
            @(negedge clk_mem_110_592);
            ioctl_dout = word_data;
            ioctl_wr = 1'b1;
            @(negedge clk_mem_110_592);
            ioctl_wr = 1'b0;
        end
    endtask

    task automatic check_case(
        input [7:0] ram_type,
        input [19:0] expected_size,
        input rtc_present,
        input color_model
    );
        reg expected_sram;
        reg expected_eeprom;
        begin
            expected_sram = ram_type inside {
                8'h01, 8'h02, 8'h03, 8'h04, 8'h05
            };
            expected_eeprom = ram_type inside {8'h10, 8'h20, 8'h50};

            ext_cart_download = color_model ? 2'b10 : 2'b01;
            ext_cart_download_sys = ext_cart_download;

            // Five final little-endian words cover footer bytes -10 through
            // -1. Only the model, RTC/mapper, and RAM-type fields are varied;
            // distinctive filler proves that the decoder uses the right word.
            write_footer_word({7'h2a, color_model, 8'h51});
            write_footer_word(16'h62a4);
            write_footer_word({ram_type, 8'h73});
            write_footer_word({rtc_present ? 8'h01 : 8'h00, 8'h84});
            write_footer_word(16'h95b6);

            // The host keeps the title-load indication live through the first
            // system edge after the final memory-domain word. This is the
            // protocol boundary the production snapshot consumes.
            @(posedge clk_sys_36_864);
            #1;

            if (dut.footer_color_sys !== color_model ||
                dut.footer_romtype_sys !== (rtc_present ? 8'h01 : 8'h00) ||
                dut.footer_ramtype_sys !== ram_type) begin
                $fatal(
                    1,
                    "torn footer snapshot phase=%0d ram=%02x rtc=%0d color=%0d got=%0d:%02x:%02x",
                    sys_phase_ps,
                    ram_type,
                    rtc_present,
                    color_model,
                    dut.footer_color_sys,
                    dut.footer_romtype_sys,
                    dut.footer_ramtype_sys
                );
            end

            if (dut.ramtype_mem !== ram_type || dut.ramtype_sys !== ram_type ||
                dut.has_rtc_mem !== rtc_present ||
                dut.has_rtc_sys !== rtc_present ||
                save_size_bytes !== expected_size ||
                dut.save_size_bytes_sys !== expected_size ||
                dut.save_is_sram_mem !== expected_sram ||
                dut.save_is_sram_sys !== expected_sram ||
                dut.save_is_eeprom_mem !== expected_eeprom) begin
                $fatal(
                    1,
                    "footer decoder mismatch phase=%0d ram=%02x rtc=%0d color=%0d",
                    sys_phase_ps,
                    ram_type,
                    rtc_present,
                    color_model
                );
            end

            if (dut.isColor !== color_model) begin
                $fatal(
                    1,
                    "automatic model mismatch phase=%0d expected=%0d actual=%0d",
                    sys_phase_ps,
                    color_model,
                    dut.isColor
                );
            end

            ext_cart_download = 2'b00;
            ext_cart_download_sys = 2'b00;
            @(posedge clk_mem_110_592);
            #1;
            if (!save_metadata_commit) begin
                $fatal(1, "footer metadata commit missing at cartridge completion");
            end
            @(posedge clk_mem_110_592);
            #1;
            if (save_metadata_commit) begin
                $fatal(1, "footer metadata commit was not a one-cycle pulse");
            end

            // Host Reset Enter/Exit belongs to the running title. It may
            // reset execution state, but must not erase the footer identity
            // needed by the save and mapper paths on Reset Exit.
            @(negedge clk_sys_36_864);
            reset_n = 1'b0;
            reset_n_sys = 1'b0;
            @(posedge clk_sys_36_864);
            #1;
            if (dut.footer_color_sys !== color_model ||
                dut.footer_romtype_sys !== (rtc_present ? 8'h01 : 8'h00) ||
                dut.footer_ramtype_sys !== ram_type ||
                dut.ramtype_sys !== ram_type ||
                dut.has_rtc_sys !== rtc_present ||
                dut.save_size_bytes_sys !== expected_size ||
                dut.isColor !== color_model) begin
                $fatal(1, "host reset erased footer snapshot identity");
            end
            reset_n = 1'b1;
            reset_n_sys = 1'b1;
            case_count = case_count + 1;
        end
    endtask

    task automatic check_system_type_reset_lifecycle;
        begin
            // The final footer-matrix case is a Color title and the preceding
            // host reset captured Auto. A runtime request for forced mono must
            // not change the running machine before another reset.
            if (dut.configured_system_active !== 2'b00 ||
                dut.isColor !== 1'b1) begin
                $fatal(1, "system-type lifecycle did not start in Color Auto");
            end
            configured_system = 2'b01;
            repeat (4) @(posedge clk_sys_36_864);
            #1;
            if (dut.configured_system_active !== 2'b00 ||
                dut.isColor !== 1'b1) begin
                $fatal(1, "runtime System Type changed the active model before reset");
            end

            // Host Reset Enter applies the latest requested value. It must
            // remain active after Reset Exit.
            @(negedge clk_sys_36_864);
            reset_n = 1'b0;
            reset_n_sys = 1'b0;
            @(posedge clk_sys_36_864);
            #1;
            if (dut.configured_system_active !== 2'b01 ||
                dut.isColor !== 1'b0) begin
                $fatal(1, "host reset did not apply forced mono System Type");
            end
            reset_n = 1'b1;
            reset_n_sys = 1'b1;
            repeat (2) @(posedge clk_sys_36_864);
            #1;
            if (dut.configured_system_active !== 2'b01 ||
                dut.isColor !== 1'b0) begin
                $fatal(1, "forced mono System Type did not survive Reset Exit");
            end

            // A second runtime change is also inert until the next title-load
            // reset, which then captures the forced Color request.
            configured_system = 2'b10;
            repeat (4) @(posedge clk_sys_36_864);
            #1;
            if (dut.configured_system_active !== 2'b01 ||
                dut.isColor !== 1'b0) begin
                $fatal(1, "runtime forced Color request bypassed reset semantics");
            end
            ext_cart_download_sys = 2'b01;
            @(posedge clk_sys_36_864);
            #1;
            if (dut.configured_system_active !== 2'b10 ||
                dut.isColor !== 1'b1) begin
                $fatal(1, "title-load reset did not apply forced Color System Type");
            end
            ext_cart_download_sys = 2'b00;
            repeat (2) @(posedge clk_sys_36_864);
            #1;
            if (dut.configured_system_active !== 2'b10 ||
                dut.isColor !== 1'b1) begin
                $fatal(1, "forced Color System Type did not survive title boot");
            end
        end
    endtask

    initial begin
        ram_types[0] = 8'h00; expected_sizes[0] = 20'h00000;
        ram_types[1] = 8'h01; expected_sizes[1] = 20'h08000;
        ram_types[2] = 8'h02; expected_sizes[2] = 20'h08000;
        ram_types[3] = 8'h03; expected_sizes[3] = 20'h20000;
        ram_types[4] = 8'h04; expected_sizes[4] = 20'h40000;
        ram_types[5] = 8'h05; expected_sizes[5] = 20'h80000;
        ram_types[6] = 8'h10; expected_sizes[6] = 20'h00080;
        ram_types[7] = 8'h20; expected_sizes[7] = 20'h00800;
        ram_types[8] = 8'h50; expected_sizes[8] = 20'h00400;

        repeat (3) @(posedge clk_mem_110_592);
        pll_core_locked = 1'b1;
        repeat (2) @(posedge clk_mem_110_592);

        for (ram_index = 0; ram_index < RAM_TYPE_COUNT; ram_index = ram_index + 1) begin
            for (rtc_index = 0; rtc_index < 2; rtc_index = rtc_index + 1) begin
                for (color_index = 0; color_index < 2; color_index = color_index + 1) begin
                    check_case(
                        ram_types[ram_index],
                        expected_sizes[ram_index],
                        rtc_index[0],
                        color_index[0]
                    );
                end
            end
        end

        if (case_count != RAM_TYPE_COUNT * 4) begin
            $fatal(1, "footer matrix did not execute every case");
        end
        check_system_type_reset_lifecycle();
        $display(
            "PASS footer snapshot phase=%0d cases=%0d matrix=00/01/02/03/04/05/10/20/50 system_type=reset_latched",
            sys_phase_ps,
            case_count
        );
        $finish;
    end
endmodule
