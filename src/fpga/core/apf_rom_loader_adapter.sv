`timescale 1ns/1ps

// Compact non-power-of-two WonderSwan ROM adapter.
//
// WonderSwan headers live in the final 16 bytes, so compact images are aligned
// to the top of the next power-of-two mapper aperture.  Only this opt-in path
// is arbitrated: conventional power-of-two loads remain a direct connection
// between data_loader and SDRAM.
module apf_rom_loader_adapter (
    input  wire        clk,
    input  wire        reset_n,

    input  wire        plan_valid,
    input  wire [24:0] raw_size,
    input  wire        cart_download,

    input  wire        raw_write_en,
    input  wire [24:0] raw_write_addr,
    input  wire [15:0] raw_write_data,
    output wire        raw_write_complete,

    output wire        sdram_req,
    output wire        sdram_rnw,
    output wire [24:0] sdram_byte_addr,
    output wire [15:0] sdram_write_data,
    input  wire        sdram_ready,

    output reg         plan_non_power_of_two,
    output wire [23:0] mapped_mask,
    output wire        prepare_busy,
    output wire        image_ready,
    output reg         validation_failed
);
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

  function automatic [24:0] header_size_bytes(input [7:0] code);
    begin
      case (code)
        8'h00: header_size_bytes = 25'h0020000;  // 128 KiB
        8'h01: header_size_bytes = 25'h0040000;  // 256 KiB
        8'h02: header_size_bytes = 25'h0080000;  // 512 KiB
        8'h03: header_size_bytes = 25'h0100000;  // 1 MiB
        8'h04: header_size_bytes = 25'h0200000;  // 2 MiB
        8'h05: header_size_bytes = 25'h0300000;  // 3 MiB
        8'h06: header_size_bytes = 25'h0400000;  // 4 MiB
        8'h07: header_size_bytes = 25'h0600000;  // 6 MiB
        8'h08: header_size_bytes = 25'h0800000;  // 8 MiB
        8'h09: header_size_bytes = 25'h1000000;  // 16 MiB
        default: header_size_bytes = 25'd0;
      endcase
    end
  endfunction

  function automatic supported_save_type(input [7:0] code);
    begin
      supported_save_type =
          (code == 8'h00) || (code == 8'h01) || (code == 8'h02) ||
          (code == 8'h03) || (code == 8'h04) || (code == 8'h05) ||
          (code == 8'h10) || (code == 8'h20) || (code == 8'h50);
    end
  endfunction

  reg [24:0] raw_size_latched;
  reg [24:0] aperture_size;
  reg [24:0] prefix_size;
  reg [24:0] fill_addr;
  reg fill_active;
  reg fill_due;
  reg plan_loaded;
  reg staged_plan_valid;
  reg [24:0] staged_raw_size;

  localparam [1:0] STATE_IDLE = 2'd0;
  localparam [1:0] STATE_RAW  = 2'd1;
  localparam [1:0] STATE_FILL = 2'd2;
  localparam [1:0] STATE_GAP  = 2'd3;
  reg [1:0] state;

  reg cart_download_previous;
  reg load_end_seen;
  reg validation_passed;
  reg stream_valid;
  reg footer_contract_valid;
  reg [4:0] footer_fields_seen;
  reg checksum_seen;
  reg [15:0] checksum;
  reg [24:0] expected_raw_addr;

  wire download_rise = cart_download && !cart_download_previous;
  wire activate_plan = cart_download && (!plan_loaded || download_rise) &&
                       (plan_valid || staged_plan_valid);
  wire [24:0] activation_size = plan_valid ? raw_size : staged_raw_size;
  // Combinationally revoke the preceding plan as soon as a new asynchronous
  // download rise is visible; do not wait one clock edge to block a held word.
  wire plan_active = plan_loaded && !download_rise;
  wire direct_path = plan_active && !plan_non_power_of_two;
  wire [24:0] aligned_raw_addr = raw_write_addr + prefix_size;
  wire [24:0] declared_header_size = header_size_bytes(raw_write_data[7:0]);
  wire header_size_matches = (declared_header_size != 25'd0) &&
      ((declared_header_size == raw_size_latched) ||
       (declared_header_size == aperture_size));

  assign mapped_mask = aperture_size[23:0] - 24'd1;
  // A compact image remains in reset for its entire load and until the
  // falling-edge validation decision. In particular, do not expose a low
  // pulse between asynchronous cart_download deassertion and load_end_seen.
  assign prepare_busy = (cart_download && !plan_active) ||
                        (plan_non_power_of_two &&
                         (fill_active || !load_end_seen ||
                          !validation_passed));
  assign image_ready = direct_path ||
                       (load_end_seen && validation_passed && !fill_active);

  // LOADF may present and hold its first word before the accepted-size CDC
  // pulse reaches this clock.  Fail closed until that per-load plan is active;
  // data_loader retains the word because raw_write_complete remains low.
  assign raw_write_complete = !plan_active ? 1'b0 :
                              direct_path ? sdram_ready :
                              ((state == STATE_RAW) && sdram_ready);
  assign sdram_req = !plan_active ? 1'b0 :
                     direct_path ? raw_write_en :
                     ((state == STATE_RAW) || (state == STATE_FILL));
  assign sdram_rnw = direct_path ? !cart_download : 1'b0;
  assign sdram_byte_addr = direct_path ? raw_write_addr :
                           (state == STATE_RAW ? aligned_raw_addr : fill_addr);
  assign sdram_write_data = direct_path ? raw_write_data :
                            (state == STATE_RAW ? raw_write_data : 16'hffff);

  always @(posedge clk or negedge reset_n) begin
    if (!reset_n) begin
      raw_size_latched <= 25'd0;
      aperture_size <= 25'h0010000;
      prefix_size <= 25'd0;
      fill_addr <= 25'd0;
      fill_active <= 1'b0;
      fill_due <= 1'b0;
      plan_loaded <= 1'b0;
      staged_plan_valid <= 1'b0;
      staged_raw_size <= 25'd0;
      plan_non_power_of_two <= 1'b0;
      state <= STATE_IDLE;
      cart_download_previous <= 1'b0;
      load_end_seen <= 1'b0;
      validation_passed <= 1'b0;
      validation_failed <= 1'b0;
      stream_valid <= 1'b0;
      footer_contract_valid <= 1'b0;
      footer_fields_seen <= 5'd0;
      checksum_seen <= 1'b0;
      checksum <= 16'd0;
      expected_raw_addr <= 25'd0;
    end else begin
      cart_download_previous <= cart_download;

      if (plan_valid) begin
        staged_raw_size <= raw_size;
        staged_plan_valid <= 1'b1;
      end

      if (download_rise) begin
        // Invalidate the preceding image's plan before accepting any word of
        // this load.  A plan that arrived early remains staged for activation.
        plan_loaded <= 1'b0;
        plan_non_power_of_two <= 1'b0;
        state <= STATE_IDLE;
        fill_active <= 1'b0;
        fill_due <= 1'b0;
        load_end_seen <= 1'b0;
        validation_passed <= 1'b0;
        validation_failed <= 1'b0;
        stream_valid <= 1'b0;
        footer_contract_valid <= 1'b0;
        footer_fields_seen <= 5'd0;
        checksum_seen <= 1'b0;
        checksum <= 16'd0;
        expected_raw_addr <= 25'd0;
      end

      if (activate_plan) begin
        raw_size_latched <= activation_size;
        aperture_size <= next_power_of_two(activation_size);
        prefix_size <= next_power_of_two(activation_size) - activation_size;
        fill_addr <= 25'd0;
        fill_active <=
            (activation_size & (activation_size - 25'd1)) != 25'd0;
        fill_due <= 1'b0;
        plan_loaded <= 1'b1;
        staged_plan_valid <= 1'b0;
        plan_non_power_of_two <=
            (activation_size & (activation_size - 25'd1)) != 25'd0;
        state <= STATE_IDLE;
        load_end_seen <= 1'b0;
        validation_passed <= 1'b0;
        validation_failed <= 1'b0;
        stream_valid <= 1'b1;
        footer_contract_valid <= 1'b1;
        footer_fields_seen <= 5'd0;
        checksum_seen <= 1'b0;
        checksum <= 16'd0;
        expected_raw_addr <= 25'd0;
      end else if (!download_rise && plan_loaded &&
                   plan_non_power_of_two) begin
        case (state)
          STATE_IDLE: begin
            // Accept the first held data_loader word immediately so its small
            // CDC FIFO cannot overflow. Thereafter service one prefix word
            // after every accepted raw word while fill remains active. Since
            // every compact size is greater than half its aperture, prefix
            // words are fewer than raw words and fill completes before EOF,
            // even under a continuously held raw stream. Idle gaps may advance
            // fill faster without delaying a pending first/raw word.
            if (fill_active && (fill_due || !raw_write_en)) begin
              state <= STATE_FILL;
            end else if (raw_write_en) begin
              state <= STATE_RAW;

              if ((raw_write_addr != expected_raw_addr) ||
                  (raw_write_addr >= raw_size_latched))
                stream_valid <= 1'b0;
              expected_raw_addr <= raw_write_addr + 25'd2;

              if (raw_write_addr == raw_size_latched - 25'd16) begin
                footer_fields_seen[0] <= 1'b1;
                if (raw_write_data[7:0] != 8'hea)
                  footer_contract_valid <= 1'b0;
              end
              if (raw_write_addr == raw_size_latched - 25'd12) begin
                footer_fields_seen[1] <= 1'b1;
                // Byte 5 is the high byte of this little-endian word; only
                // its low nibble (raw_write_data[11:8]) is reserved.
                if (raw_write_data[11:8] != 4'd0)
                  footer_contract_valid <= 1'b0;
              end
              if (raw_write_addr == raw_size_latched - 25'd10) begin
                footer_fields_seen[2] <= 1'b1;
                if (raw_write_data[15:9] != 7'd0)
                  footer_contract_valid <= 1'b0;
              end
              if (raw_write_addr == raw_size_latched - 25'd6) begin
                footer_fields_seen[3] <= 1'b1;
                if (!header_size_matches ||
                    !supported_save_type(raw_write_data[15:8]))
                  footer_contract_valid <= 1'b0;
              end
              if (raw_write_addr == raw_size_latched - 25'd4) begin
                footer_fields_seen[4] <= 1'b1;
                // This core's SDRAM cartridge path is 16-bit.  Mapper values
                // 0/1 are the implemented 2001/2003 footer encodings.
                if (!raw_write_data[2] || (raw_write_data[15:8] > 8'h01))
                  footer_contract_valid <= 1'b0;
              end

              if (raw_write_addr == raw_size_latched - 25'd2) begin
                checksum_seen <= 1'b1;
                if (raw_write_data != checksum)
                  stream_valid <= 1'b0;
              end else begin
                checksum <= checksum + {8'd0, raw_write_data[7:0]} +
                            {8'd0, raw_write_data[15:8]};
              end
            end
          end

          STATE_RAW: begin
            if (sdram_ready) begin
              fill_due <= fill_active;
              state <= STATE_GAP;
            end
          end

          STATE_FILL: begin
            if (sdram_ready) begin
              if (fill_addr == prefix_size - 25'd2) begin
                fill_active <= 1'b0;
              end else begin
                fill_addr <= fill_addr + 25'd2;
              end
              fill_due <= 1'b0;
              state <= STATE_GAP;
            end
          end

          STATE_GAP: begin
            // SDRAM detects request edges.  Guarantee one fully low cycle
            // before selecting the next raw or prefix transaction.
            state <= STATE_IDLE;
          end
        endcase

        if (cart_download_previous && !cart_download) begin
          load_end_seen <= 1'b1;
          if (stream_valid && footer_contract_valid &&
              (&footer_fields_seen) && checksum_seen &&
              (expected_raw_addr == raw_size_latched)) begin
            validation_passed <= 1'b1;
          end else begin
            validation_failed <= 1'b1;
          end
        end
      end
    end
  end
endmodule
