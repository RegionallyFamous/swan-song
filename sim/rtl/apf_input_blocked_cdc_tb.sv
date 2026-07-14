`timescale 1ns/1ps

module apf_input_blocked_cdc_tb;
  reg clk_source = 1'b0;
  reg clk_destination = 1'b0;
  always #5 clk_source = ~clk_source;
  always #7 clk_destination = ~clk_destination;

  reg reset_n_async = 1'b0;
  reg [15:0] buttons_source = 16'hffff;
  reg input_blocked_source = 1'b0;
  wire [15:0] buttons_destination;
  wire input_blocked_destination;
  integer errors = 0;
  reg saw_first_coalesced_payload = 1'b0;

  apf_input_blocked_cdc dut (
      .clk_source(clk_source),
      .clk_destination(clk_destination),
      .reset_n_async(reset_n_async),
      .buttons_source(buttons_source),
      .input_blocked_source(input_blocked_source),
      .buttons_destination(buttons_destination),
      .input_blocked_destination(input_blocked_destination)
  );

  task automatic fail(input string message);
    begin
      $display("FAIL: %s", message);
      errors = errors + 1;
    end
  endtask

  task automatic drive_source(
      input bit blocked,
      input [15:0] buttons
  );
    begin
      @(negedge clk_source);
      input_blocked_source = blocked;
      buttons_source = buttons;
    end
  endtask

  task automatic wait_payload(
      input bit expected_blocked,
      input [15:0] expected_buttons,
      input string message
  );
    integer edges;
    begin
      edges = 0;
      while ({input_blocked_destination, buttons_destination} !==
             {expected_blocked, expected_buttons} && edges < 16) begin
        @(posedge clk_destination);
        #1;
        edges = edges + 1;
      end
      if ({input_blocked_destination, buttons_destination} !==
          {expected_blocked, expected_buttons})
        fail(message);
    end
  endtask

  task automatic wait_source_idle;
    integer edges;
    begin
      edges = 0;
      while (!dut.transfer_idle_source && edges < 16) begin
        @(posedge clk_source);
        #1;
        edges = edges + 1;
      end
      if (!dut.transfer_idle_source)
        fail("source handshake did not return to idle");
    end
  endtask

  // Every destination update must be one complete state from this test's
  // source sequence. Any bitwise/vector synchronizer implementation can be
  // adversarially skewed into a value outside this set in hardware.
  always @(posedge clk_destination) begin
    #1;
    if ({input_blocked_destination, buttons_destination} === 17'h0_00f0)
      saw_first_coalesced_payload = 1'b1;
    if (reset_n_async &&
        {input_blocked_destination, buttons_destination} !== 17'h1_0000 &&
        {input_blocked_destination, buttons_destination} !== 17'h0_a55a &&
        {input_blocked_destination, buttons_destination} !== 17'h0_5aa5 &&
        {input_blocked_destination, buttons_destination} !== 17'h0_0000 &&
        {input_blocked_destination, buttons_destination} !== 17'h0_00f0 &&
        {input_blocked_destination, buttons_destination} !== 17'h0_f00f)
      fail($sformatf("destination exposed torn payload %05h",
                     {input_blocked_destination, buttons_destination}));
  end

  initial begin
    #2;
    if ({input_blocked_destination, buttons_destination} !== 17'h1_0000)
      fail("asynchronous reset did not immediately publish blocked+zero");

    // Reset release cannot expose the live source bus. It takes one complete
    // request/acknowledge transfer to publish the first unblocked snapshot.
    @(negedge clk_source);
    buttons_source = 16'ha55a;
    reset_n_async = 1'b1;
    repeat (2) begin
      @(posedge clk_destination);
      #1;
      if ({input_blocked_destination, buttons_destination} !== 17'h1_0000)
        fail("destination released safe reset state before atomic capture");
    end
    wait_payload(1'b0, 16'ha55a,
                 "first complete button snapshot did not cross");

    // A transition which flips every button bit must be captured in one edge.
    drive_source(1'b0, 16'h5aa5);
    wait_payload(1'b0, 16'h5aa5,
                 "complementary multi-button snapshot did not cross");

    // Focus assertion is canonicalized: even a hostile non-zero source bitmap
    // arrives only as the indivisible blocked+zero payload.
    drive_source(1'b1, 16'hffff);
    wait_payload(1'b1, 16'h0000,
                 "focus assertion did not atomically block and zero buttons");

    // Neutral rearm is the inverse ownership boundary and must likewise arrive
    // as neutral+unblocked on one destination edge.
    drive_source(1'b0, 16'h0000);
    wait_payload(1'b0, 16'h0000,
                 "neutral rearm did not atomically release ownership");

    // Change the source again while the first request is still in flight. The
    // held payload must not tear; the latest state is sent after acknowledgement.
    wait_source_idle();
    drive_source(1'b0, 16'h00f0);
    @(posedge clk_source);
    #1;
    if (dut.payload_hold_source !== 17'h0_00f0)
      fail("first queued payload was not frozen at the source boundary");
    drive_source(1'b0, 16'hf00f);
    @(posedge clk_source);
    #1;
    if (dut.payload_hold_source !== 17'h0_00f0)
      fail("in-flight source payload changed before destination acknowledgement");
    wait_payload(1'b0, 16'hf00f,
                 "coalesced follow-up payload did not reach destination");
    if (!saw_first_coalesced_payload)
      fail("destination skipped the frozen in-flight complete payload");

    // Host reset is the asynchronous fail-closed override in both domains.
    #1;
    reset_n_async = 1'b0;
    #1;
    if ({input_blocked_destination, buttons_destination} !== 17'h1_0000)
      fail("late asynchronous reset did not restore blocked+zero immediately");

    if (errors != 0)
      $fatal(1, "atomic input-state CDC failed with %0d errors", errors);

    $display("PASS atomic buttons+ownership CDC, coalescing, neutral rearm, and reset");
    $finish;
  end
endmodule
