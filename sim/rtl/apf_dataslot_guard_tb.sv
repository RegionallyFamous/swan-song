`timescale 1ns/1ps

module apf_dataslot_guard_tb;
  reg clk = 1'b0;
  always #5 clk = ~clk;

  reg reset_n = 1'b0;
  reg request_valid = 1'b0;
  reg request_write = 1'b0;
  reg [15:0] request_id = 16'd0;
  reg [47:0] request_size = 48'd0;
  wire request_ack;
  wire [1:0] request_result;
  wire request_busy;

  wire [15:0] policy_slot_id;
  reg policy_slot_known;
  reg policy_allow_read;
  reg policy_allow_write;
  reg policy_bounds_ready;
  reg [1:0] policy_size_mode;
  reg [47:0] policy_exact_size;
  reg [47:0] policy_min_size;
  reg [47:0] policy_max_size;
  reg policy_capture_length;

  reg force_bounds_not_ready = 1'b0;
  reg read_loader_ready = 1'b1;
  reg write_loader_ready = 1'b1;
  reg captured_length_clear = 1'b0;
  wire captured_save_length_valid;
  wire [15:0] captured_save_id;
  wire [47:0] captured_save_length;
  wire captured_save_length_updated;

  integer errors = 0;
  integer ack_count = 0;

  localparam [1:0] RESULT_READY = 2'd0;
  localparam [1:0] RESULT_NOT_ALLOWED = 2'd1;
  localparam [1:0] RESULT_CHECK_LATER = 2'd2;

  apf_dataslot_guard dut (
      .clk(clk),
      .reset_n(reset_n),
      .request_valid(request_valid),
      .request_write(request_write),
      .request_id(request_id),
      .request_size(request_size),
      .request_ack(request_ack),
      .request_result(request_result),
      .request_busy(request_busy),
      .policy_slot_id(policy_slot_id),
      .policy_slot_known(policy_slot_known),
      .policy_allow_read(policy_allow_read),
      .policy_allow_write(policy_allow_write),
      .policy_bounds_ready(policy_bounds_ready),
      .policy_size_mode(policy_size_mode),
      .policy_exact_size(policy_exact_size),
      .policy_min_size(policy_min_size),
      .policy_max_size(policy_max_size),
      .policy_capture_length(policy_capture_length),
      .read_loader_ready(read_loader_ready),
      .write_loader_ready(write_loader_ready),
      .captured_length_clear(captured_length_clear),
      .captured_save_length_valid(captured_save_length_valid),
      .captured_save_id(captured_save_id),
      .captured_save_length(captured_save_length),
      .captured_save_length_updated(captured_save_length_updated)
  );

  // Representative WonderSwan integration policy.  The guard itself remains
  // generic; core_top can replace this lookup without changing its handshake.
  always_comb begin
    policy_slot_known = 1'b1;
    policy_allow_read = 1'b0;
    policy_allow_write = 1'b1;
    policy_bounds_ready = !force_bounds_not_ready;
    policy_size_mode = 2'd0;
    policy_exact_size = 48'd0;
    policy_min_size = 48'd0;
    policy_max_size = 48'hffff_ffff_ffff;
    policy_capture_length = 1'b0;

    case (policy_slot_id)
      16'd0: begin
        // Cartridge: host-to-core only, dynamically sized within mapper bounds.
        policy_size_mode = 2'd2;
        policy_min_size = 48'd65536;
        policy_max_size = 48'd16777216;
      end
      16'd9: begin
        // Retired external monochrome BIOS slot: permanently disallowed.
        policy_allow_write = 1'b0;
      end
      16'd10: begin
        // Retired external Color BIOS slot: permanently disallowed.
        policy_allow_write = 1'b0;
      end
      16'd11: begin
        // Save: both directions, exact bound supplied after ROM footer decode.
        policy_allow_read = 1'b1;
        policy_size_mode = 2'd1;
        policy_exact_size = 48'd140;
        policy_capture_length = 1'b1;
      end
      16'd12: begin
        // Fixed monochrome console EEPROM: exact 128-byte load, readable flush.
        policy_allow_read = 1'b1;
        policy_size_mode = 2'd1;
        policy_exact_size = 48'd128;
      end
      16'd13: begin
        // Fixed Color console EEPROM: exact 2 KiB load, readable flush.
        policy_allow_read = 1'b1;
        policy_size_mode = 2'd1;
        policy_exact_size = 48'd2048;
      end
      default: begin
        policy_slot_known = 1'b0;
        policy_allow_read = 1'b0;
        policy_allow_write = 1'b0;
        policy_bounds_ready = 1'b1;
        policy_size_mode = 2'd0;
      end
    endcase
  end

  task automatic fail(input string message);
    begin
      $display("FAIL: %s", message);
      errors = errors + 1;
    end
  endtask

  task automatic apply_reset;
    begin
      @(negedge clk);
      reset_n = 1'b0;
      request_valid = 1'b0;
      captured_length_clear = 1'b0;
      @(posedge clk);
      #1;
      if (request_ack !== 1'b0 || request_busy !== 1'b0)
        fail("reset did not clear request handshake");
      if (captured_save_length_valid !== 1'b0)
        fail("reset did not mark save as absent");
      @(negedge clk);
      reset_n = 1'b1;
    end
  endtask

  task automatic issue_request(
      input bit write_direction,
      input [15:0] slot_id,
      input [47:0] byte_size,
      input [1:0] expected_result,
      input bit expected_capture
  );
    integer ack_before;
    begin
      while (request_busy) @(negedge clk);
      ack_before = ack_count;
      request_write = write_direction;
      request_id = slot_id;
      request_size = byte_size;
      request_valid = 1'b1;

      // Acceptance only snapshots the request; no combinational/immediate ack.
      @(posedge clk);
      #1;
      if (!request_busy || request_ack)
        fail($sformatf("slot %0d was not delayed for evaluation", slot_id));
      if (policy_slot_id !== slot_id)
        fail($sformatf("slot %0d policy lookup ID mismatch", slot_id));

      // The following clock returns exactly one official result code.
      @(posedge clk);
      #1;
      if (!request_ack)
        fail($sformatf("slot %0d request was not acknowledged", slot_id));
      if (request_result !== expected_result)
        fail($sformatf("slot %0d result=%0d expected=%0d",
                       slot_id, request_result, expected_result));
      if (captured_save_length_updated !== expected_capture)
        fail($sformatf("slot %0d capture pulse mismatch", slot_id));

      // Holding the command high after ack must not execute it twice.
      repeat (2) begin
        @(posedge clk);
        #1;
        if (request_ack)
          fail($sformatf("slot %0d level request acknowledged twice", slot_id));
        if (captured_save_length_updated)
          fail($sformatf("slot %0d length captured twice", slot_id));
      end
      if (ack_count != ack_before + 1)
        fail($sformatf("slot %0d emitted %0d acknowledgements",
                       slot_id, ack_count - ack_before));

      @(negedge clk);
      request_valid = 1'b0;
      @(posedge clk);
      #1;
      if (request_busy)
        fail($sformatf("slot %0d did not re-arm after release", slot_id));
    end
  endtask

  always @(posedge clk) begin
    #1;
    if (request_ack)
      ack_count = ack_count + 1;
    if (reset_n && $isunknown({request_ack, request_result, request_busy,
                               policy_slot_id, captured_save_length_valid,
                               captured_save_length_updated}))
      fail("unknown value escaped data-slot guard");
  end

  initial begin
    apply_reset();

    // No save write after reset means the host save is absent.
    if (captured_save_length_valid)
      fail("absent save unexpectedly has a captured length");

    // Chip32 holds cart_download (the capture-clear level) high around LOADF.
    // Slot 0 must still acknowledge or cold boot deadlocks before that level
    // can ever be released.
    captured_length_clear = 1'b1;
    issue_request(1'b1, 16'd0, 48'd65536, RESULT_READY, 1'b0);
    captured_length_clear = 1'b0;

    // Unsupported IDs and directions are permanently disallowed (result 1).
    issue_request(1'b1, 16'hbeef, 48'd4096, RESULT_NOT_ALLOWED, 1'b0);
    issue_request(1'b0, 16'd0, 48'd0, RESULT_NOT_ALLOWED, 1'b0);

    // Retired firmware IDs fail closed for every former image size.
    issue_request(1'b1, 16'd9, 48'd4095, RESULT_NOT_ALLOWED, 1'b0);
    issue_request(1'b1, 16'd9, 48'd4097, RESULT_NOT_ALLOWED, 1'b0);
    issue_request(1'b1, 16'd9, 48'd4096, RESULT_NOT_ALLOWED, 1'b0);
    issue_request(1'b1, 16'd10, 48'd8192, RESULT_NOT_ALLOWED, 1'b0);

    // Console-owned EEPROM slots are bidirectional and exact. They are not
    // captured as cartridge-save lengths and reject either truncation or
    // oversize before any loader sees the transfer.
    issue_request(1'b1, 16'd12, 48'd127, RESULT_NOT_ALLOWED, 1'b0);
    issue_request(1'b1, 16'd12, 48'd129, RESULT_NOT_ALLOWED, 1'b0);
    issue_request(1'b1, 16'd12, 48'd128, RESULT_READY, 1'b0);
    issue_request(1'b0, 16'd12, 48'd0, RESULT_READY, 1'b0);
    issue_request(1'b1, 16'd13, 48'd2047, RESULT_NOT_ALLOWED, 1'b0);
    issue_request(1'b1, 16'd13, 48'd2049, RESULT_NOT_ALLOWED, 1'b0);
    issue_request(1'b1, 16'd13, 48'd2048, RESULT_READY, 1'b0);
    issue_request(1'b0, 16'd13, 48'd0, RESULT_READY, 1'b0);

    // Dynamic inclusive bounds accept both endpoints and reject either side.
    issue_request(1'b1, 16'd0, 48'd65535, RESULT_NOT_ALLOWED, 1'b0);
    issue_request(1'b1, 16'd0, 48'd65536, RESULT_READY, 1'b0);
    issue_request(1'b1, 16'd0, 48'd16777216, RESULT_READY, 1'b0);
    issue_request(1'b1, 16'd0, 48'd16777217, RESULT_NOT_ALLOWED, 1'b0);
    issue_request(1'b1, 16'd0, 48'h0001_0000_0000,
                  RESULT_NOT_ALLOWED, 1'b0);

    // A legal request whose policy or loader is not ready must return the
    // official retry/check-later result (2), then succeed when retried.
    write_loader_ready = 1'b0;
    issue_request(1'b1, 16'd12, 48'd128, RESULT_CHECK_LATER, 1'b0);
    write_loader_ready = 1'b1;
    issue_request(1'b1, 16'd12, 48'd128, RESULT_READY, 1'b0);
    force_bounds_not_ready = 1'b1;
    // Even a currently mismatched size is retryable until dynamic bounds exist.
    issue_request(1'b1, 16'd11, 48'd139, RESULT_CHECK_LATER, 1'b1);
    force_bounds_not_ready = 1'b0;
    read_loader_ready = 1'b0;
    issue_request(1'b0, 16'd11, 48'd0, RESULT_CHECK_LATER, 1'b0);
    read_loader_ready = 1'b1;
    issue_request(1'b0, 16'd11, 48'd0, RESULT_READY, 1'b0);

    // Save write lengths are captured even when exact validation rejects them.
    issue_request(1'b1, 16'd11, 48'd139, RESULT_NOT_ALLOWED, 1'b1);
    if (!captured_save_length_valid || captured_save_id != 16'd11 ||
        captured_save_length != 48'd139)
      fail("short save length was not retained for diagnostics");
    issue_request(1'b1, 16'd11, 48'd141, RESULT_NOT_ALLOWED, 1'b1);
    if (captured_save_length != 48'd141)
      fail("oversized save length was not retained for diagnostics");
    issue_request(1'b1, 16'd11, 48'd140, RESULT_READY, 1'b1);
    if (captured_save_length != 48'd140)
      fail("valid save length was not captured");

    // Explicit lifecycle clear restores the absent-save state without reset.
    @(negedge clk);
    captured_length_clear = 1'b1;
    @(posedge clk);
    #1;
    if (captured_save_length_valid || captured_save_length != 48'd0)
      fail("captured save clear did not restore absent state");
    @(negedge clk);
    captured_length_clear = 1'b0;

    // Inputs may change while a request is in flight; the latched first request
    // remains authoritative, and the changed level is not treated as a second.
    request_write = 1'b1;
    request_id = 16'd12;
    request_size = 48'd128;
    request_valid = 1'b1;
    @(posedge clk);
    #1;
    request_id = 16'hdead;
    request_size = 48'hffff_ffff_ffff;
    @(posedge clk);
    #1;
    if (!request_ack || request_result != RESULT_READY)
      fail("in-flight input mutation changed the latched request");
    @(posedge clk);
    #1;
    if (request_ack)
      fail("mutated held request was executed a second time");
    @(negedge clk);
    request_valid = 1'b0;
    @(posedge clk);
    #1;
    if (request_busy)
      fail("in-flight mutation case did not re-arm");

    // Reset aborts an in-flight request without ack or stale length capture.
    request_write = 1'b1;
    request_id = 16'd11;
    request_size = 48'd140;
    request_valid = 1'b1;
    @(posedge clk);
    #1;
    @(negedge clk);
    reset_n = 1'b0;
    request_valid = 1'b0;
    @(posedge clk);
    #1;
    if (request_ack || request_busy || captured_save_length_valid)
      fail("reset did not abort an in-flight save request");
    @(negedge clk);
    reset_n = 1'b1;

    if (errors != 0) begin
      $display("FAIL apf_dataslot_guard_tb errors=%0d", errors);
      $fatal(1);
    end
    $display("PASS APF data-slot guard delayed results, bounds, capture, and reset");
    $finish;
  end

endmodule
