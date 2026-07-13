`timescale 1ns / 1ps
`default_nettype none

module apf_savestate_sdram_reader_tb;
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
  reg read_request_valid = 1'b0;
  wire read_request_ready;
  reg [31:0] read_request_offset = 32'd0;
  wire read_word_valid;
  reg read_word_ready = 1'b0;
  wire [31:0] read_word_offset;
  wire [31:0] read_word;
  wire [31:0] fetched_bytes;
  wire [31:0] delivered_bytes;
  wire sdram_req;
  wire [24:0] sdram_addr;
  wire sdram_rnw;
  reg [15:0] sdram_data = 16'd0;
  reg sdram_ready = 1'b0;
  reg sdram_error = 1'b0;

  reg previous_sdram_req = 1'b0;
  integer request_count = 0;
  integer fetch_count = 0;
  integer delivery_count = 0;
  integer test_index;
  integer random_stall_low;
  integer random_stall_high;
  integer random_hold;
  reg [31:0] random_word;
  reg [31:0] random_offset;

  always #5 clk = ~clk;

  apf_savestate_sdram_reader dut (
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
      .read_request_valid(read_request_valid),
      .read_request_ready(read_request_ready),
      .read_request_offset(read_request_offset),
      .read_word_valid(read_word_valid),
      .read_word_ready(read_word_ready),
      .read_word_offset(read_word_offset),
      .read_word(read_word),
      .fetched_bytes(fetched_bytes),
      .delivered_bytes(delivered_bytes),
      .sdram_req(sdram_req),
      .sdram_addr(sdram_addr),
      .sdram_rnw(sdram_rnw),
      .sdram_data(sdram_data),
      .sdram_ready(sdram_ready),
      .sdram_error(sdram_error)
  );

  always @(posedge clk) begin
    #1ps;
    if (!reset_n) begin
      previous_sdram_req = 1'b0;
    end else begin
      if (sdram_req && previous_sdram_req)
        $fatal(1, "SDRAM request was not a one-cycle edge pulse");
      if (sdram_req) request_count = request_count + 1;
      previous_sdram_req = sdram_req;
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
      expect_true(transfer_start_ready,
                  "transfer start was backpressured while quiescent");
      transfer_start = 1'b1;
      @(negedge clk);
      transfer_start = 1'b0;
      #1ps;
      expect_true(transfer_active && !transfer_failed,
                  "accepted transfer start did not activate reader");
      expect_true(failure_reason == FAILURE_NONE,
                  "accepted transfer start did not clear failure reason");
      expect_true(!read_word_valid && fetched_bytes == 0 && delivered_bytes == 0,
                  "accepted transfer start did not clear cache/counters");
    end
  endtask

  task automatic offer_request(input [31:0] offset);
    begin
      @(negedge clk);
      expect_true(read_request_ready,
                  "reader did not advertise request readiness");
      read_request_offset = offset;
      read_request_valid = 1'b1;
      @(negedge clk);
      read_request_valid = 1'b0;
    end
  endtask

  task automatic wait_sdram_request(
      input [24:0] expected_addr,
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
      expect_true(sdram_addr === expected_addr,
                  {label_text, " address mismatch"});
      expect_true(sdram_rnw === 1'b1,
                  {label_text, " was not a read"});
    end
  endtask

  task automatic acknowledge_read(
      input [24:0] expected_addr,
      input [15:0] returned_data,
      input integer stall_cycles,
      input inject_error,
      input [511:0] label_text
  );
    integer stall_index;
    begin
      wait_sdram_request(expected_addr, label_text);
      for (stall_index = 0; stall_index < stall_cycles;
           stall_index = stall_index + 1) begin
        @(negedge clk);
        expect_true(!sdram_req,
                    {label_text, " request repeated while stalled"});
        expect_true(sdram_addr === expected_addr,
                    {label_text, " address changed while stalled"});
        expect_true(!read_request_ready,
                    {label_text, " upstream was not backpressured"});
      end
      sdram_data = returned_data;
      sdram_error = inject_error;
      sdram_ready = 1'b1;
      @(negedge clk);
      sdram_ready = 1'b0;
      sdram_error = 1'b0;
      sdram_data = 16'd0;
    end
  endtask

  task automatic expect_no_request(input integer cycles,
                                   input [511:0] label_text);
    integer cycle_index;
    begin
      for (cycle_index = 0; cycle_index < cycles;
           cycle_index = cycle_index + 1) begin
        @(negedge clk);
        expect_true(!sdram_req, label_text);
      end
    end
  endtask

  task automatic fetch_to_cache(
      input [31:0] offset,
      input [31:0] word_value,
      input integer low_stall,
      input integer high_stall
  );
    reg [24:0] low_address;
    reg [31:0] fetched_before;
    begin
      low_address = (25'h088_0000 + offset[25:1]);
      fetched_before = fetched_bytes;
      offer_request(offset);
      acknowledge_read(low_address,
                       {word_value[23:16], word_value[31:24]},
                       low_stall, 1'b0, "low half");
      expect_true(!read_word_valid && fetched_bytes == fetched_before,
                  "low half exposed or counted a torn x32 word");
      acknowledge_read(low_address + 25'd1,
                       {word_value[7:0], word_value[15:8]},
                       high_stall, 1'b0, "high half");
      expect_true(read_word_valid,
                  "successful high half did not populate cache");
      expect_true(read_word_offset == offset && read_word == word_value,
                  "cached normalized word was torn or byte-swapped");
      expect_true(fetched_bytes == fetched_before + 32'd4,
                  "successful fetch advanced byte count incorrectly");
      fetch_count = fetch_count + 1;
    end
  endtask

  task automatic consume_cached(
      input [31:0] expected_offset,
      input [31:0] expected_word,
      input integer hold_cycles
  );
    integer hold_index;
    reg [31:0] delivered_before;
    begin
      delivered_before = delivered_bytes;
      for (hold_index = 0; hold_index < hold_cycles;
           hold_index = hold_index + 1) begin
        @(negedge clk);
        expect_true(read_word_valid,
                    "cached word disappeared before consumption");
        expect_true(read_word_offset == expected_offset &&
                    read_word == expected_word,
                    "cached word changed while backpressured");
        expect_true(!read_request_ready,
                    "unconsumed cache incorrectly accepted a successor");
      end
      read_word_ready = 1'b1;
      #1ps;
      expect_true(read_word_valid,
                  "ready combinationally invalidated cached word");
      @(negedge clk);
      read_word_ready = 1'b0;
      expect_true(!read_word_valid,
                  "consumed word remained valid");
      expect_true(delivered_bytes == delivered_before + 32'd4,
                  "consumption advanced delivered bytes incorrectly");
      delivery_count = delivery_count + 1;
    end
  endtask

  task automatic expect_invalid_offset(input [31:0] invalid_offset);
    integer requests_before;
    begin
      start_new_transfer();
      requests_before = request_count;
      offer_request(invalid_offset);
      #1ps;
      expect_true(transfer_failed && !transfer_active && quiescent,
                  "invalid address did not poison the transaction");
      expect_true(failure_reason == FAILURE_ADDRESS,
                  "invalid address reported the wrong failure reason");
      expect_true(!read_word_valid && fetched_bytes == 0,
                  "invalid address exposed cached data");
      expect_no_request(4, "invalid address emitted an SDRAM request");
      expect_true(request_count == requests_before,
                  "invalid address changed the request count");
    end
  endtask

  initial begin
    #1ps;
    expect_true(quiescent && !busy && !transfer_active && !transfer_failed,
                "reset outputs were not fail-safe");
    expect_true(!sdram_req && !read_word_valid && fetched_bytes == 0 &&
                delivered_bytes == 0,
                "reset leaked a request, cache word, or byte count");
    repeat (3) @(posedge clk);
    reset_n = 1'b1;

    // Exact byte normalization, independent stalls, and a cache that remains
    // stable while its consumer and successor are backpressured.
    start_new_transfer();
    fetch_to_cache(32'd0, 32'h1122_3344, 5, 7);
    expect_true(sdram_addr == STAGE_BASE_WORD + 25'd1,
                "first fetch left the protected staging base");
    @(negedge clk);
    read_request_offset = 32'd4;
    read_request_valid = 1'b1;
    repeat (5) begin
      @(negedge clk);
      expect_true(!read_request_ready,
                  "held successor bypassed an unconsumed cache word");
      expect_true(read_word_valid && read_word_offset == 0 &&
                  read_word == 32'h1122_3344,
                  "bridge-visible cache changed while held");
    end

    // Pop the old cache and accept its held successor on exactly one edge.
    read_word_ready = 1'b1;
    #1ps;
    expect_true(read_request_ready,
                "same-edge cache turnover did not advertise readiness");
    @(negedge clk);
    read_word_ready = 1'b0;
    read_request_valid = 1'b0;
    expect_true(!read_word_valid && delivered_bytes == 32'd4 && busy,
                "same-edge turnover did not consume and launch atomically");
    delivery_count = delivery_count + 1;
    acknowledge_read(STAGE_BASE_WORD + 25'd2, 16'h6655, 3, 1'b0,
                     "turnover low half");
    acknowledge_read(STAGE_BASE_WORD + 25'd3, 16'h8877, 4, 1'b0,
                     "turnover high half");
    expect_true(read_word_valid && read_word_offset == 4 &&
                read_word == 32'h5566_7788 && fetched_bytes == 8,
                "turnover successor did not populate cache exactly");
    fetch_count = fetch_count + 1;
    consume_cached(32'd4, 32'h5566_7788, 6);

    // The final legal x32 word proves the exclusive end boundary.
    fetch_to_cache(LAST_OFFSET, 32'ha1b2_c3d4, 0, 1);
    expect_true(sdram_addr == LAST_LOW_WORD + 25'd1,
                "last legal fetch mapped to the wrong high half");
    consume_cached(LAST_OFFSET, 32'ha1b2_c3d4, 2);

    // Alignment, exclusive end, and wide-add overflow fail before SDRAM.
    expect_invalid_offset(32'd2);
    expect_invalid_offset(STAGE_BYTES);
    expect_invalid_offset(32'hffff_fffc);

    // Either physical half can fail, but neither case exposes a word.
    start_new_transfer();
    offer_request(32'd0);
    acknowledge_read(STAGE_BASE_WORD, 16'hadde, 2, 1'b1,
                     "injected low backend failure");
    expect_true(transfer_failed && failure_reason == FAILURE_BACKEND_LOW,
                "low backend failure was not terminal");
    expect_true(!read_word_valid && fetched_bytes == 0,
                "low backend failure exposed or counted a word");
    expect_no_request(4, "low backend failure issued a high half");

    start_new_transfer();
    offer_request(32'd4);
    acknowledge_read(STAGE_BASE_WORD + 25'd2, 16'hf0ca, 1, 1'b0,
                     "high-failure low half");
    acknowledge_read(STAGE_BASE_WORD + 25'd3, 16'h3412, 3, 1'b1,
                     "injected high backend failure");
    expect_true(transfer_failed && failure_reason == FAILURE_BACKEND_HIGH,
                "high backend failure was not terminal");
    expect_true(!read_word_valid && fetched_bytes == 0,
                "high backend failure exposed or counted a word");

    // Aborting a populated but unconsumed cache invalidates it immediately.
    start_new_transfer();
    fetch_to_cache(32'd0, 32'hfeed_face, 0, 0);
    abort = 1'b1;
    @(negedge clk);
    abort = 1'b0;
    expect_true(quiescent && transfer_failed &&
                failure_reason == FAILURE_ABORT && !read_word_valid &&
                delivered_bytes == 0,
                "cache abort did not fail closed");

    // Abort before the low request edge suppresses both physical reads.
    start_new_transfer();
    offer_request(32'd0);
    abort = 1'b1;
    @(negedge clk);
    abort = 1'b0;
    expect_true(transfer_failed && failure_reason == FAILURE_ABORT && quiescent,
                "pre-issue abort did not fail closed");
    expect_no_request(4, "pre-issue abort leaked an SDRAM request");

    // An outstanding abort stays in drain even when abort is held. New work
    // is backpressured until the one stale ready pulse is consumed.
    start_new_transfer();
    offer_request(32'd0);
    wait_sdram_request(STAGE_BASE_WORD, "held-abort low half");
    abort = 1'b1;
    transfer_start = 1'b1;
    repeat (4) begin
      @(negedge clk);
      expect_true(busy && !quiescent && !transfer_start_ready && !sdram_req,
                  "held abort escaped drain or repeated a request");
    end
    sdram_data = 16'hffff;
    sdram_ready = 1'b1;
    @(negedge clk);
    sdram_ready = 1'b0;
    sdram_data = 16'd0;
    abort = 1'b0;
    transfer_start = 1'b0;
    expect_true(quiescent && transfer_failed && !read_word_valid &&
                failure_reason == FAILURE_ABORT,
                "held-abort stale acknowledgement was not drained");
    expect_no_request(3, "held low abort issued a high half");

    // Abort wins when completion and error arrive on the exact same edge.
    start_new_transfer();
    offer_request(32'd4);
    wait_sdram_request(STAGE_BASE_WORD + 25'd2,
                       "same-cycle abort and ready");
    abort = 1'b1;
    sdram_ready = 1'b1;
    sdram_error = 1'b1;
    sdram_data = 16'h1234;
    @(negedge clk);
    abort = 1'b0;
    sdram_ready = 1'b0;
    sdram_error = 1'b0;
    sdram_data = 16'd0;
    expect_true(quiescent && transfer_failed &&
                failure_reason == FAILURE_ABORT && !read_word_valid,
                "same-cycle abort/ready did not preserve abort priority");
    expect_no_request(3, "same-cycle abort/ready issued a high half");

    // The same stale-ready rule applies after the high request is issued.
    start_new_transfer();
    offer_request(32'd0);
    acknowledge_read(STAGE_BASE_WORD, 16'had0b, 0, 1'b0,
                     "abort-high low half");
    wait_sdram_request(STAGE_BASE_WORD + 25'd1,
                       "abort-drain high half");
    abort = 1'b1;
    @(negedge clk);
    abort = 1'b0;
    expect_true(busy && !transfer_start_ready,
                "outstanding high abort did not enter drain state");
    repeat (3) @(negedge clk);
    sdram_ready = 1'b1;
    sdram_data = 16'h0df0;
    @(negedge clk);
    sdram_ready = 1'b0;
    sdram_data = 16'd0;
    expect_true(quiescent && transfer_failed && !read_word_valid &&
                fetched_bytes == 0,
                "aborted outstanding high half populated cache");

    // Sustained operation with permuted addresses and adversarial finite
    // stalls proves normalization and stable cache behavior repeatedly.
    start_new_transfer();
    for (test_index = 0; test_index < 256; test_index = test_index + 1) begin
      random_word = $urandom;
      random_offset = ((test_index * 32'd7919) % (STAGE_BYTES / 4)) * 4;
      random_stall_low = $urandom_range(0, 20);
      random_stall_high = $urandom_range(0, 20);
      random_hold = $urandom_range(0, 12);
      fetch_to_cache(random_offset, random_word,
                     random_stall_low, random_stall_high);
      consume_cached(random_offset, random_word, random_hold);
    end
    expect_true(!transfer_failed && transfer_active && quiescent,
                "randomized read/cache run did not remain healthy");
    expect_true(fetched_bytes == 32'd1024 && delivered_bytes == 32'd1024,
                "randomized run counted the wrong number of bytes");

    // Reset clears logical state. Production integration must reset the SDRAM
    // arbiter too if a physical request was outstanding.
    reset_n = 1'b0;
    #1ps;
    expect_true(quiescent && !transfer_active && !transfer_failed &&
                !read_word_valid && fetched_bytes == 0 &&
                delivered_bytes == 0 && !sdram_req,
                "asynchronous reset did not restore fail-safe state");

    $display(
        "PASS APF savestate SDRAM reader requests=%0d fetches=%0d deliveries=%0d random_words=256",
        request_count,
        fetch_count,
        delivery_count
    );
    $finish;
  end
endmodule

`default_nettype wire
