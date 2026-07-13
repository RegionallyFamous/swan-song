// Protected APF Memories staging coordinator.
//
// This module deliberately contains no storage.  It defines the control-plane
// contract for a full-size, random-access backend (the Pocket SDRAM integration
// is the intended implementation).  APF load data may change only that staging
// backend.  The live state engine cannot be started or read the staged payload
// until the complete SWAN envelope has been validated and every backend write
// has completed successfully.
//
// The production wrapper does not instantiate this module yet.  Memories and
// Sleep + Wake must remain disabled until the backend, clock crossings, and
// state-engine adapters are integrated and pass the documented hardware gates.
module apf_savestate_staging #(
    parameter [31:0] PAYLOAD_BYTES = 32'h0009_0300,
    parameter [31:0] FORMAT_ID = 32'h5753_0001
) (
    input  wire        clk,
    input  wire        reset_n,

    // A4 copy-in.  An upstream lossless bridge FIFO must retain load_write,
    // load_offset, and load_data until load_word_ready is asserted.
    input  wire        load_write,
    input  wire [27:0] load_offset,
    input  wire [31:0] load_data,
    output wire        load_word_ready,
    input  wire        load_finalize,
    output wire        load_copy_active,
    output wire        load_validated,
    output wire        load_error,
    output reg         load_busy,
    output reg         load_done,

    // The only live-mutation entry point.  A future state-engine adapter starts
    // a restore on this pulse, then reports one terminal result.
    output reg         restore_start,
    input  wire        restore_complete,
    input  wire        restore_error,

    // A0 capture-in.  capture_write uses payload-relative byte offsets and the
    // usual ready/valid contract.  capture_finalize is legal only with every
    // exact payload word already accepted (or with the final accepted word).
    input  wire        save_start,
    output reg         capture_start,
    input  wire        capture_write,
    input  wire [27:0] capture_offset,
    input  wire [31:0] capture_data,
    output wire        capture_word_ready,
    input  wire        capture_finalize,
    input  wire        capture_error,
    output reg         save_busy,
    output reg         save_ready,
    output reg         save_error,

    // Full-size staging backend write port.  stage_write_ready means the word
    // is durably accepted by the backend on this clock edge; stage_write_error
    // makes the active operation fail closed.
    output wire        stage_write_valid,
    output wire        stage_write_is_save,
    output wire [27:0] stage_write_offset,
    output wire [31:0] stage_write_data,
    input  wire        stage_write_ready,
    input  wire        stage_write_error,

    // Read authorization gates.  Header words are synthesized by the envelope;
    // payload requests remain relative to staging offset zero.  The external
    // backend adapter owns read latency and data return.
    input  wire        save_read_request,
    input  wire [27:0] save_read_offset,
    output wire        save_read_permitted,
    output wire        save_header_select,
    output wire [31:0] save_header_data,
    output wire        save_payload_read_request,
    output wire [27:0] save_payload_read_offset,

    input  wire        restore_read_request,
    input  wire [27:0] restore_read_offset,
    output wire        restore_read_permitted
);
  localparam [31:0] HEADER_BYTES = 32'd32;
  localparam [31:0] TOTAL_BYTES = PAYLOAD_BYTES + HEADER_BYTES;

  localparam [2:0] MODE_IDLE = 3'd0;
  localparam [2:0] MODE_SAVE = 3'd1;
  localparam [2:0] MODE_SAVE_READY = 3'd2;
  localparam [2:0] MODE_LOAD = 3'd3;
  localparam [2:0] MODE_RESTORE = 3'd4;

  reg [2:0] mode;

  wire envelope_payload_write;
  wire [27:0] envelope_payload_offset;
  wire [31:0] envelope_payload_data;
  wire envelope_load_active;
  wire envelope_load_complete;
  wire envelope_load_ready;
  wire envelope_load_error;
  wire envelope_save_header_select;
  wire [31:0] envelope_save_header_data;

  reg load_transport_error;
  reg load_backend_error;
  reg load_finalize_seen;
  reg restore_issued;
  reg restore_failed;
  reg [31:0] load_staged_bytes;

  // The envelope parser emits payload words one clock after their bridge word.
  // Hold one word if the backend cannot complete it immediately.  Upstream is
  // then backpressured before the parser can emit another word.
  reg pending_load_valid;
  reg [27:0] pending_load_offset;
  reg [31:0] pending_load_data;

  reg [31:0] save_expected_offset;

  wire mode_allows_load = (mode == MODE_IDLE) ||
                          (mode == MODE_SAVE_READY) ||
                          (mode == MODE_LOAD);
  wire load_payload_path_ready = !pending_load_valid &&
                                 (!envelope_payload_write || stage_write_ready);
  assign load_word_ready = mode_allows_load &&
                           ((load_offset < HEADER_BYTES[27:0]) ||
                            load_payload_path_ready);
  wire accepted_load_write = load_write && load_word_ready;

  apf_savestate_envelope #(
      .PAYLOAD_BYTES(PAYLOAD_BYTES),
      .FORMAT_ID(FORMAT_ID)
  ) envelope (
      .clk(clk),
      .reset_n(reset_n),
      .load_write(accepted_load_write),
      .load_offset(load_offset),
      .load_data(load_data),
      .load_finalize(load_finalize && mode == MODE_LOAD),
      .payload_write(envelope_payload_write),
      .payload_offset(envelope_payload_offset),
      .payload_data(envelope_payload_data),
      .load_active(envelope_load_active),
      .load_complete(envelope_load_complete),
      .load_ready(envelope_load_ready),
      .load_error(envelope_load_error),
      .save_offset(save_read_offset),
      .save_header_data(envelope_save_header_data),
      .save_header_select(envelope_save_header_select)
  );

  wire capture_offset_valid = capture_offset[1:0] == 2'b00 &&
                              capture_offset == save_expected_offset[27:0] &&
                              capture_offset < PAYLOAD_BYTES[27:0];
  assign capture_word_ready = mode == MODE_SAVE && !save_error &&
                              stage_write_ready;
  wire capture_accept = capture_write && capture_word_ready;
  wire capture_stage_valid = capture_write && mode == MODE_SAVE &&
                             !save_error && capture_offset_valid;
  wire capture_is_last = capture_accept && capture_offset_valid &&
                         capture_offset == PAYLOAD_BYTES[27:0] - 28'd4;
  wire capture_exact_at_finalize =
      (save_expected_offset == PAYLOAD_BYTES) || capture_is_last;
  wire capture_finalize_input_valid = !capture_write ||
                                      (capture_accept && capture_offset_valid);

  wire load_stage_direct = mode == MODE_LOAD && envelope_payload_write &&
                           !pending_load_valid;
  wire load_stage_valid = mode == MODE_LOAD &&
                          (pending_load_valid || load_stage_direct);

  assign stage_write_is_save = mode == MODE_SAVE;
  assign stage_write_valid = stage_write_is_save ? capture_stage_valid :
                             load_stage_valid;
  assign stage_write_offset = stage_write_is_save ? capture_offset :
                              pending_load_valid ? pending_load_offset :
                              envelope_payload_offset;
  assign stage_write_data = stage_write_is_save ? capture_data :
                            pending_load_valid ? pending_load_data :
                            envelope_payload_data;
  wire stage_write_accept = stage_write_valid && stage_write_ready;

  assign load_copy_active = mode == MODE_LOAD && envelope_load_active;
  assign load_error = envelope_load_error || load_transport_error ||
                      load_backend_error || restore_failed;
  assign load_validated = mode == MODE_LOAD && load_finalize_seen &&
                          envelope_load_ready && !load_error &&
                          !pending_load_valid &&
                          load_staged_bytes == PAYLOAD_BYTES;

  wire save_read_in_range = save_read_offset[1:0] == 2'b00 &&
                            save_read_offset < TOTAL_BYTES[27:0];
  assign save_read_permitted = save_read_request && save_ready &&
                               save_read_in_range;
  assign save_header_select = save_read_permitted &&
                              envelope_save_header_select;
  assign save_header_data = save_header_select ?
                            envelope_save_header_data : 32'd0;
  assign save_payload_read_request = save_read_permitted &&
                                     save_read_offset >= HEADER_BYTES[27:0];
  assign save_payload_read_offset = save_read_offset - HEADER_BYTES[27:0];

  assign restore_read_permitted = restore_read_request &&
                                  mode == MODE_RESTORE && !load_error &&
                                  restore_read_offset[1:0] == 2'b00 &&
                                  restore_read_offset < PAYLOAD_BYTES[27:0];

  always @(posedge clk or negedge reset_n) begin
    if (!reset_n) begin
      mode <= MODE_IDLE;
      load_transport_error <= 1'b0;
      load_backend_error <= 1'b0;
      load_finalize_seen <= 1'b0;
      restore_issued <= 1'b0;
      restore_failed <= 1'b0;
      load_staged_bytes <= 32'd0;
      pending_load_valid <= 1'b0;
      pending_load_offset <= 28'd0;
      pending_load_data <= 32'd0;
      load_busy <= 1'b0;
      load_done <= 1'b0;
      restore_start <= 1'b0;
      save_expected_offset <= 32'd0;
      capture_start <= 1'b0;
      save_busy <= 1'b0;
      save_ready <= 1'b0;
      save_error <= 1'b0;
    end else begin
      restore_start <= 1'b0;
      capture_start <= 1'b0;

      // Offset zero is also the transaction reset.  Starting an A4 copy makes
      // any older A0 image unavailable before its staging bytes are replaced.
      if (accepted_load_write && load_offset == 28'd0) begin
        mode <= MODE_LOAD;
        load_transport_error <= 1'b0;
        load_backend_error <= 1'b0;
        load_finalize_seen <= 1'b0;
        restore_issued <= 1'b0;
        restore_failed <= 1'b0;
        load_staged_bytes <= 32'd0;
        pending_load_valid <= 1'b0;
        load_busy <= 1'b1;
        load_done <= 1'b0;
        save_ready <= 1'b0;
      end else begin
        if (mode == MODE_LOAD) begin
          if (load_finalize)
            load_finalize_seen <= 1'b1;

          if (envelope_payload_write) begin
            if (pending_load_valid) begin
              load_transport_error <= 1'b1;
            end else if (stage_write_ready) begin
              load_staged_bytes <= load_staged_bytes + 32'd4;
              if (stage_write_error)
                load_backend_error <= 1'b1;
            end else begin
              pending_load_valid <= 1'b1;
              pending_load_offset <= envelope_payload_offset;
              pending_load_data <= envelope_payload_data;
            end
          end else if (pending_load_valid && stage_write_accept) begin
            pending_load_valid <= 1'b0;
            load_staged_bytes <= load_staged_bytes + 32'd4;
            if (stage_write_error)
              load_backend_error <= 1'b1;
          end

          if (load_finalize_seen && (envelope_load_error ||
                                     load_transport_error ||
                                     load_backend_error))
            load_busy <= 1'b0;

          if (load_validated && !restore_issued) begin
            mode <= MODE_RESTORE;
            restore_issued <= 1'b1;
            restore_start <= 1'b1;
            load_busy <= 1'b1;
          end
        end

        if (mode == MODE_RESTORE) begin
          if (restore_error) begin
            restore_failed <= 1'b1;
            load_busy <= 1'b0;
            load_done <= 1'b0;
            mode <= MODE_IDLE;
          end else if (restore_complete) begin
            load_busy <= 1'b0;
            load_done <= 1'b1;
            mode <= MODE_IDLE;
          end
        end
      end

      if (save_start) begin
        // A simultaneous offset-zero A4 word owns the shared staging image.
        // Reject A0 rather than starting two writers with contradictory status.
        if ((mode == MODE_IDLE || mode == MODE_SAVE_READY) &&
            !(accepted_load_write && load_offset == 28'd0)) begin
          mode <= MODE_SAVE;
          save_expected_offset <= 32'd0;
          save_busy <= 1'b1;
          save_ready <= 1'b0;
          save_error <= 1'b0;
          capture_start <= 1'b1;
          load_done <= 1'b0;
        end else begin
          save_error <= 1'b1;
        end
      end

      if (mode == MODE_SAVE) begin
        if (capture_error) begin
          save_error <= 1'b1;
          save_busy <= 1'b0;
          mode <= MODE_IDLE;
        end else if (capture_accept) begin
          if (!capture_offset_valid) begin
            save_error <= 1'b1;
            save_busy <= 1'b0;
            mode <= MODE_IDLE;
          end else if (stage_write_error) begin
            save_error <= 1'b1;
            save_busy <= 1'b0;
            mode <= MODE_IDLE;
          end else begin
            save_expected_offset <= save_expected_offset + 32'd4;
          end
        end

        if (capture_finalize) begin
          if (capture_exact_at_finalize && !save_error && !capture_error &&
              capture_finalize_input_valid &&
              !(stage_write_accept && stage_write_error)) begin
            save_busy <= 1'b0;
            save_ready <= 1'b1;
            mode <= MODE_SAVE_READY;
          end else begin
            save_busy <= 1'b0;
            save_ready <= 1'b0;
            save_error <= 1'b1;
            mode <= MODE_IDLE;
          end
        end
      end
    end
  end

`ifndef SYNTHESIS
  initial begin
    if (PAYLOAD_BYTES == 0 || PAYLOAD_BYTES[1:0] != 2'b00)
      $fatal(1, "PAYLOAD_BYTES must be a nonzero multiple of four");
    if (TOTAL_BYTES > 32'h0fff_ffff)
      $fatal(1, "staged blob exceeds APF bridge window");
  end
`endif
endmodule
