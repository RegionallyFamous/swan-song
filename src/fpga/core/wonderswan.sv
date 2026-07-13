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

    // Settings
    input wire [1:0] configured_system,
    input wire use_cpu_turbo,
    input wire use_rewind_capture,

    input wire use_triple_buffer,
    input wire [1:0] configured_flickerblend,

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

    // Audio
    output wire [15:0] audio_l,
    output wire [15:0] audio_r
);

  wire                                                   [15:0] cart_addr;
  wire                                                          cart_rd;
  wire                                                          cart_wr;

  wire ioctl_download = cart_download_sys || |bios_download;

  // ext_cart_download is the clk_mem copy; ext_cart_download_sys is the
  // independently synchronized clk_sys copy.
  wire cart_download = |ext_cart_download;
  wire cart_download_sys = |ext_cart_download_sys;
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

  wire extra_data_addr;
  wire rtc_extra_write_complete;
  wire canonical_rtc_read;

  // Only the canonical 12-byte trailer is exposed on save reads.  Legacy
  // padding is load-only compatibility data and must never address past the
  // RTC snapshot or be written back into a newly flushed save.
  assign sd_buff_din = extra_data_addr ?
                       (canonical_rtc_read ? sd_buff_din_time : 16'h0000) :
                       saveIsSRAM ? sdram_din : eeprom_din;

  wire clearing_save;
  wire clearing_sram;
  wire clear_sram_write;
  wire clear_eeprom_write;
  wire [19:0] clear_save_word_addr;

  // Save initialization is sequenced by clk_mem, but it holds the emulated
  // machine in reset in clk_sys. Assert that reset immediately and release it
  // only after the level has been observed low for three system clocks.
  (* ASYNC_REG = "TRUE" *) reg [2:0] clearing_save_sys_sync = 3'b000;
  always @(posedge clk_sys_36_864 or posedge clearing_save) begin
    if (clearing_save) begin
      clearing_save_sys_sync <= 3'b111;
    end else begin
      clearing_save_sys_sync <= {clearing_save_sys_sync[1:0], 1'b0};
    end
  end
  wire clearing_save_sys = clearing_save_sys_sync[2];

  pocket_save_init save_initializer (
      .clk(clk_mem_110_592),
      .cart_download(cart_download),
      .load_complete(load_complete),
      .reset_n(reset_n),
      .save_payload_write(sd_buff_wr && !extra_data_addr),
      .save_is_sram(saveIsSRAM),
      .save_is_eeprom(saveIsEEPROM),
      .save_size_bytes(save_size_bytes),
      .sram_write_ack(save_ram_ack),
      .clearing(clearing_save),
      .clearing_sram(clearing_sram),
      .clear_sram_write(clear_sram_write),
      .clear_eeprom_write(clear_eeprom_write),
      .clear_word_addr(clear_save_word_addr),
      .initialization_resolved(save_initialization_resolved)
  );

  wire save_ram_ack;

  // EEPROM is in BRAM. Will ack immediately after write
  // Overflow words are acknowledged and classified by the RTC save loader.
  assign save_ram_write_complete = extra_data_addr ? rtc_extra_write_complete : saveIsSRAM ? save_ram_ack : sd_buff_wr;

  sdram sdram (
      .init(~pll_core_locked),
      .clk (clk_mem_110_592),

      .doRefresh(EXTRAM_doRefresh),

      .ch1_addr (ioctl_addr[24:1]),
      .ch1_din  (ioctl_dout),
      .ch1_req  (ioctl_wr),
      .ch1_rnw  (cart_download ? 1'b0 : 1'b1),
      .ch1_ready(rom_write_complete),
      // .ch1_dout (),

      .ch2_addr(clearing_sram ? {4'b1000, clear_save_word_addr} : {4'b1000, sd_buff_addr[20:1]}),
      .ch2_din(clearing_sram ? 16'b0 : sd_buff_dout),
      .ch2_dout(sdram_din),
      .ch2_req  ((saveIsSRAM && (sd_buff_rd || sd_buff_wr) && ~extra_data_addr) || clear_sram_write),
      .ch2_rnw(~clear_sram_write && ~sd_buff_wr),
      .ch2_ready(save_ram_ack),

      .ch3_addr(EXTRAM_addr[24:1]),
      .ch3_din (EXTRAM_datawrite),
      .ch3_dout(EXTRAM_dataread),
      .ch3_be  (EXTRAM_be),
      .ch3_req (~cart_download & (EXTRAM_read | EXTRAM_write)),
      .ch3_rnw (EXTRAM_read),
      // .ch3_ready(),

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

  always @(posedge clk_sys_36_864) begin
    if (!reset_n_sys) begin
      old_download <= 1'b0;
      colorcart_downloaded <= 1'b0;
      mask_addr <= 25'd0;
    end else begin
      old_download <= cart_download_sys;
      if (cart_download_sys) begin
        colorcart_downloaded <= colorcart_download_sys;
      end
      if (old_download & ~cart_download_sys) begin
        mask_addr <= ioctl_addr[24:0] + 1'd1;
      end
    end
  end

  wire [15:0] Swan_AUDIO_L;
  wire [15:0] Swan_AUDIO_R;

  wire reset = ~reset_n_sys | cart_download_sys | clearing_save_sys | external_reset;
  assign execution_ready = ~reset;

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

  wire isColor = (configured_system == 0) ? (lastdata[4][8] | colorcart_downloaded) : (configured_system == 2'b10);

  reg [79:0] time_dout = 80'd0;
  wire [79:0] time_din;
  assign time_din[42+32+:80-(42+32)] = '0;
  reg                                      RTC_load = 0;

  wire [ 7:0] ramtype = lastdata[2][15:8];

  wire [15:0]                              eeprom_din;

  SwanTop SwanTop (
      .clk     (clk_sys_36_864),
      .clk_ram (clk_mem_110_592),
      .reset_in(reset),
      .pause_in(paused),

      // rom
      .EXTRAM_doRefresh(EXTRAM_doRefresh),
      .EXTRAM_read     (EXTRAM_read),
      .EXTRAM_write    (EXTRAM_write),
      .EXTRAM_be       (EXTRAM_be),
      .EXTRAM_addr     (EXTRAM_addr),
      .EXTRAM_datawrite(EXTRAM_datawrite),
      .EXTRAM_dataread (EXTRAM_dataread),

      .maskAddr(mask_addr[23:0]),
      .romtype(lastdata[2][7:0]),
      .ramtype(ramtype),
      .hasRTC(has_rtc),  // Unused

      // eeprom
      // .eepromWrite(eepromWrite),
      .eeprom_addr(clear_eeprom_write ? clear_save_word_addr[9:0] : sd_buff_addr[10:1]),
      .eeprom_din (clear_eeprom_write ? 16'hFFFF : sd_buff_dout),
      .eeprom_dout(eeprom_din),
      .eeprom_req (clear_eeprom_write || (saveIsEEPROM && (sd_buff_rd || sd_buff_wr) && ~extra_data_addr)),
      .eeprom_rnw (!clear_eeprom_write && ~sd_buff_wr),

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
      .KeyY1   (vertical ? button_x : button_trig_l),   // Vertical X2
      .KeyY2   (vertical ? button_a : button_trig_r),   // Vertical X3
      .KeyY3   (vertical ? button_b : button_x),        // Vertical X4
      .KeyY4   (vertical ? button_y : button_y),        // Vertical X1
      .KeyX1   (dpad_up),                               // Horizontal up, vertical Y2
      .KeyX2   (dpad_right),                            // Horizontal right, vertical Y3
      .KeyX3   (dpad_down),                             // Horizontal down, vertical Y4
      .KeyX4   (dpad_left),                             // Horizontal left, vertical Y1
      .KeyStart(button_start),
      .KeyA    (~vertical ? button_a : button_trig_l),
      .KeyB    (~vertical ? button_b : button_trig_r),

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
  // blend formula or buffer policy mid-scanout would still create a visible
  // horizontal seam. Latch both only at the outgoing frame boundary below.
  wire requested_buffervideo =
      use_triple_buffer | (configured_flickerblend != 2'd0);
  reg use_triple_buffer_applied = 1'b1;
  reg [1:0] flickerblend_applied = 2'd0;
  reg allow_direct_while_priming = 1'b0;
  wire buffervideo =
      use_triple_buffer_applied | (flickerblend_applied != 2'd0);

  wire vertical;
  reg hs, vs, hbl, vbl, ce_pix;
  reg [7:0] r, g, b;
  reg [8:0] x, y;
  reg [2:0] div;
  reg signed [3:0] HShift;
  reg signed [3:0] VShift;

  // TODO: This setting is not exposed for Pocket
  wire use_refresh_rate_75hz = 0;
  wire scanout_line_end =
      (x >= 400 && ~use_refresh_rate_75hz) ||
      (x >= 378 && use_refresh_rate_75hz);
  wire scanout_frame_boundary = ce_pix && scanout_line_end && y >= 257;
  wire producer_frame_done = pixel_we && pixel_addr == 32255;
  wire [2:0] framebank_write;
  wire [2:0] framebank_newest;
  wire [2:0] framebank_previous;
  wire [2:0] framebank_oldest;
  wire [1:0] framebank_valid_count;

  always @(posedge clk_sys_36_864) begin
    if (reset) begin
      // Settings persist through Reset Enter. Keep their coherent values, but
      // do not expose retained RAM while the new title's history re-primes.
      use_triple_buffer_applied <= use_triple_buffer;
      flickerblend_applied <= configured_flickerblend;
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
    end
  end

  apf_framebank_arbiter framebank_arbiter (
      .clk(clk_sys_36_864),
      .reset(reset),
      .enable(buffervideo),
      .producer_frame_done(producer_frame_done),
      .consumer_frame_boundary(scanout_frame_boundary),
      .write_bank(framebank_write),
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

      {r, g, b} <= temporal_video_rgb;

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

      x <= x + 1'd1;
      if (scanout_line_end) begin
        x <= 0;
        if (~&y) y <= y + 1'd1;
        if (y >= 257) begin
          y <= 0;

          // HShift         <= status[19:16];
          // VShift         <= status[23:20];
          HShift         <= 0;
          VShift         <= 0;
        end
      end
    end
  end

  assign is_vertical = vertical;

  assign video_r = r;
  assign video_g = g;
  assign video_b = b;

  assign hsync = hs;
  assign hblank = hbl;

  assign vsync = vs;
  assign vblank = vbl;

  ///////////////////////////// Fast Forward Latch /////////////////////////////////

  reg fast_forward;
  reg ff_latch;

  wire fastforward = button_select && !ioctl_download;
  wire ff_on;

  always @(posedge clk_sys_36_864) begin : ffwd
    reg last_ffw;
    reg ff_was_held;
    longint ff_count;

    last_ffw <= fastforward;

    if (fastforward) ff_count <= ff_count + 1;

    if (~last_ffw & fastforward) begin
      ff_latch <= 0;
      ff_count <= 0;
    end

    if ((last_ffw & ~fastforward)) begin  // 32mhz clock, 0.2 seconds
      ff_was_held <= 0;

      if (ff_count < 6400000 && ~ff_was_held) begin
        ff_was_held <= 1;
        ff_latch <= 1;
      end
    end

    fast_forward <= (fastforward | ff_latch);
  end

  /////////////////////////  SRAM/EEPROM SAVE/LOAD  /////////////////////////////
  reg did_receive_sys_rtc = 0;
  reg is_save_rtc_ready = 0;
  reg rtc_load_delivered = 0;

  wire [20:0] rtc_data_offset = sd_buff_addr - save_size_bytes;
  wire rtc_trailer_begin;
  wire rtc_payload_write;
  wire [2:0] rtc_payload_index;
  wire [15:0] rtc_payload_data;
  wire rtc_trailer_complete;

  // Cartridge footer bit 8 declares the optional RTC persistence trailer.
  assign has_rtc = lastdata[1][8];

  wire saveIsSRAM = (ramtype == 8'h01) || (ramtype == 8'h02) || (ramtype == 8'h03) || (ramtype == 8'h04) || (ramtype == 8'h05);
  wire saveIsEEPROM = (ramtype == 8'h10) || (ramtype == 8'h20) || (ramtype == 8'h50);

  always_comb begin
    save_size_bytes = 20'h00000;

    if (ramtype == 8'h01) save_size_bytes = 20'h08000;
    if (ramtype == 8'h02) save_size_bytes = 20'h08000;
    if (ramtype == 8'h03) save_size_bytes = 20'h20000;
    if (ramtype == 8'h04) save_size_bytes = 20'h40000;
    if (ramtype == 8'h05) save_size_bytes = 20'h80000;
    // EEPROM sizes are exact bytes: 64, 1024, and 512 16-bit words.
    if (ramtype == 8'h10) save_size_bytes = 20'h00080;
    if (ramtype == 8'h20) save_size_bytes = 20'h00800;
    if (ramtype == 8'h50) save_size_bytes = 20'h00400;
  end

  apf_rtc_save_loader rtc_save_loader (
      .clk                 (clk_sys_36_864),
      .reset_title         (cart_download_sys),
      .has_rtc             (has_rtc),
      .legacy_padded_type  ((ramtype == 8'h10) || (ramtype == 8'h50)),
      .save_size_bytes     (save_size_bytes),
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
  assign canonical_rtc_read = has_rtc && (rtc_data_offset < 21'd12);
  wire [2:0] rtc_read_word_index = canonical_rtc_read ? rtc_data_offset[3:1] : 3'd0;
  // Word addressing (3:1), clamped before the variable part select.
  wire [15:0] sd_buff_din_time = time_din_h[{rtc_read_word_index, 4'b0000}+:16];

endmodule
