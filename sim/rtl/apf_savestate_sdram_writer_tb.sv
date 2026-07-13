`timescale 1ns / 1ps
`default_nettype none

module apf_savestate_sdram_writer_tb;
  localparam [31:0] STAGE_BASE_BYTE = 32'h0110_0000;
  localparam [31:0] STAGE_BYTES = 32'h0009_0300;
  localparam [24:0] STAGE_BASE_WORD = 25'h088_0000;
  localparam [31:0] LAST_OFFSET = STAGE_BYTES - 32'd4;
  localparam [24:0] LAST_LOW_WORD = 25'h08c_817e;

  localparam [2:0] FAILURE_NONE = 3'd0;
  localparam [2:0] FAILURE_ADDRESS = 3'd1;
  localparam [2:0] FAILURE_BACKEND_LOW = 3'd2;
  localparam [2:0] FAILURE_BACKEND_HIGH = 3'd3;
  localparam [2:0] FAILURE_ABORT = 3'd4;

  reg clk = 1'b0;
  reg reset_n = 1'b0;
  reg transfer_start = 1'b0;
  wire transfer_start_ready;
  reg abort = 1'b0;
  wire transfer_active;
  wire transfer_failed;
  wire [2:0] failure_reason;
  wire busy;
  wire quiescent;
  reg stage_word_valid = 1'b0;
  wire stage_word_ready;
  reg [31:0] stage_word_offset = 32'd0;
  reg [31:0] stage_word = 32'd0;
  wire commit_pulse;
  wire [31:0] committed_offset;
  wire [31:0] committed_word;
  wire [31:0] committed_bytes;
  wire sdram_req;
  wire [24:0] sdram_addr;
  wire [15:0] sdram_data;
  wire [1:0] sdram_be;
  reg sdram_ready = 1'b0;
  reg sdram_error = 1'b0;

  reg previous_sdram_req = 1'b0;
  reg previous_commit_pulse = 1'b0;
  integer request_count = 0;
  integer commit_count = 0;
  integer test_index;
  integer random_stall_low;
  integer random_stall_high;
  reg [31:0] random_word;
  reg [31:0] random_offset;

  always #5 clk = ~clk;

  apf_savestate_sdram_writer dut (
      .clk(clk),
      .reset_n(reset_n),
      .transfer_start(transfer_start),
      .transfer_start_ready(transfer_start_ready),
      .abort(abort),
      .transfer_active(transfer_active),
      .transfer_failed(transfer_failed),
      .failure_reason(failure_reason),
      .busy(busy),
      .quiescent(quiescent),
      .stage_word_valid(stage_word_valid),
      .stage_word_ready(stage_word_ready),
      .stage_word_offset(stage_word_offset),
      .stage_word(stage_word),
      .commit_pulse(commit_pulse),
      .committed_offset(committed_offset),
      .committed_word(committed_word),
      .committed_bytes(committed_bytes),
      .sdram_req(sdram_req),
      .sdram_addr(sdram_addr),
      .sdram_data(sdram_data),
      .sdram_be(sdram_be),
      .sdram_ready(sdram_ready),
      .sdram_error(sdram_error)
  );

  always @(posedge clk) begin
    #1ps;
    if (!reset_n) begin
      previous_sdram_req = 1'b0;
      previous_commit_pulse = 1'b0;
    end else begin
      if (sdram_req && previous_sdram_req)
        $fatal(1, "SDRAM request was not a one-cycle edge pulse");
      if (commit_pulse && previous_commit_pulse)
        $fatal(1, "commit pulse lasted more than one cycle");
      if (sdram_req) request_count = request_count + 1;
      if (commit_pulse) commit_count = commit_count + 1;
      previous_sdram_req = sdram_req;
      previous_commit_pulse = commit_pulse;
    end
  end

  task automatic expect_true(input condition, input [511:0] label_text);
    begin
      if (!condition)
        $fatal(1, "%0s", label_text);
    end
  endtask

  task automatic start_new_transfer;
    begin
      @(negedge clk);
      expect_true(transfer_start_ready, "transfer start was backpressured while quiescent");
      transfer_start = 1'b1;
      @(negedge clk);
      transfer_start = 1'b0;
      #1ps;
      expect_true(transfer_active, "accepted transfer start did not activate writer");
      expect_true(!transfer_failed && failure_reason == FAILURE_NONE,
                  "accepted transfer start did not clear failure state");
      expect_true(committed_bytes == 32'd0,
                  "accepted transfer start did not clear committed count");
    end
  endtask

  task automatic offer_word(input [31:0] offset, input [31:0] word_value);
    begin
      @(negedge clk);
      expect_true(stage_word_ready, "writer did not advertise input readiness");
      stage_word_offset = offset;
      stage_word = word_value;
      stage_word_valid = 1'b1;
      @(negedge clk);
      stage_word_valid = 1'b0;
    end
  endtask

  task automatic wait_request(
      input [24:0] expected_addr,
      input [15:0] expected_data,
      input [511:0] label_text
  );
    integer wait_cycles;
    begin
      wait_cycles = 0;
      while (!sdram_req) begin
        @(negedge clk);
        wait_cycles = wait_cycles + 1;
        if (wait_cycles > 20)
          $fatal(1, "%0s request never arrived", label_text);
      end
      expect_true(sdram_addr === expected_addr, {label_text, " address mismatch"});
      expect_true(sdram_data === expected_data, {label_text, " data mismatch"});
      expect_true(sdram_be === 2'b11, {label_text, " byte enables mismatch"});
    end
  endtask

  task automatic acknowledge_request(
      input [24:0] expected_addr,
      input [15:0] expected_data,
      input integer stall_cycles,
      input inject_error,
      input [511:0] label_text
  );
    integer stall_index;
    begin
      wait_request(expected_addr, expected_data, label_text);
      for (stall_index = 0; stall_index < stall_cycles; stall_index = stall_index + 1) begin
        @(negedge clk);
        expect_true(!sdram_req, {label_text, " request was repeated while stalled"});
        expect_true(sdram_addr === expected_addr,
                    {label_text, " address changed while stalled"});
        expect_true(sdram_data === expected_data,
                    {label_text, " data changed while stalled"});
        expect_true(!stage_word_ready,
                    {label_text, " upstream was not backpressured while stalled"});
      end
      sdram_error = inject_error;
      sdram_ready = 1'b1;
      @(negedge clk);
      sdram_ready = 1'b0;
      sdram_error = 1'b0;
    end
  endtask

  task automatic expect_no_request(input integer cycles, input [511:0] label_text);
    integer cycle_index;
    begin
      for (cycle_index = 0; cycle_index < cycles; cycle_index = cycle_index + 1) begin
        @(negedge clk);
        expect_true(!sdram_req, label_text);
      end
    end
  endtask

  task automatic write_and_commit(
      input [31:0] offset,
      input [31:0] word_value,
      input integer low_stall,
      input integer high_stall
  );
    reg [24:0] low_address;
    integer commits_before;
    reg [31:0] bytes_before;
    begin
      low_address = (STAGE_BASE_BYTE + offset) >> 1;
      commits_before = commit_count;
      bytes_before = committed_bytes;
      offer_word(offset, word_value);
      acknowledge_request(low_address,
                          {word_value[23:16], word_value[31:24]},
                          low_stall, 1'b0, "low half");
      expect_true(commit_count == commits_before,
                  "word committed after only its low half");
      expect_true(committed_bytes == bytes_before,
                  "committed byte count advanced after only the low half");
      acknowledge_request(low_address + 25'd1,
                          {word_value[7:0], word_value[15:8]},
                          high_stall, 1'b0, "high half");
      expect_true(commit_pulse, "successful high half did not pulse commit");
      expect_true(commit_count == commits_before + 1,
                  "successful word produced the wrong commit count");
      expect_true(committed_offset == offset && committed_word == word_value,
                  "committed word metadata was torn or incorrect");
      expect_true(committed_bytes == bytes_before + 32'd4,
                  "successful word advanced committed bytes incorrectly");
    end
  endtask

  task automatic expect_invalid_offset(input [31:0] invalid_offset);
    integer requests_before;
    integer commits_before;
    begin
      start_new_transfer();
      requests_before = request_count;
      commits_before = commit_count;
      offer_word(invalid_offset, 32'hbad0_ff5e);
      #1ps;
      expect_true(transfer_failed && !transfer_active,
                  "invalid address did not poison the transaction");
      expect_true(failure_reason == FAILURE_ADDRESS,
                  "invalid address reported the wrong failure reason");
      expect_true(quiescent && !stage_word_ready,
                  "invalid address did not fail closed while quiescent");
      expect_no_request(4, "invalid address emitted an SDRAM request");
      expect_true(request_count == requests_before && commit_count == commits_before,
                  "invalid address changed request or commit counts");
    end
  endtask

  initial begin
    #1ps;
    expect_true(quiescent && !busy && !transfer_active && !transfer_failed,
                "reset outputs were not fail-safe");
    expect_true(!sdram_req && !commit_pulse && committed_bytes == 0,
                "reset leaked a request, commit, or byte count");
    repeat (3) @(posedge clk);
    reset_n = 1'b1;

    // Exact low/high byte order, independent stalls, and logical atomicity.
    start_new_transfer();
    write_and_commit(32'd0, 32'h1122_3344, 5, 7);
    expect_true(sdram_addr == STAGE_BASE_WORD + 25'd1,
                "first word did not stay inside staging base");

    // The final legal word proves the inclusive/exclusive address boundary.
    write_and_commit(LAST_OFFSET, 32'ha1b2_c3d4, 0, 1);
    expect_true(sdram_addr == LAST_LOW_WORD + 25'd1,
                "last legal word mapped to the wrong high half");

    // A valid held word cannot be consumed until both halves of its
    // predecessor commit. Keep the second word stable throughout backpressure.
    @(negedge clk);
    expect_true(stage_word_ready, "held-valid setup was unexpectedly backpressured");
    stage_word_offset = 32'd8;
    stage_word = 32'h0102_0304;
    stage_word_valid = 1'b1;
    @(negedge clk);
    stage_word_offset = 32'd12;
    stage_word = 32'h5566_7788;
    acknowledge_request(STAGE_BASE_WORD + 25'd4, 16'h0201, 3, 1'b0,
                        "held-valid first low");
    expect_true(!stage_word_ready, "second held word bypassed the first low half");
    acknowledge_request(STAGE_BASE_WORD + 25'd5, 16'h0403, 4, 1'b0,
                        "held-valid first high");
    expect_true(commit_pulse, "held-valid first word did not commit");
    // stage_word_valid stayed high; readiness returns only after the commit.
    expect_true(stage_word_ready, "held-valid second word was not released after commit");
    @(negedge clk);
    stage_word_valid = 1'b0;
    acknowledge_request(STAGE_BASE_WORD + 25'd6, 16'h6655, 2, 1'b0,
                        "held-valid second low");
    acknowledge_request(STAGE_BASE_WORD + 25'd7, 16'h8877, 2, 1'b0,
                        "held-valid second high");
    expect_true(commit_pulse && committed_offset == 32'd12 &&
                committed_word == 32'h5566_7788,
                "held-valid second word did not commit exactly");
    expect_true(committed_bytes == 32'd16,
                "four successful words did not commit sixteen bytes");

    // Alignment, exclusive end, and wide-add overflow all fail before SDRAM.
    expect_invalid_offset(32'd2);
    expect_invalid_offset(STAGE_BYTES);
    expect_invalid_offset(32'hffff_fffc);

    // Backend failure after the first physical half leaves no logical commit.
    start_new_transfer();
    offer_word(32'd0, 32'hdead_beef);
    acknowledge_request(STAGE_BASE_WORD, 16'hadde, 2, 1'b1,
                        "injected low backend failure");
    expect_true(transfer_failed && failure_reason == FAILURE_BACKEND_LOW,
                "low backend failure was not terminal");
    expect_true(committed_bytes == 0 && !commit_pulse,
                "low backend failure produced a logical commit");
    expect_no_request(4, "low backend failure issued a high half");

    // Backend failure on the high half is also non-committing.
    start_new_transfer();
    offer_word(32'd4, 32'hcaf0_1234);
    acknowledge_request(STAGE_BASE_WORD + 25'd2, 16'hf0ca, 1, 1'b0,
                        "high-failure low half");
    acknowledge_request(STAGE_BASE_WORD + 25'd3, 16'h3412, 3, 1'b1,
                        "injected high backend failure");
    expect_true(transfer_failed && failure_reason == FAILURE_BACKEND_HIGH,
                "high backend failure was not terminal");
    expect_true(committed_bytes == 0 && !commit_pulse,
                "high backend failure produced a logical commit");

    // Abort before request issue suppresses both physical halves.
    start_new_transfer();
    offer_word(32'd0, 32'h1357_9bdf);
    abort = 1'b1;
    @(negedge clk);
    abort = 1'b0;
    expect_true(transfer_failed && failure_reason == FAILURE_ABORT && quiescent,
                "pre-issue abort did not fail closed");
    expect_no_request(4, "pre-issue abort leaked an SDRAM request");

    // Abort after an edge request must backpressure a new transaction until
    // the stale ready is drained, preventing cross-transaction acknowledgement.
    start_new_transfer();
    offer_word(32'd0, 32'h2468_ace0);
    wait_request(STAGE_BASE_WORD, 16'h6824, "abort-drain low half");
    abort = 1'b1;
    repeat (3) begin
      @(negedge clk);
      expect_true(busy && !quiescent && !transfer_start_ready && !sdram_req,
                  "held abort escaped drain or repeated a request");
    end
    abort = 1'b0;
    expect_true(busy && !quiescent && !transfer_start_ready,
                "outstanding abort did not enter drain backpressure");
    transfer_start = 1'b1;
    repeat (4) begin
      @(negedge clk);
      expect_true(!transfer_start_ready && !sdram_req,
                  "draining abort accepted a new transfer or repeated request");
    end
    sdram_ready = 1'b1;
    @(negedge clk);
    sdram_ready = 1'b0;
    transfer_start = 1'b0;
    expect_true(quiescent && transfer_failed && failure_reason == FAILURE_ABORT,
                "abort drain did not terminate as a sticky failure");
    expect_true(committed_bytes == 0 && !commit_pulse,
                "aborted outstanding low half committed");

    // Abort wins even when completion arrives on the same edge. The request
    // is drained immediately, but neither a high half nor commit is allowed.
    start_new_transfer();
    offer_word(32'd4, 32'hface_c0de);
    wait_request(STAGE_BASE_WORD + 25'd2, 16'hcefa,
                 "same-cycle abort and ready");
    abort = 1'b1;
    sdram_ready = 1'b1;
    sdram_error = 1'b1;
    @(negedge clk);
    abort = 1'b0;
    sdram_ready = 1'b0;
    sdram_error = 1'b0;
    expect_true(quiescent && transfer_failed &&
                failure_reason == FAILURE_ABORT && committed_bytes == 0,
                "same-cycle abort/ready did not preserve abort priority");
    expect_no_request(3, "same-cycle abort/ready issued a high half");

    // The same rule applies after the high half has been issued: physical
    // completion may drain, but logical commit remains forbidden.
    start_new_transfer();
    offer_word(32'd0, 32'h0bad_f00d);
    acknowledge_request(STAGE_BASE_WORD, 16'had0b, 0, 1'b0,
                        "abort-high low half");
    wait_request(STAGE_BASE_WORD + 25'd1, 16'h0df0,
                 "abort-drain high half");
    abort = 1'b1;
    @(negedge clk);
    abort = 1'b0;
    expect_true(busy && !transfer_start_ready,
                "outstanding high abort did not enter drain state");
    repeat (3) @(negedge clk);
    sdram_ready = 1'b1;
    @(negedge clk);
    sdram_ready = 1'b0;
    expect_true(quiescent && transfer_failed && committed_bytes == 0 &&
                !commit_pulse,
                "aborted outstanding high half committed logically");

    // Sustained operation with adversarial but finite stalls. Offsets are
    // deliberately permuted: this unit protects range and atomicity while the
    // upstream envelope coordinator owns exact sequential-blob policy.
    start_new_transfer();
    for (test_index = 0; test_index < 256; test_index = test_index + 1) begin
      random_word = $urandom;
      random_offset = ((test_index * 32'd7919) % (STAGE_BYTES / 4)) * 4;
      random_stall_low = $urandom_range(0, 20);
      random_stall_high = $urandom_range(0, 20);
      write_and_commit(random_offset, random_word,
                       random_stall_low, random_stall_high);
    end
    expect_true(!transfer_failed && transfer_active && quiescent,
                "randomized stall run did not remain healthy");
    expect_true(committed_bytes == 32'd1024,
                "randomized stall run committed the wrong byte count");

    // Reset clears logical state. Production integration must reset the SDRAM
    // arbiter at the same time if a physical request is outstanding.
    reset_n = 1'b0;
    #1ps;
    expect_true(quiescent && !transfer_active && !transfer_failed &&
                committed_bytes == 0 && !sdram_req && !commit_pulse,
                "asynchronous reset did not restore fail-safe state");

    $display(
        "PASS APF savestate SDRAM writer requests=%0d commits=%0d random_words=256",
        request_count,
        commit_count
    );
    $finish;
  end
endmodule

`default_nettype wire
