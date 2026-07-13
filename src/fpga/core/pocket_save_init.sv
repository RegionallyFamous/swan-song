// One-shot initialization for cartridge-backed persistence memories.
//
// APF loads a save, when one exists, while reset_n is low.  On the first
// Reset Exit for a newly downloaded cartridge, initialize an absent save to
// the medium's native blank value.  The lifecycle is armed by cart_download,
// not by every Reset Enter/Exit pair, so shutdown and later reset cycles cannot
// erase data written by the running game.
module pocket_save_init (
    input  wire        clk,
    input  wire        cart_download,
    input  wire        reset_n,
    input  wire        save_payload_write,
    input  wire        save_is_sram,
    input  wire        save_is_eeprom,
    input  wire [19:0] save_size_bytes,
    input  wire        sram_write_ack,

    output wire        clearing,
    output wire        clearing_sram,
    output wire        clear_sram_write,
    output wire        clear_eeprom_write,
    output reg  [19:0] clear_word_addr = 20'd0
);

  localparam [1:0] CLEAR_IDLE = 2'd0;
  localparam [1:0] CLEAR_SRAM_START = 2'd1;
  localparam [1:0] CLEAR_SRAM_WAIT_ACK = 2'd2;
  localparam [1:0] CLEAR_EEPROM_WRITE = 2'd3;

  reg [1:0] state = CLEAR_IDLE;
  reg prev_reset_n = 1'b0;
  reg prev_sram_write_ack = 1'b0;
  reg save_loaded = 1'b0;
  reg init_pending = 1'b1;

  wire [19:0] save_word_count = save_size_bytes >> 1;

  assign clearing = state != CLEAR_IDLE;
  assign clearing_sram = state == CLEAR_SRAM_START || state == CLEAR_SRAM_WAIT_ACK;
  assign clear_sram_write = state == CLEAR_SRAM_WAIT_ACK;
  assign clear_eeprom_write = state == CLEAR_EEPROM_WRITE;

  always @(posedge clk) begin
    prev_reset_n <= reset_n;
    prev_sram_write_ack <= sram_write_ack;

    if (cart_download) begin
      // A cartridge load is the only event that arms fresh-save handling.
      state <= CLEAR_IDLE;
      clear_word_addr <= 20'd0;
      save_loaded <= 1'b0;
      init_pending <= 1'b1;
    end else begin
      if (save_payload_write) begin
        // RTC-only or malformed trailer traffic must not suppress payload init.
        save_loaded <= 1'b1;
      end

      case (state)
        CLEAR_IDLE: begin
          if (reset_n && !prev_reset_n && init_pending) begin
            init_pending <= 1'b0;
            clear_word_addr <= 20'd0;

            // Include a payload write coincident with Reset Exit.  APF normally
            // completes the slot transfer first, but this keeps the decision
            // fail-safe at the lifecycle boundary as well.
            if (!(save_loaded || save_payload_write) && save_word_count != 0) begin
              if (save_is_sram) begin
                state <= CLEAR_SRAM_START;
              end else if (save_is_eeprom) begin
                state <= CLEAR_EEPROM_WRITE;
              end
            end
          end
        end

        CLEAR_SRAM_START: begin
          state <= CLEAR_SRAM_WAIT_ACK;
        end

        CLEAR_SRAM_WAIT_ACK: begin
          if (sram_write_ack && !prev_sram_write_ack) begin
            if (clear_word_addr + 20'd1 >= save_word_count) begin
              state <= CLEAR_IDLE;
            end else begin
              clear_word_addr <= clear_word_addr + 20'd1;
              state <= CLEAR_SRAM_START;
            end
          end
        end

        CLEAR_EEPROM_WRITE: begin
          // The external EEPROM is FPGA block RAM on this port.  One word is
          // committed on this edge while clear_eeprom_write is asserted.
          if (clear_word_addr + 20'd1 >= save_word_count) begin
            state <= CLEAR_IDLE;
          end else begin
            clear_word_addr <= clear_word_addr + 20'd1;
          end
        end
      endcase
    end
  end

endmodule
