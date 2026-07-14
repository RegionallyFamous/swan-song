`timescale 1ns/1ps

module sdram_cl3_capture_tb;
  localparam [2:0] CMD_READ = 3'b101;
  localparam [15:0] POISON = 16'hdeaf;
  localparam realtime CLK_HALF_NS = 4.521;
  localparam realtime READ_MAX_NS = 5.9;

  reg clk = 1'b0;
  always #(CLK_HALF_NS) clk = ~clk;

  reg init = 1'b1;
  reg doRefresh = 1'b0;

  wire [15:0] SDRAM_DQ;
  wire [12:0] SDRAM_A;
  wire SDRAM_DQML;
  wire SDRAM_DQMH;
  wire [1:0] SDRAM_BA;
  wire SDRAM_nCS;
  wire SDRAM_nWE;
  wire SDRAM_nRAS;
  wire SDRAM_nCAS;
  wire SDRAM_CKE;
  wire SDRAM_CLK;

  reg dq_model_oe = 1'b0;
  reg [15:0] dq_model_data = POISON;
  assign SDRAM_DQ = dq_model_oe ? dq_model_data : 16'hzzzz;

  reg [26:1] ch1_addr = '0;
  wire [15:0] ch1_dout;
  reg [15:0] ch1_din = '0;
  reg ch1_req = 1'b0;
  reg ch1_rnw = 1'b1;
  wire ch1_ready;

  reg [26:1] ch2_addr = '0;
  wire [15:0] ch2_dout;
  reg [15:0] ch2_din = '0;
  reg ch2_req = 1'b0;
  reg ch2_rnw = 1'b1;
  wire ch2_ready;

  reg [26:1] ch3_addr = '0;
  wire [15:0] ch3_dout;
  reg [15:0] ch3_din = '0;
  reg [1:0] ch3_be = 2'b11;
  reg ch3_req = 1'b0;
  reg ch3_rnw = 1'b1;
  wire ch3_ready;
  wire quiescent;

  wire [2:0] command = {SDRAM_nRAS, SDRAM_nCAS, SDRAM_nWE};
  integer cycle_count = 0;

  sdram dut (
      .init(init),
      .clk(clk),
      .doRefresh(doRefresh),
      .SDRAM_DQ(SDRAM_DQ),
      .SDRAM_A(SDRAM_A),
      .SDRAM_DQML(SDRAM_DQML),
      .SDRAM_DQMH(SDRAM_DQMH),
      .SDRAM_BA(SDRAM_BA),
      .SDRAM_nCS(SDRAM_nCS),
      .SDRAM_nWE(SDRAM_nWE),
      .SDRAM_nRAS(SDRAM_nRAS),
      .SDRAM_nCAS(SDRAM_nCAS),
      .SDRAM_CKE(SDRAM_CKE),
      .SDRAM_CLK(SDRAM_CLK),
      .ch1_addr(ch1_addr),
      .ch1_dout(ch1_dout),
      .ch1_din(ch1_din),
      .ch1_req(ch1_req),
      .ch1_rnw(ch1_rnw),
      .ch1_ready(ch1_ready),
      .ch2_addr(ch2_addr),
      .ch2_dout(ch2_dout),
      .ch2_din(ch2_din),
      .ch2_req(ch2_req),
      .ch2_rnw(ch2_rnw),
      .ch2_ready(ch2_ready),
      .ch3_addr(ch3_addr),
      .ch3_dout(ch3_dout),
      .ch3_din(ch3_din),
      .ch3_be(ch3_be),
      .ch3_req(ch3_req),
      .ch3_rnw(ch3_rnw),
      .ch3_ready(ch3_ready),
      .quiescent(quiescent)
  );

  always @(posedge clk)
    cycle_count <= cycle_count + 1;

  task automatic tick;
    begin
      @(posedge clk);
      #1;
    end
  endtask

  task automatic expect_true(input bit condition, input string message);
    begin
      if (!condition)
        $fatal(1, "%s", message);
    end
  endtask

  task automatic expect_no_ready(input string phase);
    begin
      if (ch1_ready || ch2_ready || ch3_ready)
        $fatal(1, "unexpected ready during %s", phase);
    end
  endtask

  task automatic wait_for_quiescent(input integer limit,
                                    input string label_text);
    integer cycles;
    begin
      cycles = 0;
      while (!quiescent && cycles < limit) begin
        tick();
        cycles = cycles + 1;
      end
      if (!quiescent)
        $fatal(1, "timeout waiting for quiescence: %s", label_text);
    end
  endtask

  task automatic wait_for_read_command(input integer limit,
                                       input string label_text);
    integer cycles;
    begin
      cycles = 0;
      while (command != CMD_READ && cycles < limit) begin
        expect_no_ready({label_text, " command wait"});
        tick();
        cycles = cycles + 1;
      end
      if (command != CMD_READ)
        $fatal(1, "timeout waiting for READ command: %s", label_text);
    end
  endtask

  task automatic set_request(input integer channel, input bit value);
    begin
      case (channel)
        1: ch1_req = value;
        2: ch2_req = value;
        3: ch3_req = value;
        default: $fatal(1, "invalid SDRAM test channel %0d", channel);
      endcase
    end
  endtask

  task automatic expect_channel_ready(input integer channel,
                                      input [15:0] expected);
    begin
      case (channel)
        1: begin
          expect_true(ch1_ready && !ch2_ready && !ch3_ready,
                      "channel 1 ready routing mismatch");
          expect_true(ch1_dout == expected,
                      "channel 1 returned the wrong CL3 sample");
        end
        2: begin
          expect_true(!ch1_ready && ch2_ready && !ch3_ready,
                      "channel 2 ready routing mismatch");
          expect_true(ch2_dout == expected,
                      "channel 2 returned the wrong CL3 sample");
        end
        3: begin
          expect_true(!ch1_ready && !ch2_ready && ch3_ready,
                      "channel 3 ready routing mismatch");
          expect_true(ch3_dout == expected,
                      "channel 3 returned the wrong CL3 sample");
        end
        default: $fatal(1, "invalid SDRAM test channel %0d", channel);
      endcase
    end
  endtask

  task automatic run_cl3_read(input integer channel,
                              input [15:0] expected);
    integer read_cycle;
    begin
      wait_for_quiescent(16, "before CL3 read");
      dq_model_oe = 1'b1;
      dq_model_data = POISON;

      set_request(channel, 1'b1);
      tick();
      set_request(channel, 1'b0);
      wait_for_read_command(10, "CL3 read");
      read_cycle = cycle_count;

      // The command is registered on r at the real 110.592 MHz clock rate.
      // Keep the old bus value through the positive-edge sample after r+2,
      // then present the word at the modeled 5.9 ns CL3 maximum before r+3.
      // This forces dq_reg to use the positive edge after r+3, not the earlier
      // sample which is outside the modeled valid window. Physical setup/hold
      // margins around that logical edge remain the responsibility of STA.
      @(posedge SDRAM_CLK);  // r
      @(posedge SDRAM_CLK);  // r+1
      @(posedge SDRAM_CLK);  // r+2
      #(READ_MAX_NS);
      expect_true(dut.dq_reg == POISON,
                  "dq_reg accepted data before the CL3 valid window");
      dq_model_data = expected;
      @(posedge SDRAM_CLK);  // r+3
      @(posedge clk);        // capture edge immediately after r+3
      #1;
      expect_true(cycle_count == read_cycle + 4,
                  "CL3 capture did not occur four clocks after READ");
      expect_true(dut.dq_reg == expected,
                  "dq_reg missed the CL3 data window");
      expect_no_ready("CL3 capture edge");

      // Poison DQ after capture. The ready cycle must consume the preceding
      // dq_reg sample, proving the intentional one-cycle handoff.
      dq_model_data = POISON;
      tick();
      expect_true(cycle_count == read_cycle + 5,
                  "request-to-ready latency changed from five clocks");
      expect_channel_ready(channel, expected);
      expect_true(dut.dq_reg == POISON,
                  "dq_reg did not continue sampling after the CL3 word");
      tick();
      expect_no_ready("cycle after CL3 ready pulse");
      dq_model_oe = 1'b0;
    end
  endtask

  initial begin
    integer reset_read_cycle;

    // Complete the controller's real startup sequence once; the read tests do
    // not bypass or force internal state.
    repeat (4) begin
      tick();
      expect_no_ready("initial reset");
    end
    init = 1'b0;
    wait_for_quiescent(13000, "initial startup");

    ch1_addr = 26'h0001111;
    ch2_addr = 26'h0002222;
    ch3_addr = 26'h0003333;
    run_cl3_read(1, 16'h1357);
    run_cl3_read(2, 16'h2468);
    run_cl3_read(3, 16'h5aa5);

    // Reset after a READ command but before r+3. It must clear the capture,
    // delayed-ready pipeline, and previously returned data, with no stale
    // completion after reset is released.
    wait_for_quiescent(16, "before reset cancellation read");
    dq_model_oe = 1'b1;
    dq_model_data = 16'hc33c;
    set_request(2, 1'b1);
    tick();
    set_request(2, 1'b0);
    wait_for_read_command(10, "reset cancellation read");
    reset_read_cycle = cycle_count;
    @(posedge SDRAM_CLK);  // r
    #1;
    init = 1'b1;
    tick();
    expect_true(cycle_count == reset_read_cycle + 1,
                "reset was not applied during the pending CL3 read");
    expect_no_ready("mid-read reset");
    expect_true(dut.dq_reg == 16'd0,
                "mid-read reset did not clear dq_reg");
    expect_true(ch1_dout == 16'd0 && ch2_dout == 16'd0 &&
                ch3_dout == 16'd0,
                "mid-read reset did not clear channel data outputs");
    repeat (7) begin
      tick();
      expect_no_ready("held mid-read reset");
      expect_true(dut.dq_reg == 16'd0,
                  "dq_reg sampled DQ while reset was held");
    end
    init = 1'b0;
    dq_model_oe = 1'b0;
    repeat (8) begin
      tick();
      expect_no_ready("post-reset cancellation window");
    end

    $display("PASS SDRAM CL3 capture/latency/reset channels=3 latency=5");
    $finish;
  end
endmodule
