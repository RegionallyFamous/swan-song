`timescale 1ns/1ps

// Frame-atomic Analogue Pocket scaler-slot command transport.
//
// The system-domain orientation guard supplies one of three legal video.json
// slots:
//   0: landscape
//   1: portrait
//   2: landscape rotated 180 degrees
// Portrait takes precedence, so the legacy landscape-180 option can never
// turn a portrait title upside down.
//
// The commanded slot crosses clock domains as bundled data. slot_hold_sys is
// frozen before request_toggle_sys changes and remains frozen until the video
// domain acknowledges capture. The destination may receive several updates
// during one frame, but exposes only the newest complete update and only at a
// frame boundary. The emitted EOL command applies to the following APF frame;
// the orientation guard separately tracks that expected-applied state.
// Only slots 0-2 are legal here, so the acknowledged payload remains two bits;
// the APF-facing output zero-extends it to the protocol's three-bit field.
// Integration must constrain the complete two-bit bundled payload in
// the same way as the other acknowledged bundled-data CDCs in this core.
module apf_scaler_selector (
    input  wire        reset_n,

    input  wire        clk_sys,
    input  wire [2:0]  requested_slot_sys,
    output wire        update_pending_sys,

    input  wire        clk_video,
    input  wire        frame_start_video,
    output reg  [2:0]  scaler_slot_video,
    output wire [23:0] eol_word_video
);
  localparam [1:0] SLOT_LANDSCAPE = 2'd0;
  localparam [1:0] SLOT_PORTRAIT = 2'd1;
  localparam [1:0] SLOT_LANDSCAPE_180 = 2'd2;

  function automatic [1:0] legal_video_slot;
    input [2:0] candidate;
    begin
      case (candidate)
        3'd1: legal_video_slot = SLOT_PORTRAIT;
        3'd2: legal_video_slot = SLOT_LANDSCAPE_180;
        default: legal_video_slot = SLOT_LANDSCAPE;
      endcase
    end
  endfunction

  // Assertion is asynchronous so an interrupted update is discarded in both
  // domains. Release is synchronized independently to each destination.
  (* ASYNC_REG = "TRUE" *) reg [1:0] sys_reset_sync;
  (* ASYNC_REG = "TRUE" *) reg [1:0] video_reset_sync;
  wire sys_reset_n = sys_reset_sync[1];
  wire video_reset_n = video_reset_sync[1];

  always @(posedge clk_sys or negedge reset_n) begin
    if (!reset_n) sys_reset_sync <= 2'b00;
    else sys_reset_sync <= {sys_reset_sync[0], 1'b1};
  end

  always @(posedge clk_video or negedge reset_n) begin
    if (!reset_n) video_reset_sync <= 2'b00;
    else video_reset_sync <= {video_reset_sync[0], 1'b1};
  end

  wire [1:0] desired_slot_sys = legal_video_slot(requested_slot_sys);

  reg [1:0] slot_hold_sys;
  reg request_toggle_sys;
  (* ASYNC_REG = "TRUE" *) reg acknowledge_meta_sys;
  (* ASYNC_REG = "TRUE" *) reg acknowledge_sync_sys;

  reg acknowledge_toggle_video;
  (* ASYNC_REG = "TRUE" *) reg request_meta_video;
  (* ASYNC_REG = "TRUE" *) reg request_sync_video;
  reg request_seen_video;

  wire transfer_busy_sys = request_toggle_sys != acknowledge_sync_sys;
  assign update_pending_sys = transfer_busy_sys ||
      (desired_slot_sys != slot_hold_sys);

  // This is a level-tracking CDC rather than a pulse interface. If the user
  // changes the setting while a transfer is busy, the newest level is sent as
  // soon as the acknowledgement returns. Returning to the already-sent level
  // naturally cancels the pending follow-up.
  always @(posedge clk_sys or negedge sys_reset_n) begin
    if (!sys_reset_n) begin
      slot_hold_sys <= SLOT_LANDSCAPE;
      request_toggle_sys <= 1'b0;
      acknowledge_meta_sys <= 1'b0;
      acknowledge_sync_sys <= 1'b0;
    end else begin
      acknowledge_meta_sys <= acknowledge_toggle_video;
      acknowledge_sync_sys <= acknowledge_meta_sys;

      if (!transfer_busy_sys && desired_slot_sys != slot_hold_sys) begin
        slot_hold_sys <= desired_slot_sys;
        request_toggle_sys <= ~request_toggle_sys;
      end
    end
  end

  reg [1:0] pending_slot_video;
  reg pending_valid_video;
  wire request_arrived_video = request_sync_video != request_seen_video;

  always @(posedge clk_video or negedge video_reset_n) begin
    if (!video_reset_n) begin
      request_meta_video <= 1'b0;
      request_sync_video <= 1'b0;
      request_seen_video <= 1'b0;
      acknowledge_toggle_video <= 1'b0;
      pending_slot_video <= SLOT_LANDSCAPE;
      pending_valid_video <= 1'b0;
      scaler_slot_video <= {1'b0, SLOT_LANDSCAPE};
    end else begin
      request_meta_video <= request_toggle_sys;
      request_sync_video <= request_meta_video;

      if (request_arrived_video) begin
        // The request synchronizer delay guarantees that slot_hold_sys was
        // stable before this one canonical bundled capture. It replaces any
        // older pending update; a coincident frame boundary deliberately holds
        // the current slot and applies this newest complete value next frame.
        request_seen_video <= request_sync_video;
        acknowledge_toggle_video <= request_sync_video;
        pending_slot_video <= slot_hold_sys;
        pending_valid_video <= 1'b1;
      end

      if (frame_start_video && !request_arrived_video) begin
        if (pending_valid_video) begin
          scaler_slot_video <= {1'b0, pending_slot_video};
          pending_valid_video <= 1'b0;
        end
      end
    end
  end

  // APF end-of-line command: parameter [23:13] is the scaler slot, reserved
  // [12:3] is zero, and function [2:0] is 000 (Set Scaler Slot).
  assign eol_word_video = {8'd0, scaler_slot_video, 10'd0, 3'b000};
endmodule
