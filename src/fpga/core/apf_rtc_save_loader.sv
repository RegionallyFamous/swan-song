// RTC save-trailer loader with compatibility for the inherited Pocket layout.
//
// Older builds exposed every external EEPROM as 2 KiB, so type 0x10 and 0x50
// saves put their 12-byte RTC trailer at byte 2048.  Current saves put it
// immediately after the cartridge's exact EEPROM capacity.  All writes beyond
// the exact payload are acknowledged here: padding is discarded, while a
// canonical or legacy "RT" header selects the five following payload words.
module apf_rtc_save_loader (
    input  wire        clk,
    input  wire        reset_title,
    input  wire        has_rtc,
    input  wire        legacy_padded_type,
    input  wire [19:0] save_size_bytes,
    input  wire        sd_buff_wr,
    input  wire [20:0] sd_buff_addr,
    input  wire [15:0] sd_buff_dout,

    output wire        extra_data_addr,
    output reg         extra_write_complete = 1'b0,
    output reg         rtc_trailer_begin = 1'b0,
    output reg         rtc_payload_write = 1'b0,
    output reg  [ 2:0] rtc_payload_index = 3'd0,
    output reg  [15:0] rtc_payload_data = 16'd0,
    output reg         rtc_trailer_complete = 1'b0
);

  localparam [20:0] LEGACY_RTC_BASE = 21'd2048;

  reg        trailer_active = 1'b0;
  reg [20:0] trailer_base = 21'd0;

  wire canonical_header = has_rtc && sd_buff_wr &&
                          (sd_buff_addr == {1'b0, save_size_bytes}) &&
                          (sd_buff_dout == "RT");
  wire legacy_header = has_rtc && legacy_padded_type && sd_buff_wr &&
                       (sd_buff_addr == LEGACY_RTC_BASE) &&
                       (sd_buff_dout == "RT");
  wire [20:0] trailer_offset = sd_buff_addr - trailer_base;
  wire payload_offset = (trailer_offset >= 21'd2) &&
                        (trailer_offset <= 21'd10) &&
                        !trailer_offset[0];

  assign extra_data_addr = sd_buff_addr >= {1'b0, save_size_bytes};

  always @(posedge clk) begin
    extra_write_complete <= 1'b0;
    rtc_trailer_begin <= 1'b0;
    rtc_payload_write <= 1'b0;
    rtc_trailer_complete <= 1'b0;

    if (reset_title) begin
      trailer_active <= 1'b0;
      trailer_base <= 21'd0;
      rtc_payload_index <= 3'd0;
      rtc_payload_data <= 16'd0;
    end else begin
      // The memory-domain data_loader holds sd_buff_wr until this system-domain
      // acknowledgement returns.  Ack only after this clock has sampled the
      // address/data, so the slower RTC parser cannot miss a short write pulse.
      if (extra_data_addr && sd_buff_wr)
        extra_write_complete <= 1'b1;

      if (legacy_header || canonical_header) begin
        // The absolute legacy header takes precedence if the predicates ever
        // overlap.  A later valid header intentionally restarts the trailer,
        // so an accidental "RT" in padding cannot hijack the final RTC.
        trailer_active <= 1'b1;
        trailer_base <= legacy_header ? LEGACY_RTC_BASE
                                      : {1'b0, save_size_bytes};
        rtc_trailer_begin <= 1'b1;
      end else if (trailer_active && sd_buff_wr && payload_offset) begin
        rtc_payload_write <= 1'b1;
        rtc_payload_index <= trailer_offset[3:1] - 3'd1;
        rtc_payload_data <= sd_buff_dout;

        if (trailer_offset == 21'd10) begin
          trailer_active <= 1'b0;
          rtc_trailer_complete <= 1'b1;
        end
      end
    end
  end

endmodule
