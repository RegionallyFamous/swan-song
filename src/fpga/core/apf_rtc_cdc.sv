// Bundled-data request/acknowledge CDC for APF's RTC epoch notification.
// The source payload is captured before the request toggle crosses domains and
// remains stable until the acknowledgement returns.
module apf_rtc_cdc (
    input  wire        reset_n,

    input  wire        clk_74a,
    input  wire [31:0] rtc_epoch_src,
    input  wire        rtc_valid_src,
    output wire        rtc_busy_src,
    output reg         rtc_rejected_src,

    input  wire        clk_sys,
    output reg  [31:0] rtc_epoch_dst,
    output reg         rtc_valid_dst
);
  // Asynchronously assert reset in each domain, but release it only on that
  // domain's clock. This lets the bridge use the always-on PLL lock reset
  // rather than APF Reset Enter/Exit, because command 0090 is delivered while
  // the emulated console is intentionally still held in reset.
  (* ASYNC_REG = "TRUE" *) reg [1:0] source_reset_sync = 2'b00;
  (* ASYNC_REG = "TRUE" *) reg [1:0] destination_reset_sync = 2'b00;
  wire source_reset_n = source_reset_sync[1];
  wire destination_reset_n = destination_reset_sync[1];

  always @(posedge clk_74a or negedge reset_n) begin
    if (!reset_n) source_reset_sync <= 2'b00;
    else source_reset_sync <= {source_reset_sync[0], 1'b1};
  end

  always @(posedge clk_sys or negedge reset_n) begin
    if (!reset_n) destination_reset_sync <= 2'b00;
    else destination_reset_sync <= {destination_reset_sync[0], 1'b1};
  end

  reg [31:0] rtc_epoch_hold;
  reg request_toggle;

  (* ASYNC_REG = "TRUE" *) reg acknowledge_meta;
  (* ASYNC_REG = "TRUE" *) reg acknowledge_sync;

  reg acknowledge_toggle;
  (* ASYNC_REG = "TRUE" *) reg request_meta;
  (* ASYNC_REG = "TRUE" *) reg request_sync;
  reg request_seen;

  assign rtc_busy_src = request_toggle != acknowledge_sync;

  always @(posedge clk_74a or negedge source_reset_n) begin
    if (!source_reset_n) begin
      rtc_epoch_hold <= 32'h0000_0000;
      request_toggle <= 1'b0;
      acknowledge_meta <= 1'b0;
      acknowledge_sync <= 1'b0;
      rtc_rejected_src <= 1'b0;
    end else begin
      acknowledge_meta <= acknowledge_toggle;
      acknowledge_sync <= acknowledge_meta;
      rtc_rejected_src <= 1'b0;

      if (rtc_valid_src) begin
        if (!rtc_busy_src) begin
          rtc_epoch_hold <= rtc_epoch_src;
          request_toggle <= ~request_toggle;
        end else begin
          // The producer violated backpressure.  Reject it explicitly instead
          // of silently replacing the payload currently crossing domains.
          rtc_rejected_src <= 1'b1;
        end
      end
    end
  end

  always @(posedge clk_sys or negedge destination_reset_n) begin
    if (!destination_reset_n) begin
      request_meta <= 1'b0;
      request_sync <= 1'b0;
      request_seen <= 1'b0;
      acknowledge_toggle <= 1'b0;
      rtc_epoch_dst <= 32'h0000_0000;
      rtc_valid_dst <= 1'b0;
    end else begin
      request_meta <= request_toggle;
      request_sync <= request_meta;
      rtc_valid_dst <= 1'b0;

      if (request_sync != request_seen) begin
        rtc_epoch_dst <= rtc_epoch_hold;
        rtc_valid_dst <= 1'b1;
        request_seen <= request_sync;
        acknowledge_toggle <= request_sync;
      end
    end
  end
endmodule
