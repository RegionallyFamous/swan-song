module wonderswan (
    input wire clk_sys_36_864,
    input wire clk_mem_110_592,

    // Host reset is synchronized separately for each consuming domain.
    input wire reset_n,
    input wire reset_n_sys,
    input wire pll_core_locked,
    input wire external_reset,

    // Data in
    input wire        ioctl_wr,
    input wire [24:0] ioctl_addr,
    input wire [15:0] ioctl_dout,
    input wire [24:0] rom_size_mem,
    input wire        rom_plan_valid_mem,
    input wire [24:0] rom_size_sys,
    input wire        rom_plan_valid_sys,
    output wire       rom_image_ready_mem,
    output wire       rom_validation_failed_mem,
    // 1 for B&W cart, 2 for color cart
    input wire [ 1:0] ext_cart_download,
    input wire [ 1:0] ext_cart_download_sys,

    output wire rom_write_complete,

    // BIOS in
    // 1 for B&W bios, 2 for color bios
    input wire [1:0] bios_download,

    input wire bios_wr,
    input wire [12:0] bios_addr,
    input wire [15:0] bios_dout,

    input wire [31:0] rtc_epoch_seconds,
    input wire rtc_epoch_valid,

    // Inputs
    input wire button_a,
    input wire button_b,
    input wire button_x,
    input wire button_y,
    input wire button_trig_l,
    input wire button_trig_r,
    input wire button_start,
    input wire button_select,
    input wire dpad_up,
    input wire dpad_down,
    input wire dpad_left,
    input wire dpad_right,
    input wire physical_input_blocked,

    // Settings
    input wire [1:0] configured_system,
    input wire use_cpu_turbo,
    input wire use_rewind_capture,

    input wire use_triple_buffer,
    input wire [1:0] configured_flickerblend,
    input wire [1:0] configured_orientation,
    input wire [1:0] configured_control_layout,
    input wire use_flip_horizontal,
    input wire configured_color_profile,

    input wire use_fastforward_sound,

    // Saves
    output logic [19:0] save_size_bytes,
    output wire has_rtc,
    // APF lifecycle evidence in clk_mem: footer metadata is committed once at
    // cartridge completion, and save initialization resolves after 008F.
    input wire load_complete,
    output reg save_metadata_commit,
    output wire save_initialization_resolved,
    output wire execution_ready,
    input wire sd_buff_wr,
    input wire sd_buff_rd,
    input wire [20:0] sd_buff_addr,
    output wire [15:0] sd_buff_din,
    input wire [15:0] sd_buff_dout,

    // Fixed-name console EEPROM slots. These are global machine state and are
    // intentionally independent of the cartridge save interface above.
    input wire console_eeprom_wr,
    input wire console_eeprom_rd,
    input wire console_eeprom_bank,
    input wire [10:0] console_eeprom_addr,
    output wire [15:0] console_eeprom_din,
    input wire [15:0] console_eeprom_dout,
    output wire console_eeprom_write_complete,

    output wire save_ram_write_complete,

    // Save states
    input wire ss_save,
    input wire ss_load,

    output wire [63:0] ss_din,
    input wire [63:0] ss_dout,
    output wire [25:0] ss_addr,
    output wire ss_rnw,
    output wire ss_req,
    output wire [7:0] ss_be,
    input wire ss_ack,

    output wire ss_busy,

    // SDRAM
    output wire [12:0] dram_a,
    output wire [ 1:0] dram_ba,
    inout  wire [15:0] dram_dq,
    output wire [ 1:0] dram_dqm,
    output wire        dram_clk,
    output wire        dram_cke,
    output wire        dram_ras_n,
    output wire        dram_cas_n,
    output wire        dram_we_n,

    // Video
    output wire hsync,
    output wire vsync,
    output wire hblank,
    output wire vblank,
    output wire [7:0] video_r,
    output wire [7:0] video_g,
    output wire [7:0] video_b,

    output wire is_vertical,
    output wire [2:0] scaler_slot_command,

    // Audio
    output wire [15:0] audio_l,
    output wire [15:0] audio_r
);

  wire                                                   [15:0] cart_addr;
  wire                                                          cart_rd;
  wire                                                          cart_wr;

  wire rom_prepare_busy_mem;
  wire rom_prepare_busy_sys;

  wire cart_download_external = |ext_cart_download;
  wire cart_download_sys_external = |ext_cart_download_sys;
  wire cart_download = cart_download_external || rom_prepare_busy_mem;
  wire cart_download_sys = cart_download_sys_external || rom_prepare_busy_sys;
  wire ioctl_download = cart_download_sys || |bios_download;

  // ext_cart_download is the clk_mem copy; ext_cart_download_sys is the
  // independently synchronized clk_sys copy.
  wire colorcart_download_sys = ext_cart_download_sys[1];
  // wire cart_download = ioctl_download && (filetype[5:0] == 6'h01 || filetype == 8'h80);
  // wire colorcart_download = ioctl_download && (filetype == 8'h01);
  // wire bios_download = ioctl_download && (filetype == 8'h00 || filetype == 8'h40);

  wire                                                          EXTRAM_doRefresh;
  wire                                                          EXTRAM_read;
  wire                                                          EXTRAM_write;
  wire                                                   [24:0] EXTRAM_addr;
  wire                                                   [15:0] EXTRAM_datawrite;
  wire                                                   [15:0] EXTRAM_dataread;
  wire                                                   [ 1:0] EXTRAM_be;

  wire                                                   [15:0] sdram_din;

  synch_3 rom_prepare_to_system (
      rom_prepare_busy_mem,
      rom_prepare_busy_sys,
      clk_sys_36_864
  );

  wire extra_data_addr;
  wire rtc_extra_write_complete;
  wire canonical_rtc_read;

  // Only the canonical 12-byte trailer is exposed on save reads.  Legacy
  // padding is load-only compatibility data and must never address past the
  // RTC snapshot or be written back into a newly flushed save.
  assign sd_buff_din = extra_data_addr ?
                       (canonical_rtc_read ? sd_buff_din_time : 16'h0000) :
                       save_is_sram_sys ? sdram_din : eeprom_din;

  wire clearing_save;
  wire clearing_sram;
  wire clear_sram_write;
  wire clear_eeprom_write;
  wire [19:0] clear_save_word_addr;

  // Save initialization is sequenced by clk_mem, but it holds the emulated
  // machine in reset in clk_sys. Assert that reset immediately and release it
  // only after the level has been observed low for three system clocks.
  (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED; -name PRESERVE_REGISTER ON" *)
  reg [2:0] clearing_save_sys_sync = 3'b111;
  always @(posedge clk_sys_36_864 or posedge clearing_save) begin
    if (clearing_save) begin
      clearing_save_sys_sync <= 3'b111;
    end else begin
      clearing_save_sys_sync <= {clearing_save_sys_sync[1:0], 1'b0};
    end
  end
  wire clearing_save_sys = clearing_save_sys_sync[2];

  wire cartridge_save_initialization_resolved;

  pocket_save_init save_initializer (
      .clk(clk_mem_110_592),
      .cart_download(cart_download),
      .load_complete(load_complete),
      .reset_n(reset_n),
      .save_payload_write(sd_buff_wr && !extra_data_addr),
      .save_is_sram(save_is_sram_mem),
      .save_is_eeprom(save_is_eeprom_mem),
      .save_size_bytes(save_size_bytes),
      .sram_write_ack(save_ram_ack),
      .clearing(clearing_save),
      .clearing_sram(clearing_sram),
      .clear_sram_write(clear_sram_write),
      .clear_eeprom_write(clear_eeprom_write),
      .clear_word_addr(clear_save_word_addr),
      .initialization_resolved(cartridge_save_initialization_resolved)
  );

  wire console_eeprom_clearing;
  wire console_eeprom_factory_write;
  wire [10:0] console_eeprom_factory_addr;
  wire [15:0] console_eeprom_factory_data;
  wire console_eeprom_initialization_resolved;

  pocket_console_eeprom_init console_eeprom_initializer (
      .clk(clk_mem_110_592),
      .cart_download(cart_download),
      .clearing(console_eeprom_clearing),
      .write_en(console_eeprom_factory_write),
      .physical_word_addr(console_eeprom_factory_addr),
      .write_data(console_eeprom_factory_data),
      .initialization_resolved(console_eeprom_initialization_resolved)
  );

  assign save_initialization_resolved =
      cartridge_save_initialization_resolved &&
      console_eeprom_initialization_resolved;

  wire save_ram_ack;

  // EEPROM is in BRAM. Will ack immediately after write
  // Overflow words are acknowledged and classified by the RTC save loader.
  assign save_ram_write_complete = extra_data_addr ? rtc_extra_write_complete : save_is_sram_mem ? save_ram_ack : sd_buff_wr;

  wire rom_sdram_req;
  wire rom_sdram_rnw;
  wire [24:0] rom_sdram_byte_addr;
  wire [15:0] rom_sdram_write_data;
  wire rom_sdram_ready;

  // Channel 1 is the only SDRAM path that is idle after cartridge setup.  Its
  // ownership boundary is live in the ROM path now, while the staging side is
  // deliberately tied off until the cross-domain pause/drain and serialized
  // state-engine adapters are complete.  This proves ROM pass-through without
  // making APF Memories capable of touching SDRAM prematurely.
  wire ch1_sdram_req;
  wire ch1_sdram_rnw;
  wire [24:0] ch1_sdram_word_addr;
  wire [15:0] ch1_sdram_write_data;
  wire ch1_sdram_ready;
  wire [15:0] ch1_sdram_read_data;
  wire ch3_sdram_ready;
  wire sdram_quiescent;

  apf_rom_loader_adapter rom_loader_adapter (
      .clk(clk_mem_110_592),
      .reset_n(pll_core_locked),
      .plan_valid(rom_plan_valid_mem),
      .raw_size(rom_size_mem),
      .cart_download(cart_download_external),
      .raw_write_en(ioctl_wr),
      .raw_write_addr(ioctl_addr),
      .raw_write_data(ioctl_dout),
      .raw_write_complete(rom_write_complete),
      .sdram_req(rom_sdram_req),
      .sdram_rnw(rom_sdram_rnw),
      .sdram_byte_addr(rom_sdram_byte_addr),
      .sdram_write_data(rom_sdram_write_data),
      .sdram_ready(rom_sdram_ready),
      .plan_non_power_of_two(),
      .mapped_mask(),
      .prepare_busy(rom_prepare_busy_mem),
      // prepare_busy is the production fail-closed reset contract.  The
      // same status is synchronized back to Chip32 for a clear load failure.
      .image_ready(rom_image_ready_mem),
      .validation_failed(rom_validation_failed_mem)
  );

  apf_sdram_channel1_mux channel1_owner (
      .clk(clk_mem_110_592),
      .reset_n(pll_core_locked),
      .stage_acquire(1'b0),
      .runtime_quiesced(1'b0),
      .stage_granted(),
      .protocol_error(),
      .rom_req(rom_sdram_req),
      .rom_rnw(rom_sdram_rnw),
      .rom_addr({1'b0, rom_sdram_byte_addr[24:1]}),
      .rom_write_data(rom_sdram_write_data),
      .rom_ready(rom_sdram_ready),
      .rom_read_data(),
      .stage_req(1'b0),
      .stage_rnw(1'b1),
      .stage_addr(25'd0),
      .stage_write_data(16'd0),
      .stage_ready(),
      .stage_read_data(),
      .sdram_req(ch1_sdram_req),
      .sdram_rnw(ch1_sdram_rnw),
      .sdram_addr(ch1_sdram_word_addr),
      .sdram_write_data(ch1_sdram_write_data),
      .sdram_ready(ch1_sdram_ready),
      .sdram_read_data(ch1_sdram_read_data)
  );

  wire ch2_sdram_req =
      (save_is_sram_mem && (sd_buff_rd || sd_buff_wr) && ~extra_data_addr) ||
      clear_sram_write;
  wire ch3_sdram_req = ~cart_download & (EXTRAM_read | EXTRAM_write);

  sdram sdram (
      .init(~pll_core_locked),
      .clk (clk_mem_110_592),

      .doRefresh(EXTRAM_doRefresh),

      .ch1_addr ({1'b0, ch1_sdram_word_addr}),
      .ch1_din  (ch1_sdram_write_data),
      .ch1_dout (ch1_sdram_read_data),
      .ch1_req  (ch1_sdram_req),
      .ch1_rnw  (ch1_sdram_rnw),
      .ch1_ready(ch1_sdram_ready),

      .ch2_addr(clearing_sram ? {4'b1000, clear_save_word_addr} : {4'b1000, sd_buff_addr[20:1]}),
      .ch2_din(clearing_sram ? 16'b0 : sd_buff_dout),
      .ch2_dout(sdram_din),
      .ch2_req  (ch2_sdram_req),
      .ch2_rnw(~clear_sram_write && ~sd_buff_wr),
      .ch2_ready(save_ram_ack),

      .ch3_addr(EXTRAM_addr[24:1]),
      .ch3_din (EXTRAM_datawrite),
      .ch3_dout(EXTRAM_dataread),
      .ch3_be  (EXTRAM_be),
      .ch3_req (ch3_sdram_req),
      .ch3_rnw (EXTRAM_read),
      .ch3_ready(ch3_sdram_ready),

      // These memory-domain observations are intentionally not yet allowed to
      // grant staging. They make the real channel-3 completion and complete
      // controller drain available to the upcoming pause/ownership coordinator.
      .quiescent(sdram_quiescent),

      // Actual SDRAM interface
      .SDRAM_DQ(dram_dq),
      .SDRAM_A(dram_a),
      .SDRAM_DQML(dram_dqm[0]),
      .SDRAM_DQMH(dram_dqm[1]),
      .SDRAM_BA(dram_ba),
      //   .SDRAM_nCS(),
      .SDRAM_nWE(dram_we_n),
      .SDRAM_nRAS(dram_ras_n),
      .SDRAM_nCAS(dram_cas_n),
      .SDRAM_CLK(dram_clk),
      .SDRAM_CKE(dram_cke)
  );

  reg [15:0] lastdata             [0:4];

  // The ROM footer is shifted in by clk_mem, but most of its consumers run on
  // clk_sys.  Capture the three lifecycle-static fields while the synchronized
  // system-domain download window is open, before doing any decode.  The final
  // clk_sys capture occurs only after the last legal clk_mem footer update has
  // settled.  Keep this snapshot across host Reset Enter/Exit so a running
  // title cannot lose its mapper or persistence identity.
  reg        footer_color_sys = 1'b0;
  reg [ 7:0] footer_romtype_sys = 8'h00;
  reg [ 7:0] footer_ramtype_sys = 8'h00;

  always @(posedge clk_sys_36_864) begin
    if (cart_download_sys) begin
      footer_color_sys   <= lastdata[4][8];
      footer_romtype_sys <= lastdata[1][15:8];
      footer_ramtype_sys <= lastdata[2][15:8];
    end
  end

  reg        ioctl_wr_1 = 0;
  reg        cart_download_mem_previous = 1'b0;

  reg        colorcart_downloaded;

  always @(posedge clk_mem_110_592) begin
    ioctl_wr_1 <= ioctl_wr;
    if (cart_download) begin
      if (ioctl_wr & ~ioctl_wr_1) begin
        // ioctl_wait  <= 1;
        lastdata[0] <= ioctl_dout;
        lastdata[1] <= lastdata[0];
        lastdata[2] <= lastdata[1];
        lastdata[3] <= lastdata[2];
        lastdata[4] <= lastdata[3];
      end
      // if (sdram_ack) ioctl_wait <= 0;
    end
    // else ioctl_wait <= 0;
  end

  // Snapshot the footer-derived persistence contract only after the final ROM
  // word is stable. The bundled metadata CDC in core_top holds this payload
  // atomically while crossing to the Pocket command domain.
  always @(posedge clk_mem_110_592) begin
    if (!pll_core_locked) begin
      cart_download_mem_previous <= 1'b0;
      save_metadata_commit <= 1'b0;
    end else begin
      save_metadata_commit <= cart_download_mem_previous && !cart_download;
      cart_download_mem_previous <= cart_download;
    end
  end

  reg old_download;
  reg [24:0] mask_addr;
  reg [24:0] planned_rom_size_sys;

  function automatic [24:0] next_power_of_two(input [24:0] size);
    begin
      if      (size <= 25'h0010000) next_power_of_two = 25'h0010000;
      else if (size <= 25'h0020000) next_power_of_two = 25'h0020000;
      else if (size <= 25'h0040000) next_power_of_two = 25'h0040000;
      else if (size <= 25'h0080000) next_power_of_two = 25'h0080000;
      else if (size <= 25'h0100000) next_power_of_two = 25'h0100000;
      else if (size <= 25'h0200000) next_power_of_two = 25'h0200000;
      else if (size <= 25'h0400000) next_power_of_two = 25'h0400000;
      else if (size <= 25'h0800000) next_power_of_two = 25'h0800000;
      else                           next_power_of_two = 25'h1000000;
    end
  endfunction

  wire rom_size_sys_non_power =
      (planned_rom_size_sys & (planned_rom_size_sys - 25'd1)) != 25'd0;

  always @(posedge clk_sys_36_864) begin
    if (!reset_n_sys) begin
      old_download <= 1'b0;
      colorcart_downloaded <= 1'b0;
      mask_addr <= 25'd0;
      planned_rom_size_sys <= 25'd0;
    end else begin
      old_download <= cart_download_sys;
      if (rom_plan_valid_sys)
        planned_rom_size_sys <= rom_size_sys;
      // Do not let the compact-ROM prefix/validation tail overwrite the model
      // detected during the real LOADF window after its external bit drops.
      if (cart_download_sys_external) begin
        colorcart_downloaded <= colorcart_download_sys;
      end
      if (old_download & ~cart_download_sys) begin
        if (rom_size_sys_non_power)
          mask_addr <= next_power_of_two(planned_rom_size_sys) - 25'd1;
        else
          // Preserve the inherited direct-loader mask derivation for every
          // conventional power-of-two image.
          mask_addr <= ioctl_addr[24:0] + 1'd1;
      end
    end
  end

  wire [15:0] Swan_AUDIO_L;
  wire [15:0] Swan_AUDIO_R;

  wire reset = ~reset_n_sys | cart_download_sys | clearing_save_sys | external_reset;
  assign execution_ready = ~reset;

  // System Type is a boot-time machine selection. Pocket may write the
  // persistent menu value while a title is already running, but changing the
  // active model live would immediately alter memory, DMA, EEPROM, and video
  // behavior. Capture the requested value only while the console is held in
  // reset; Reset Exit is already fenced until the complete settings snapshot
  // has crossed into this clock domain.
  reg [1:0] configured_system_active = 2'b00;
  always @(posedge clk_sys_36_864) begin
    if (reset) begin
      configured_system_active <= configured_system;
    end
  end

  reg paused;
  always_ff @(posedge clk_sys_36_864) begin
    paused <= syncpaused;
  end

  reg bios_wrbw;
  reg bios_wrcolor;
  always @(posedge clk_sys_36_864) begin
    bios_wrbw    <= 0;
    bios_wrcolor <= 0;
    if (|bios_download && bios_wr) begin
      if (bios_download[1] == 1'b1) bios_wrcolor <= 1'b1;
      else bios_wrbw <= 1'b1;
    end
  end

  wire isColor = (configured_system_active == 0) ?
                 (footer_color_sys | colorcart_downloaded) :
                 (configured_system_active == 2'b10);

  reg [79:0] time_dout = 80'd0;
  wire [79:0] time_din;
  assign time_din[42+32+:80-(42+32)] = '0;
  reg                                      RTC_load = 0;

  wire [ 7:0] ramtype_mem = lastdata[2][15:8];
  wire [ 7:0] ramtype_sys = footer_ramtype_sys;

  wire [15:0]                              eeprom_din;
  wire [15:0] internal_eeprom_din;
  wire internal_eeprom_host_access = console_eeprom_wr || console_eeprom_rd;
  wire internal_eeprom_req = console_eeprom_factory_write ||
                             internal_eeprom_host_access;
  wire internal_eeprom_bank = console_eeprom_factory_write ?
                              console_eeprom_factory_addr[10] :
                              console_eeprom_bank;
  wire [9:0] internal_eeprom_addr = console_eeprom_factory_write ?
                                    console_eeprom_factory_addr[9:0] :
                                    console_eeprom_addr[10:1];
  wire [15:0] internal_eeprom_dout = console_eeprom_factory_write ?
                                     console_eeprom_factory_data :
                                     console_eeprom_dout;
  wire internal_eeprom_rnw = console_eeprom_factory_write ? 1'b0 :
                             !console_eeprom_wr;

  assign console_eeprom_din = internal_eeprom_din;
  // A loader write is held until the title-only factory pass has completed;
  // this prevents an existing APF image from being overwritten by a late seed.
  assign console_eeprom_write_complete =
      console_eeprom_wr && !console_eeprom_clearing;

  wire vertical;
  wire control_key_y1;
  wire control_key_y2;
  wire control_key_y3;
  wire control_key_y4;
  wire control_key_a;
  wire control_key_b;
  apf_control_layout control_layout_mapper (
      .configured_layout(configured_control_layout),
      .native_vertical(vertical),
      .button_a(button_a),
      .button_b(button_b),
      .button_x(button_x),
      .button_y(button_y),
      .button_trig_l(button_trig_l),
      .button_trig_r(button_trig_r),
      .key_y1(control_key_y1),
      .key_y2(control_key_y2),
      .key_y3(control_key_y3),
      .key_y4(control_key_y4),
      .key_a(control_key_a),
      .key_b(control_key_b)
  );

  SwanTop SwanTop (
      .clk     (clk_sys_36_864),
      .clk_ram (clk_mem_110_592),
      .reset_in(reset),
      .pause_in(paused),
      .preserve_internal_eeprom(1'b1),

      // rom
      .EXTRAM_doRefresh(EXTRAM_doRefresh),
      .EXTRAM_read     (EXTRAM_read),
      .EXTRAM_write    (EXTRAM_write),
      .EXTRAM_be       (EXTRAM_be),
      .EXTRAM_addr     (EXTRAM_addr),
      .EXTRAM_datawrite(EXTRAM_datawrite),
      .EXTRAM_dataread (EXTRAM_dataread),

      .maskAddr(mask_addr[23:0]),
      // Footer byte -3 is the RTC field used by existing software metadata to
      // select Bandai 2003. The old romtype wiring incorrectly used byte -6
      // (the ROM-size code), which happened to be unused by memorymux.
      .romtype(footer_romtype_sys),
      .ramtype(ramtype_sys),
      .hasRTC(has_rtc_sys),

      // eeprom
      // .eepromWrite(eepromWrite),
      .eeprom_addr(clear_eeprom_write ? clear_save_word_addr[9:0] : sd_buff_addr[10:1]),
      .eeprom_din (clear_eeprom_write ? 16'hFFFF : sd_buff_dout),
      .eeprom_dout(eeprom_din),
      .eeprom_req (clear_eeprom_write || (save_is_eeprom_mem && (sd_buff_rd || sd_buff_wr) && ~extra_data_addr)),
      .eeprom_rnw (!clear_eeprom_write && ~sd_buff_wr),

      .internal_eeprom_bank(internal_eeprom_bank),
      .internal_eeprom_addr(internal_eeprom_addr),
      .internal_eeprom_din(internal_eeprom_dout),
      .internal_eeprom_dout(internal_eeprom_din),
      .internal_eeprom_req(internal_eeprom_req),
      .internal_eeprom_rnw(internal_eeprom_rnw),

      // bios
      .bios_wraddr (bios_addr),
      .bios_wrdata (bios_dout),
      .bios_wr     (bios_wrbw),
      .bios_wrcolor(bios_wrcolor),

      // Video 
      .vertical      (vertical),
      .pixel_out_addr(pixel_addr),  // integer range 0 to 16319; -- address for framebuffer
      .pixel_out_data(pixel_data),  // RGB data for framebuffer
      .pixel_out_we  (pixel_we),    // new pixel for framebuffer

      // audio 
      .audio_l(Swan_AUDIO_L),
      .audio_r(Swan_AUDIO_R),

      //settings
      .isColor    (isColor),
      .fastforward(fast_forward),
      .turbo      (use_cpu_turbo),

      // joystick
      .KeyY1   (control_key_y1),                        // Vertical X2
      .KeyY2   (control_key_y2),                        // Vertical X3
      .KeyY3   (control_key_y3),                        // Vertical X4
      .KeyY4   (control_key_y4),                        // Vertical X1
      .KeyX1   (dpad_up),                               // Horizontal up, vertical Y2
      .KeyX2   (dpad_right),                            // Horizontal right, vertical Y3
      .KeyX3   (dpad_down),                             // Horizontal down, vertical Y4
      .KeyX4   (dpad_left),                             // Horizontal left, vertical Y1
      .KeyStart(button_start),
      .KeyA    (control_key_a),
      .KeyB    (control_key_b),

      // RTC
      .RTC_timestampNew(rtc_epoch_valid),
      .RTC_timestampIn(rtc_epoch_seconds),
      .RTC_timestampSaved(time_dout[42+:32]),
      .RTC_savedtimeIn(time_dout[0+:42]),
      .RTC_saveLoaded(RTC_load),
      .RTC_timestampOut(time_din[42+:32]),
      .RTC_savedtimeOut(time_din[0+:42]),

      // savestates
      .increaseSSHeaderCount(1),
      .save_state           (ss_save),
      .load_state           (ss_load),
      .savestate_number     (0),

      .SAVE_out_Din(ss_din),  // data read from savestate
      .SAVE_out_Dout(ss_dout),  // data written to savestate
      .SAVE_out_Adr(ss_addr),  // all addresses are DWORD addresses!
      .SAVE_out_rnw(ss_rnw),  // read = 1, write = 0
      .SAVE_out_ena(ss_req),  // one cycle high for each action
      .SAVE_out_be(ss_be),
      .SAVE_out_done(ss_ack),  // should be one cycle high when write is done or read value is valid
      .SAVE_out_busy(ss_busy)

      // .rewind_on    (use_rewind_capture),
      // .rewind_active(use_rewind_capture & trigger_left)
  );

  assign audio_l = (fast_forward && ~use_fastforward_sound) ? 16'd0 : Swan_AUDIO_L;
  assign audio_r = (fast_forward && ~use_fastforward_sound) ? 16'd0 : Swan_AUDIO_R;

  ////////////////////////////  VIDEO  ////////////////////////////////////

  wire [14:0] pixel_addr;
  wire [11:0] pixel_data;
  wire pixel_we;

  // Menu writes arrive atomically in this clock domain, but applying a new
  // blend formula, color profile, or buffer policy mid-scanout would create a
  // visible horizontal seam. Latch all three only at the outgoing frame
  // boundary below.
  wire requested_buffervideo =
      use_triple_buffer | (configured_flickerblend != 2'd0);
  reg use_triple_buffer_applied = 1'b1;
  reg [1:0] flickerblend_applied = 2'd0;
  reg color_profile_applied = 1'b0;
  reg allow_direct_while_priming = 1'b0;
  wire buffervideo =
      use_triple_buffer_applied | (flickerblend_applied != 2'd0);

  reg hs, vs, hbl, vbl, ce_pix;
  reg [7:0] r, g, b;
  wire [8:0] x, y;
  reg [2:0] div;
  reg signed [3:0] HShift;
  reg signed [3:0] VShift;

  // TODO: This setting is not exposed for Pocket
  wire use_refresh_rate_75hz = 0;
  wire scanout_line_end;
  wire scanout_frame_boundary;
  wire producer_frame_done = pixel_we && pixel_addr == 32255;
  wire [2:0] framebank_write;
  wire [2:0] framebank_newest;
  wire [2:0] framebank_previous;
  wire [2:0] framebank_oldest;
  wire [1:0] framebank_valid_count;
  wire framebank_pending_valid;
  wire [2:0] framebank_pending;
  wire framebank_defer_candidate;
  wire framebank_protect_pending;

  // 397 * 258 pixels at 6.144 MHz is 59.984769 Hz.  The dedicated cadence
  // block keeps the APF raster exact and independently simulation-testable.
  apf_scanout_cadence scanout_cadence (
      .clk(clk_sys_36_864),
      .reset(reset),
      .pixel_enable(ce_pix),
      .x(x),
      .y(y),
      .line_end(scanout_line_end),
      .frame_boundary(scanout_frame_boundary)
  );

  always @(posedge clk_sys_36_864) begin
    if (reset) begin
      // Settings persist through Reset Enter. Keep their coherent values, but
      // do not expose retained RAM while the new title's history re-primes.
      use_triple_buffer_applied <= use_triple_buffer;
      flickerblend_applied <= configured_flickerblend;
      color_profile_applied <= configured_color_profile && isColor;
      allow_direct_while_priming <= 1'b0;
    end else if (scanout_frame_boundary) begin
      // A runtime direct->buffered transition may show the same direct bank
      // while the first complete buffered frame is prepared, avoiding a black
      // flash. history_valid_count changes only at this boundary, so the final
      // switch to immutable history is frame-atomic.
      if (!buffervideo && requested_buffervideo)
        allow_direct_while_priming <= 1'b1;
      else if (!requested_buffervideo || framebank_valid_count != 2'd0)
        allow_direct_while_priming <= 1'b0;
      use_triple_buffer_applied <= use_triple_buffer;
      flickerblend_applied <= configured_flickerblend;
      color_profile_applied <= configured_color_profile && isColor;
    end
  end

  apf_framebank_arbiter framebank_arbiter (
      .clk(clk_sys_36_864),
      .reset(reset),
      .enable(buffervideo),
      .producer_frame_done(producer_frame_done),
      .consumer_frame_boundary(scanout_frame_boundary),
      .defer_candidate(framebank_defer_candidate),
      .protect_pending(framebank_protect_pending),
      .write_bank(framebank_write),
      .pending_valid_out(framebank_pending_valid),
      .pending_bank_out(framebank_pending),
      .history_newest(framebank_newest),
      .history_previous(framebank_previous),
      .history_oldest(framebank_oldest),
      .history_valid_count(framebank_valid_count)
  );

  // Five banks provide three immutable blend/history frames, one pending
  // completed frame, and one live producer frame.  A faster 75 Hz producer can
  // supersede pending work without ever writing a bank visible to 59 Hz APF
  // scanout.  Each bank is split into native 10-bit and 2-bit M10K aspects by
  // apf_framebank_ram, reducing block fragmentation without changing the five
  // logical ownership roles. Disabling buffering returns to direct bank zero.
  wire syncpaused = 1'b0;

  reg [14:0] px_addr = 15'd0;
  wire [11:0] rgb0;
  wire [11:0] rgb1;
  wire [11:0] rgb2;
  wire [11:0] rgb3;
  wire [11:0] rgb4;

  apf_framebank_ram framebank_ram0 (
      .clk(clk_sys_36_864),
      .write_enable(pixel_we && framebank_write == 3'd0),
      .write_address(pixel_addr),
      .write_data(pixel_data),
      .read_address(px_addr),
      .read_data(rgb0)
  );

  apf_framebank_ram framebank_ram1 (
      .clk(clk_sys_36_864),
      .write_enable(pixel_we && framebank_write == 3'd1),
      .write_address(pixel_addr),
      .write_data(pixel_data),
      .read_address(px_addr),
      .read_data(rgb1)
  );

  apf_framebank_ram framebank_ram2 (
      .clk(clk_sys_36_864),
      .write_enable(pixel_we && framebank_write == 3'd2),
      .write_address(pixel_addr),
      .write_data(pixel_data),
      .read_address(px_addr),
      .read_data(rgb2)
  );

  apf_framebank_ram framebank_ram3 (
      .clk(clk_sys_36_864),
      .write_enable(pixel_we && framebank_write == 3'd3),
      .write_address(pixel_addr),
      .write_data(pixel_data),
      .read_address(px_addr),
      .read_data(rgb3)
  );

  apf_framebank_ram framebank_ram4 (
      .clk(clk_sys_36_864),
      .write_enable(pixel_we && framebank_write == 3'd4),
      .write_address(pixel_addr),
      .write_data(pixel_data),
      .read_address(px_addr),
      .read_data(rgb4)
  );

  function automatic [11:0] framebank_rgb;
    input [2:0] bank;
    begin
      case (bank)
        3'd1: framebank_rgb = rgb1;
        3'd2: framebank_rgb = rgb2;
        3'd3: framebank_rgb = rgb3;
        3'd4: framebank_rgb = rgb4;
        default: framebank_rgb = rgb0;
      endcase
    end
  endfunction

  wire [11:0] buffered_newest =
      framebank_valid_count >= 1 ? framebank_rgb(framebank_newest) : 12'd0;
  wire [11:0] buffered_previous =
      framebank_valid_count >= 2 ? framebank_rgb(framebank_previous) : buffered_newest;
  wire [11:0] buffered_oldest =
      framebank_valid_count >= 3 ? framebank_rgb(framebank_oldest) : buffered_previous;
  wire use_buffered_history = buffervideo && framebank_valid_count != 2'd0;
  wire presented_vertical;
  wire candidate_vertical;
  wire framebank_candidate_valid = framebank_protect_pending ?
      framebank_pending_valid : (producer_frame_done || framebank_pending_valid);
  wire [2:0] framebank_candidate = framebank_protect_pending ?
      framebank_pending :
      producer_frame_done ? framebank_write : framebank_pending;
  wire candidate_uses_live_orientation =
      !framebank_protect_pending && producer_frame_done;

  // Presentation follows the native orientation stored beside the frame that
  // owns the pixels. Control Layout is consumed only by the keypad mapper
  // above and must never enter this display-orientation path.
  apf_frame_orientation frame_orientation (
      .clk(clk_sys_36_864),
      .reset(reset),
      .producer_frame_done(producer_frame_done),
      .write_bank(framebank_write),
      .producer_orientation(vertical),
      .consumer_frame_boundary(scanout_frame_boundary),
      .buffered_frame_visible(use_buffered_history),
      .history_newest(framebank_newest),
      .candidate_bank(framebank_candidate),
      .candidate_uses_live_orientation(candidate_uses_live_orientation),
      .presented_orientation(presented_vertical),
      .candidate_orientation(candidate_vertical)
  );

  wire [2:0] expected_applied_slot;
  wire [2:0] presentation_slot;
  wire blank_presentation;
  apf_orientation_transition_guard orientation_transition (
      .clk(clk_sys_36_864),
      .reset(reset),
      .frame_boundary(scanout_frame_boundary),
      .buffered_mode(buffervideo),
      .current_frame_valid(use_buffered_history),
      .current_orientation(presented_vertical),
      .producer_orientation(vertical),
      .candidate_valid(framebank_candidate_valid),
      .candidate_orientation(candidate_vertical),
      .configured_orientation(configured_orientation),
      .landscape_180(use_flip_horizontal),
      .defer_candidate(framebank_defer_candidate),
      .protect_pending(framebank_protect_pending),
      .command_slot(scaler_slot_command),
      .expected_applied_slot(expected_applied_slot),
      .presentation_slot(presentation_slot),
      .blank_presentation(blank_presentation)
  );

  wire [11:0] direct_or_blank =
      (!buffervideo || allow_direct_while_priming) ? rgb0 : 12'd0;
  wire [11:0] blend_newest =
      use_buffered_history ? buffered_newest : direct_or_blank;
  wire [11:0] blend_previous =
      use_buffered_history ? buffered_previous : direct_or_blank;
  wire [11:0] blend_oldest =
      use_buffered_history ? buffered_oldest : direct_or_blank;
  wire [23:0] temporal_video_rgb;

  apf_temporal_blend temporal_blend (
      .mode(flickerblend_applied),
      .color_profile(color_profile_applied),
      .rgb_newest(blend_newest),
      .rgb_previous(blend_previous),
      .rgb_oldest(blend_oldest),
      .rgb_out(temporal_video_rgb)
  );

  always @(posedge clk_sys_36_864) begin

    if (use_refresh_rate_75hz) begin
      if (div < 4) div <= div + 1'd1;
      else div <= 0;  // 36.864 mhz / 5
    end else begin
      if (div < 5) div <= div + 1'd1;
      else div <= 0;  // 36.864 mhz / 6
    end

    ce_pix <= 0;
    if (!div) begin
      ce_pix <= 1;

      {r, g, b} <= blank_presentation ? 24'd0 : temporal_video_rgb;

      // Rotation is handled by the Pocket scaler
      if (x == 224 + 31) hbl <= 1;
      if (y == 66 + $signed(VShift)) vbl <= 0;
      if (y >= 66 + 144 + $signed(VShift)) vbl <= 1;

      if (x == 31) begin
        hbl <= 0;
      end

      if (x == 320 + $signed(HShift)) begin
        hs <= 1;
        if (y == 1) vs <= 1;
        if (y == 4) vs <= 0;
      end

      if (x == 320 + 32 + $signed(HShift)) hs <= 0;

    end

    if (ce_pix) begin

      if (vbl) begin
        px_addr <= 0;
      end else begin
        if (!hbl) begin
          px_addr <= px_addr + 1'd1;
        end
      end

      if (scanout_frame_boundary) begin
        // HShift         <= status[19:16];
        // VShift         <= status[23:20];
        HShift         <= 0;
        VShift         <= 0;
      end
    end
  end

  assign is_vertical = presented_vertical;

  assign video_r = r;
  assign video_g = g;
  assign video_b = b;

  assign hsync = hs;
  assign hblank = hbl;

  assign vsync = vs;
  assign vblank = vbl;

  ///////////////////////////// Fast Forward Latch /////////////////////////////////

  wire fast_forward;
  wire ff_on;

  // Host/external reset, a new cartridge, or loss of physical-input ownership
  // clears the complete gesture history.  PocketOS focus does not pause the
  // emulated console; it only removes physical controls and Fast Forward.
  apf_fast_forward_control fast_forward_control (
      .clk(clk_sys_36_864),
      .reset_n(reset_n_sys),
      .clear_state(external_reset || cart_download_sys || physical_input_blocked),
      .button_select(button_select),
      .fast_forward(fast_forward)
  );

  /////////////////////////  SRAM/EEPROM SAVE/LOAD  /////////////////////////////
  reg did_receive_sys_rtc = 0;
  reg is_save_rtc_ready = 0;
  reg rtc_load_delivered = 0;

  wire [20:0] rtc_data_offset = sd_buff_addr - save_size_bytes_sys;
  wire rtc_trailer_begin;
  wire rtc_payload_write;
  wire [2:0] rtc_payload_index;
  wire [15:0] rtc_payload_data;
  wire rtc_trailer_complete;

  // Canonical footer RTC value 01 declares the optional RTC trailer and
  // selects the Bandai 2003 register extensions in memorymux.
  wire has_rtc_mem = lastdata[1][15:8] == 8'h01;
  wire has_rtc_sys = footer_romtype_sys == 8'h01;
  assign has_rtc = has_rtc_mem;

  wire save_is_sram_mem = (ramtype_mem == 8'h01) || (ramtype_mem == 8'h02) ||
                          (ramtype_mem == 8'h03) || (ramtype_mem == 8'h04) ||
                          (ramtype_mem == 8'h05);
  wire save_is_eeprom_mem = (ramtype_mem == 8'h10) || (ramtype_mem == 8'h20) ||
                            (ramtype_mem == 8'h50);
  wire save_is_sram_sys = (ramtype_sys == 8'h01) || (ramtype_sys == 8'h02) ||
                          (ramtype_sys == 8'h03) || (ramtype_sys == 8'h04) ||
                          (ramtype_sys == 8'h05);

  always_comb begin
    save_size_bytes = 20'h00000;

    if (ramtype_mem == 8'h01) save_size_bytes = 20'h08000;
    if (ramtype_mem == 8'h02) save_size_bytes = 20'h08000;
    if (ramtype_mem == 8'h03) save_size_bytes = 20'h20000;
    if (ramtype_mem == 8'h04) save_size_bytes = 20'h40000;
    if (ramtype_mem == 8'h05) save_size_bytes = 20'h80000;
    // EEPROM sizes are exact bytes: 64, 1024, and 512 16-bit words.
    if (ramtype_mem == 8'h10) save_size_bytes = 20'h00080;
    if (ramtype_mem == 8'h20) save_size_bytes = 20'h00800;
    if (ramtype_mem == 8'h50) save_size_bytes = 20'h00400;
  end

  logic [19:0] save_size_bytes_sys;
  always_comb begin
    save_size_bytes_sys = 20'h00000;

    if (ramtype_sys == 8'h01) save_size_bytes_sys = 20'h08000;
    if (ramtype_sys == 8'h02) save_size_bytes_sys = 20'h08000;
    if (ramtype_sys == 8'h03) save_size_bytes_sys = 20'h20000;
    if (ramtype_sys == 8'h04) save_size_bytes_sys = 20'h40000;
    if (ramtype_sys == 8'h05) save_size_bytes_sys = 20'h80000;
    if (ramtype_sys == 8'h10) save_size_bytes_sys = 20'h00080;
    if (ramtype_sys == 8'h20) save_size_bytes_sys = 20'h00800;
    if (ramtype_sys == 8'h50) save_size_bytes_sys = 20'h00400;
  end

  apf_rtc_save_loader rtc_save_loader (
      .clk                 (clk_sys_36_864),
      .reset_title         (cart_download_sys),
      .has_rtc             (has_rtc_sys),
      .legacy_padded_type  ((ramtype_sys == 8'h10) || (ramtype_sys == 8'h50)),
      .save_size_bytes     (save_size_bytes_sys),
      .sd_buff_wr          (sd_buff_wr),
      .sd_buff_addr        (sd_buff_addr),
      .sd_buff_dout        (sd_buff_dout),
      .extra_data_addr     (extra_data_addr),
      .extra_write_complete(rtc_extra_write_complete),
      .rtc_trailer_begin   (rtc_trailer_begin),
      .rtc_payload_write   (rtc_payload_write),
      .rtc_payload_index   (rtc_payload_index),
      .rtc_payload_data    (rtc_payload_data),
      .rtc_trailer_complete(rtc_trailer_complete)
  );

  always @(posedge clk_sys_36_864) begin
    RTC_load <= 0;

    if (cart_download_sys) begin
      // Do not carry a previous title's trailer or readiness into this load.
      did_receive_sys_rtc <= 0;
      is_save_rtc_ready <= 0;
      rtc_load_delivered <= 0;
      time_dout <= 0;
    end else begin
      if (rtc_epoch_valid) begin
        // RTC received
        did_receive_sys_rtc <= 1;
      end

      if (did_receive_sys_rtc && is_save_rtc_ready && !rtc_load_delivered) begin
        // Both pieces belong to the current title. Emit a single load event.
        RTC_load <= 1;
        rtc_load_delivered <= 1;
      end

      if (rtc_trailer_begin) begin
        is_save_rtc_ready <= 0;
        rtc_load_delivered <= 0;
      end

      if (rtc_payload_write) begin
        time_dout[{rtc_payload_index, 4'b0000}+:16] <= rtc_payload_data;
      end

      if (rtc_trailer_complete) begin
        is_save_rtc_ready <= 1;
      end
    end
  end

  wire [127:0] time_din_h = {32'd0, time_din, "RT"};
  assign canonical_rtc_read = has_rtc_sys && (rtc_data_offset < 21'd12);
  wire [2:0] rtc_read_word_index = canonical_rtc_read ? rtc_data_offset[3:1] : 3'd0;
  // Word addressing (3:1), clamped before the variable part select.
  wire [15:0] sd_buff_din_time = time_din_h[{rtc_read_word_index, 4'b0000}+:16];

endmodule
