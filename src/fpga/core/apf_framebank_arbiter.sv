`timescale 1ns/1ps

// Tear-safe ownership for five same-clock WonderSwan frame banks.
//
// Up to three immutable completed frames are owned by scanout. The producer
// owns one write bank and may publish one pending frame. If it outruns Pocket
// scanout, a newer completed frame supersedes the pending frame and the old
// pending bank becomes the next writer. A visible bank is never overwritten.
module apf_framebank_arbiter (
    input  wire       clk,
    input  wire       reset,
    input  wire       enable,
    input  wire       producer_frame_done,
    input  wire       consumer_frame_boundary,
    output wire [2:0] write_bank,
    output reg  [2:0] history_newest,
    output reg  [2:0] history_previous,
    output reg  [2:0] history_oldest,
    output reg  [1:0] history_valid_count
);
  reg [2:0] write_bank_state;
  reg [2:0] pending_bank;
  reg pending_valid;

  assign write_bank = enable ? write_bank_state : 3'd0;

  function automatic [2:0] choose_free_bank;
    input [2:0] exclude0;
    input [2:0] exclude1;
    input       exclude1_valid;
    input [2:0] exclude2;
    input       exclude2_valid;
    input [2:0] exclude3;
    input       exclude3_valid;
    integer candidate;
    reg found;
    begin
      choose_free_bank = 3'd0;
      found = 1'b0;
      for (candidate = 0; candidate < 5; candidate = candidate + 1) begin
        if (!found && candidate[2:0] != exclude0 &&
            (!exclude1_valid || candidate[2:0] != exclude1) &&
            (!exclude2_valid || candidate[2:0] != exclude2) &&
            (!exclude3_valid || candidate[2:0] != exclude3)) begin
          choose_free_bank = candidate[2:0];
          found = 1'b1;
        end
      end
    end
  endfunction

  always @(posedge clk) begin
    if (reset || !enable) begin
      write_bank_state <= 3'd0;
      pending_bank <= 3'd0;
      pending_valid <= 1'b0;
      history_newest <= 3'd0;
      history_previous <= 3'd0;
      history_oldest <= 3'd0;
      history_valid_count <= 2'd0;
    end else begin
      case ({producer_frame_done, consumer_frame_boundary})
        2'b10: begin
          pending_bank <= write_bank_state;
          pending_valid <= 1'b1;
          if (pending_valid) begin
            // The older pending frame was never visible, so it is safe to
            // recycle when a newer complete producer frame supersedes it.
            write_bank_state <= pending_bank;
          end else begin
            write_bank_state <= choose_free_bank(
                write_bank_state,
                history_newest,
                history_valid_count >= 2'd1,
                history_previous,
                history_valid_count >= 2'd2,
                history_oldest,
                history_valid_count >= 2'd3
            );
          end
        end

        2'b01: begin
          if (pending_valid) begin
            history_newest <= pending_bank;
            if (history_valid_count >= 2'd1)
              history_previous <= history_newest;
            if (history_valid_count >= 2'd2)
              history_oldest <= history_previous;
            if (history_valid_count < 2'd3)
              history_valid_count <= history_valid_count + 1'd1;
            pending_valid <= 1'b0;
          end
        end

        2'b11: begin
          // Consume the just-completed writer directly. An older pending frame
          // is deliberately dropped and recycled as the next writer.
          history_newest <= write_bank_state;
          if (history_valid_count >= 2'd1)
            history_previous <= history_newest;
          if (history_valid_count >= 2'd2)
            history_oldest <= history_previous;
          if (history_valid_count < 2'd3)
            history_valid_count <= history_valid_count + 1'd1;

          if (pending_valid) begin
            write_bank_state <= pending_bank;
          end else begin
            // New history is completed + the two previously newest banks.
            write_bank_state <= choose_free_bank(
                write_bank_state,
                history_newest,
                history_valid_count >= 2'd1,
                history_previous,
                history_valid_count >= 2'd2,
                3'd0,
                1'b0
            );
          end
          pending_valid <= 1'b0;
        end

        default: begin
        end
      endcase
    end
  end
endmodule
