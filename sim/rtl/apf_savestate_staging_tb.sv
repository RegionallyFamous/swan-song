`timescale 1ns / 1ps

module apf_savestate_staging_tb;
  localparam [31:0] PAYLOAD_BYTES = 32'd32;
  localparam [31:0] TOTAL_BYTES = 32'd64;
  localparam [31:0] FORMAT_ID = 32'h5753_00a5;

  reg clk = 1'b0;
  reg reset_n = 1'b0;

  reg load_write = 1'b0;
  reg [27:0] load_offset = 28'd0;
  reg [31:0] load_data = 32'd0;
  wire load_word_ready;
  reg load_finalize = 1'b0;
  wire load_copy_active;
  wire load_validated;
  wire load_error;
  wire load_busy;
  wire load_done;

  wire restore_start;
  reg restore_complete = 1'b0;
  reg restore_error = 1'b0;

  reg save_start = 1'b0;
  wire capture_start;
  reg capture_write = 1'b0;
  reg [27:0] capture_offset = 28'd0;
  reg [31:0] capture_data = 32'd0;
  wire capture_word_ready;
  reg capture_finalize = 1'b0;
  reg capture_error = 1'b0;
  wire save_busy;
  wire save_ready;
  wire save_error;

  wire stage_write_valid;
  wire stage_write_is_save;
  wire [27:0] stage_write_offset;
  wire [31:0] stage_write_data;
  reg stage_write_ready = 1'b1;
  reg stage_write_error = 1'b0;

  reg save_read_request = 1'b0;
  reg [27:0] save_read_offset = 28'd0;
  wire save_read_permitted;
  wire save_header_select;
  wire [31:0] save_header_data;
  wire save_payload_read_request;
  wire [27:0] save_payload_read_offset;

  reg restore_read_request = 1'b0;
  reg [27:0] restore_read_offset = 28'd0;
  wire restore_read_permitted;

  reg [31:0] stage_mem [0:7];
  integer i;
  integer restore_pulses = 0;
  integer live_mutations = 0;
  integer accepted_stage_writes = 0;

  always #5 clk = ~clk;

  apf_savestate_staging #(
      .PAYLOAD_BYTES(PAYLOAD_BYTES),
      .FORMAT_ID(FORMAT_ID)
  ) dut (
      .clk(clk),
      .reset_n(reset_n),
      .load_write(load_write),
      .load_offset(load_offset),
      .load_data(load_data),
      .load_word_ready(load_word_ready),
      .load_finalize(load_finalize),
      .load_copy_active(load_copy_active),
      .load_validated(load_validated),
      .load_error(load_error),
      .load_busy(load_busy),
      .load_done(load_done),
      .restore_start(restore_start),
      .restore_complete(restore_complete),
      .restore_error(restore_error),
      .save_start(save_start),
      .capture_start(capture_start),
      .capture_write(capture_write),
      .capture_offset(capture_offset),
      .capture_data(capture_data),
      .capture_word_ready(capture_word_ready),
      .capture_finalize(capture_finalize),
      .capture_error(capture_error),
      .save_busy(save_busy),
      .save_ready(save_ready),
      .save_error(save_error),
      .stage_write_valid(stage_write_valid),
      .stage_write_is_save(stage_write_is_save),
      .stage_write_offset(stage_write_offset),
      .stage_write_data(stage_write_data),
      .stage_write_ready(stage_write_ready),
      .stage_write_error(stage_write_error),
      .save_read_request(save_read_request),
      .save_read_offset(save_read_offset),
      .save_read_permitted(save_read_permitted),
      .save_header_select(save_header_select),
      .save_header_data(save_header_data),
      .save_payload_read_request(save_payload_read_request),
      .save_payload_read_offset(save_payload_read_offset),
      .restore_read_request(restore_read_request),
      .restore_read_offset(restore_read_offset),
      .restore_read_permitted(restore_read_permitted)
  );

  always @(posedge clk) begin
    if (stage_write_valid && stage_write_ready) begin
      accepted_stage_writes <= accepted_stage_writes + 1;
      if (!stage_write_error)
        stage_mem[stage_write_offset[4:2]] <= stage_write_data;
    end

    if (restore_start) begin
      restore_pulses <= restore_pulses + 1;
      // This models the sole path that may begin mutating live machine state.
      live_mutations <= live_mutations + 1;
    end
  end

  task automatic pulse_save_start;
    begin
      @(negedge clk);
      save_start = 1'b1;
      @(negedge clk);
      save_start = 1'b0;
    end
  endtask

  task automatic send_capture(input [27:0] offset, input [31:0] data);
    begin
      @(negedge clk);
      capture_offset = offset;
      capture_data = data;
      capture_write = 1'b1;
      while (!capture_word_ready)
        @(negedge clk);
      @(negedge clk);
      capture_write = 1'b0;
    end
  endtask

  task automatic finalize_capture;
    begin
      @(negedge clk);
      capture_finalize = 1'b1;
      @(negedge clk);
      capture_finalize = 1'b0;
    end
  endtask

  task automatic send_load_word(input [27:0] offset, input [31:0] data);
    begin
      @(negedge clk);
      load_offset = offset;
      load_data = data;
      load_write = 1'b1;
      while (!load_word_ready)
        @(negedge clk);
      @(negedge clk);
      load_write = 1'b0;
    end
  endtask

  task automatic finalize_load;
    begin
      @(negedge clk);
      load_finalize = 1'b1;
      @(negedge clk);
      load_finalize = 1'b0;
    end
  endtask

  task automatic send_valid_header;
    begin
      send_load_word(28'd0, 32'h5357_414e);
      send_load_word(28'd4, 32'd1);
      send_load_word(28'd8, 32'd32);
      send_load_word(28'd12, PAYLOAD_BYTES);
      send_load_word(28'd16, TOTAL_BYTES);
      send_load_word(28'd20, FORMAT_ID);
      send_load_word(28'd24, 32'd0);
      send_load_word(28'd28, 32'd0);
    end
  endtask

  task automatic expect_no_restore(input [255:0] label_text);
    integer baseline;
    begin
      baseline = restore_pulses;
      repeat (4) @(posedge clk);
      if (restore_pulses != baseline || live_mutations != restore_pulses)
        $fatal(1, "%0s reached live restore: pulses=%0d mutations=%0d",
               label_text, restore_pulses, live_mutations);
    end
  endtask

  initial begin
    for (i = 0; i < 8; i = i + 1)
      stage_mem[i] = 32'hdead_0000 | i;

    repeat (3) @(posedge clk);
    reset_n = 1'b1;

    // A0 must expose neither a header nor payload before an exact capture.
    save_read_request = 1'b1;
    save_read_offset = 28'd0;
    #1;
    if (save_read_permitted || save_header_select)
      $fatal(1, "partial/unstarted A0 image was readable");
    save_read_request = 1'b0;

    pulse_save_start();
    if (!capture_start && !save_busy)
      $fatal(1, "A0 capture did not start");
    for (i = 0; i < 7; i = i + 1)
      send_capture(28'(i * 4), 32'ha000_0000 | i);
    finalize_capture();
    if (!save_error || save_ready || save_busy)
      $fatal(1, "short A0 capture was not rejected");

    // A held capture valid survives backend backpressure and is accepted once.
    pulse_save_start();
    stage_write_ready = 1'b0;
    @(negedge clk);
    capture_offset = 28'd0;
    capture_data = 32'hb000_0000;
    capture_write = 1'b1;
    repeat (3) begin
      @(posedge clk);
      if (capture_word_ready)
        $fatal(1, "capture claimed ready while backend was stalled");
    end
    @(negedge clk);
    stage_write_ready = 1'b1;
    @(negedge clk);
    capture_write = 1'b0;
    for (i = 1; i < 8; i = i + 1)
      send_capture(28'(i * 4), 32'hb000_0000 | i);

    // Once the exact count is present, finalize still must not ignore a raw
    // extra valid that has not completed its backend handshake.
    stage_write_ready = 1'b0;
    @(negedge clk);
    capture_offset = 28'd28;
    capture_data = 32'hbad0_0007;
    capture_write = 1'b1;
    capture_finalize = 1'b1;
    @(negedge clk);
    capture_write = 1'b0;
    capture_finalize = 1'b0;
    if (!save_error || save_ready || save_busy)
      $fatal(1, "A0 finalize consumed an unhandshaken extra word");

    stage_write_ready = 1'b1;
    pulse_save_start();
    for (i = 0; i < 8; i = i + 1)
      send_capture(28'(i * 4), 32'hb000_0000 | i);
    finalize_capture();
    if (!save_ready || save_busy || save_error)
      $fatal(1, "exact A0 capture did not become ready");
    for (i = 0; i < 8; i = i + 1)
      if (stage_mem[i] !== (32'hb000_0000 | i))
        $fatal(1, "A0 staged word %0d mismatch: %08x", i, stage_mem[i]);

    save_read_request = 1'b1;
    save_read_offset = 28'd0;
    #1;
    if (!save_read_permitted || !save_header_select ||
        save_header_data !== 32'h5357_414e)
      $fatal(1, "ready A0 header was not synthesized");
    save_read_offset = 28'd32;
    #1;
    if (!save_read_permitted || save_header_select ||
        !save_payload_read_request || save_payload_read_offset !== 28'd0)
      $fatal(1, "ready A0 payload read was not authorized");
    save_read_offset = 28'd64;
    #1;
    if (save_read_permitted || save_payload_read_request)
      $fatal(1, "out-of-range A0 read was authorized");
    save_read_offset = 28'd2;
    #1;
    if (save_read_permitted)
      $fatal(1, "misaligned A0 read was authorized");
    save_read_request = 1'b0;

    // If A0 and offset-zero A4 arrive together, A4 deterministically owns the
    // shared staging image and A0 is rejected without a capture pulse.
    @(negedge clk);
    load_offset = 28'd0;
    load_data = 32'h5357_414e;
    load_write = 1'b1;
    save_start = 1'b1;
    if (!load_word_ready)
      $fatal(1, "simultaneous A4 transaction start was not accepted");
    @(negedge clk);
    load_write = 1'b0;
    save_start = 1'b0;
    if (capture_start || !save_error || !load_busy || !load_copy_active)
      $fatal(1, "simultaneous A0/A4 start was not resolved fail-closed");
    finalize_load();
    if (!load_error)
      $fatal(1, "header-only simultaneous A4 transaction did not fail");
    expect_no_restore("simultaneous A0/A4");

    // Bad magic and a short transfer may overwrite staging but cannot produce
    // the only live-mutation pulse.
    send_load_word(28'd0, 32'h4241_4421);
    finalize_load();
    if (!load_error || load_done)
      $fatal(1, "bad-magic A4 transfer did not fail");
    expect_no_restore("bad magic");

    send_valid_header();
    send_load_word(28'd32, 32'hc000_0000);
    finalize_load();
    if (!load_error)
      $fatal(1, "short A4 payload did not fail");
    expect_no_restore("short payload");

    send_load_word(28'd0, 32'h5357_414e);
    send_load_word(28'd8, 32'd32);
    finalize_load();
    if (!load_error)
      $fatal(1, "gapped A4 header did not fail");
    expect_no_restore("gapped header");

    // A finalize pulse cannot consume a payload valid that is still held under
    // backend backpressure.  The early finalize fails, and later acceptance of
    // that held word cannot resurrect the transaction.
    send_valid_header();
    send_load_word(28'd32, 32'hcc00_0000);
    stage_write_ready = 1'b0;
    @(negedge clk);
    load_offset = 28'd36;
    load_data = 32'hcc00_0001;
    load_write = 1'b1;
    load_finalize = 1'b1;
    @(negedge clk);
    load_finalize = 1'b0;
    repeat (2) @(posedge clk);
    if (load_word_ready || !load_error)
      $fatal(1, "unhandshaken load valid escaped early finalize rejection");
    @(negedge clk);
    stage_write_ready = 1'b1;
    while (!load_word_ready)
      @(negedge clk);
    @(negedge clk);
    load_write = 1'b0;
    expect_no_restore("finalize with unhandshaken valid");

    // A structurally valid blob with a failed staging write is also barred.
    send_valid_header();
    stage_write_error = 1'b1;
    for (i = 0; i < 8; i = i + 1)
      send_load_word(28'(32 + i * 4), 32'hd000_0000 | i);
    stage_write_error = 1'b0;
    finalize_load();
    if (!load_error)
      $fatal(1, "backend-failed A4 transfer did not fail");
    expect_no_restore("backend error");

    // A valid A4 transfer remains non-mutating while its final staged word is
    // pending, even though APF has already issued Request Load.
    send_valid_header();
    send_load_word(28'd32, 32'he000_0000);
    stage_write_ready = 1'b0;
    @(negedge clk);
    load_offset = 28'd36;
    load_data = 32'he000_0001;
    load_write = 1'b1;
    repeat (2) begin
      @(posedge clk);
      if (load_word_ready)
        $fatal(1, "load ingress claimed ready with a pending backend word");
    end
    @(negedge clk);
    stage_write_ready = 1'b1;
    while (!load_word_ready)
      @(negedge clk);
    @(negedge clk);
    load_write = 1'b0;
    for (i = 2; i < 7; i = i + 1)
      send_load_word(28'(32 + i * 4), 32'he000_0000 | i);
    send_load_word(28'd60, 32'he000_0007);
    stage_write_ready = 1'b0;
    finalize_load();
    repeat (3) @(posedge clk);
    if (load_validated || restore_pulses != 0 || live_mutations != 0)
      $fatal(1, "A4 restore escaped before final staging acknowledgement");

    @(negedge clk);
    stage_write_ready = 1'b1;
    repeat (4) @(posedge clk);
    if (restore_pulses != 1 || live_mutations != 1 || !load_busy || load_error)
      $fatal(1, "validated A4 did not start exactly one restore");
    for (i = 0; i < 8; i = i + 1)
      if (stage_mem[i] !== (32'he000_0000 | i))
        $fatal(1, "A4 staged word %0d mismatch: %08x", i, stage_mem[i]);

    restore_read_request = 1'b1;
    restore_read_offset = 28'd28;
    #1;
    if (!restore_read_permitted)
      $fatal(1, "validated in-range restore read was blocked");
    restore_read_offset = 28'd32;
    #1;
    if (restore_read_permitted)
      $fatal(1, "out-of-range restore read was authorized");
    restore_read_offset = 28'd2;
    #1;
    if (restore_read_permitted)
      $fatal(1, "misaligned restore read was authorized");
    restore_read_request = 1'b0;

    @(negedge clk);
    restore_complete = 1'b1;
    @(negedge clk);
    restore_complete = 1'b0;
    repeat (2) @(posedge clk);
    if (!load_done || load_busy || load_error)
      $fatal(1, "successful restore did not reach A4 done");
    restore_read_request = 1'b1;
    restore_read_offset = 28'd0;
    #1;
    if (restore_read_permitted)
      $fatal(1, "restore read remained authorized after completion");

    $display("PASS APF savestate staging A0_exact=32 A4_exact=64 malformed_no_mutation=6 deferred_ack=1");
    $finish;
  end
endmodule
