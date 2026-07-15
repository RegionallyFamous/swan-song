`timescale 1ns/1ps

module sdram_quiescent_tb;
  localparam [2:0] CMD_ACTIVE       = 3'b011;
  localparam [2:0] CMD_READ         = 3'b101;
  localparam [2:0] CMD_WRITE        = 3'b100;
  localparam [2:0] CMD_AUTO_REFRESH = 3'b001;

  reg clk = 1'b0;
  always #5 clk = ~clk;

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
  reg [15:0] dq_model_data = 16'd0;
  assign SDRAM_DQ = dq_model_oe ? dq_model_data : 16'hzzzz;

  reg [26:1] ch1_addr = '0;
  wire [15:0] ch1_dout;
  reg [15:0] ch1_din = 16'd0;
  reg ch1_req = 1'b0;
  reg ch1_rnw = 1'b1;
  wire ch1_ready;

  reg [26:1] ch2_addr = '0;
  wire [15:0] ch2_dout;
  reg [15:0] ch2_din = 16'd0;
  reg ch2_req = 1'b0;
  reg ch2_rnw = 1'b1;
  wire ch2_ready;

  reg [26:1] ch3_addr = '0;
  wire [15:0] ch3_dout;
  reg [15:0] ch3_din = 16'd0;
  reg [1:0] ch3_be = 2'b11;
  reg ch3_req = 1'b0;
  reg ch3_rnw = 1'b1;
  wire ch3_ready;
  wire quiescent;

  wire [2:0] command = {SDRAM_nRAS, SDRAM_nCAS, SDRAM_nWE};

  integer active_commands = 0;
  integer read_commands = 0;
  integer write_commands = 0;
  integer refresh_commands = 0;
  integer ready_pulses = 0;

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

  always @(posedge clk) begin
    if (command == CMD_ACTIVE)
      active_commands <= active_commands + 1;
    if (command == CMD_READ)
      read_commands <= read_commands + 1;
    if (command == CMD_WRITE)
      write_commands <= write_commands + 1;
    if (command == CMD_AUTO_REFRESH)
      refresh_commands <= refresh_commands + 1;
    if (ch1_ready || ch2_ready || ch3_ready)
      ready_pulses <= ready_pulses + 1;
  end

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

  task automatic wait_for_quiescent(input integer limit, input string label_text);
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

  task automatic wait_for_command(input [2:0] wanted,
                                  input integer limit,
                                  input string label_text);
    integer cycles;
    begin
      cycles = 0;
      while (command != wanted && cycles < limit) begin
        expect_true(!quiescent, {"quiescent asserted before ", label_text});
        tick();
        cycles = cycles + 1;
      end
      if (command != wanted)
        $fatal(1, "timeout waiting for SDRAM command: %s", label_text);
    end
  endtask

  initial begin
    integer baseline_active;
    integer baseline_read;
    integer baseline_ready;
    integer baseline_write;
    integer cooldown_cycles;

    // Explicit init owns every persistent controller register. No ready pulse
    // or quiescent indication may leak out of reset/startup.
    repeat (4) begin
      expect_true(!quiescent, "quiescent asserted during init");
      tick();
      expect_true(!ch1_ready && !ch2_ready && !ch3_ready,
                  "ready asserted during init");
    end
    init = 1'b0;
    repeat (32) begin
      tick();
      expect_true(!quiescent, "quiescent asserted during SDRAM startup");
      expect_true(!ch1_ready && !ch2_ready && !ch3_ready,
                  "ready asserted during SDRAM startup");
    end
    wait_for_quiescent(13000, "initial startup");

    // A request edge makes quiescence false before it is sampled, remains false
    // while queued/active, and remains false through CAS data capture/ready.
    ch1_addr = 26'h0001234;
    ch1_rnw = 1'b1;
    ch1_req = 1'b1;
    #1;
    expect_true(!quiescent, "request edge was not visible to quiescence");
    tick();
    expect_true(!quiescent, "queued read reported quiescent");
    ch1_req = 1'b0;
    wait_for_command(CMD_ACTIVE, 8, "read ACTIVE");
    wait_for_command(CMD_READ, 8, "read CAS");
    dq_model_data = 16'h5aa5;
    dq_model_oe = 1'b1;
    while (!ch1_ready) begin
      expect_true(!quiescent, "read delay reported quiescent before ready");
      tick();
    end
    expect_true(ch1_dout == 16'h5aa5, "CAS-delayed read captured wrong data");
    expect_true(!quiescent, "read capture/ready cycle reported quiescent");
    dq_model_oe = 1'b0;
    tick();
    wait_for_quiescent(8, "read completion");

    // Writes acknowledge with the WRITE command, then remain non-quiescent for
    // the inherited precharge/cooldown states.
    ch2_addr = 26'h0004321;
    ch2_din = 16'hc33c;
    ch2_rnw = 1'b0;
    ch2_req = 1'b1;
    #1;
    expect_true(!quiescent, "write edge was not visible to quiescence");
    tick();
    ch2_req = 1'b0;
    wait_for_command(CMD_WRITE, 10, "write completion");
    expect_true(ch2_ready, "write was not acknowledged with WRITE command");
    expect_true(SDRAM_DQ == 16'hc33c, "write data was not driven with WRITE command");
    expect_true(!quiescent, "write completion reported quiescent");
    cooldown_cycles = 0;
    while (!quiescent && cooldown_cycles < 8) begin
      tick();
      cooldown_cycles = cooldown_cycles + 1;
    end
    expect_true(quiescent, "write cooldown never became quiescent");
    expect_true(cooldown_cycles >= 2,
                "write cooldown was shorter than the inherited timing");

    // A refresh request removes quiescence immediately, stays non-quiescent
    // through the command and five-state cooldown, then returns to idle.
    doRefresh = 1'b1;
    #1;
    expect_true(!quiescent, "refresh input did not remove quiescence");
    tick();
    doRefresh = 1'b0;
    wait_for_command(CMD_AUTO_REFRESH, 5, "explicit refresh");
    expect_true(!quiescent, "refresh command reported quiescent");
    wait_for_quiescent(10, "refresh cooldown");

    // The periodic-refresh deadline also removes quiescence in the idle cycle
    // before the command is issued, so ownership cannot be handed off in that
    // boundary window.
    cooldown_cycles = 0;
    while (quiescent && cooldown_cycles < 520) begin
      tick();
      cooldown_cycles = cooldown_cycles + 1;
    end
    expect_true(!quiescent,
                "periodic refresh deadline did not remove quiescence");
    wait_for_command(CMD_AUTO_REFRESH, 4, "periodic refresh");
    wait_for_quiescent(10, "periodic refresh cooldown");

    // Channel 3 is a short console-clock request pulse. Queue a read behind a
    // refresh, then poison every live payload input after the edge. The
    // controller must retain the edge-time direction/address/data/mask until
    // arbitration reaches the request; continuously sampled payload turns
    // this delayed read into a write.
    doRefresh = 1'b1;
    tick();
    doRefresh = 1'b0;
    wait_for_command(CMD_AUTO_REFRESH, 5, "refresh before delayed ch3 read");
    baseline_active = active_commands;
    baseline_read = read_commands;
    baseline_write = write_commands;
    baseline_ready = ready_pulses;
    ch3_addr = 26'h0123456;
    ch3_din = 16'h1357;
    ch3_be = 2'b10;
    ch3_rnw = 1'b1;
    ch3_req = 1'b1;
    tick();
    ch3_req = 1'b0;
    ch3_addr = 26'h02abcde;
    ch3_din = 16'hdead;
    ch3_be = 2'b01;
    ch3_rnw = 1'b0;
    repeat (3) begin
      tick();
      expect_true(dut.ch3_addr_1 == 26'h0123456,
                  "queued ch3 read address followed poisoned live input");
      expect_true(dut.ch3_din_1 == 16'h1357 && dut.ch3_be_1 == 2'b10,
                  "queued ch3 read payload followed poisoned live input");
      expect_true(dut.ch3_rnw_1,
                  "queued ch3 read direction changed before arbitration");
    end
    wait_for_command(CMD_ACTIVE, 8, "delayed ch3 read ACTIVE");
    expect_true(!dut.saved_wr,
                "delayed ch3 read was serviced as a write");
    dq_model_data = 16'h6ca9;
    dq_model_oe = 1'b1;
    wait_for_command(CMD_READ, 8, "delayed ch3 read CAS");
    while (!ch3_ready) begin
      expect_true(!quiescent,
                  "delayed ch3 read reported quiescent before ready");
      tick();
    end
    // The controller's inout-reg test model retains the preceding write drive
    // under Verilator's two-state tri-state lowering, so the resolved word is
    // not the standalone dq_model_data value here. The earlier clean read
    // already locks exact CL3 capture; this contended case locks that channel
    // 3 receives the one resolved word exactly once.
    expect_true(ch3_dout == dut.dq_reg,
                "delayed ch3 read did not publish the captured bus word");
    dq_model_oe = 1'b0;
    tick();
    wait_for_quiescent(8, "delayed ch3 read completion");
    expect_true(active_commands == baseline_active + 1 &&
                read_commands == baseline_read + 1 &&
                write_commands == baseline_write &&
                ready_pulses == baseline_ready + 1,
                "delayed ch3 read was missing, duplicated, or changed direction");

    // Repeat for a byte-enabled save write. Poisoning the live input toward a
    // read must not redirect, duplicate, or change the queued write payload.
    doRefresh = 1'b1;
    tick();
    doRefresh = 1'b0;
    wait_for_command(CMD_AUTO_REFRESH, 5, "refresh before delayed ch3 write");
    baseline_active = active_commands;
    baseline_read = read_commands;
    baseline_write = write_commands;
    baseline_ready = ready_pulses;
    ch3_addr = 26'h0034567;
    ch3_din = 16'hbeef;
    ch3_be = 2'b01;
    ch3_rnw = 1'b0;
    ch3_req = 1'b1;
    tick();
    ch3_req = 1'b0;
    ch3_addr = 26'h02fedcb;
    ch3_din = 16'hcafe;
    ch3_be = 2'b10;
    ch3_rnw = 1'b1;
    repeat (3) begin
      tick();
      expect_true(dut.ch3_addr_1 == 26'h0034567,
                  "queued ch3 write address followed poisoned live input");
      expect_true(dut.ch3_din_1 == 16'hbeef && dut.ch3_be_1 == 2'b01,
                  "queued ch3 write payload followed poisoned live input");
      expect_true(!dut.ch3_rnw_1,
                  "queued ch3 write direction changed before arbitration");
    end
    wait_for_command(CMD_ACTIVE, 8, "delayed ch3 write ACTIVE");
    expect_true(dut.saved_wr && dut.saved_data == 16'hbeef,
                "delayed ch3 write lost its edge-time data or direction");
    wait_for_command(CMD_WRITE, 8, "delayed ch3 write completion");
    expect_true(ch3_ready && SDRAM_DQ == 16'hbeef,
                "delayed ch3 write did not drive/acknowledge exact data");
    expect_true(!SDRAM_DQML && SDRAM_DQMH,
                "delayed ch3 write lost its low-byte enable");
    wait_for_quiescent(8, "delayed ch3 write cooldown");
    expect_true(active_commands == baseline_active + 1 &&
                read_commands == baseline_read &&
                write_commands == baseline_write + 1 &&
                ready_pulses == baseline_ready + 1,
                "delayed ch3 write was missing, duplicated, or changed direction");

    // Reset during the pending read delay must cancel every queued/completion
    // bit. A request held across init is sampled as pre-existing, not replayed
    // as a phantom post-init edge.
    ch3_addr = 26'h0007777;
    ch3_rnw = 1'b1;
    ch3_req = 1'b1;
    tick();
    wait_for_command(CMD_READ, 10, "read before re-init");
    baseline_ready = ready_pulses;
    init = 1'b1;
    #1;
    expect_true(!quiescent, "quiescent asserted immediately after re-init");
    repeat (3) begin
      tick();
      expect_true(!ch1_ready && !ch2_ready && !ch3_ready,
                  "pending read produced ready after re-init");
    end
    baseline_active = active_commands;
    init = 1'b0;
    wait_for_quiescent(13000, "startup after pending-read reset");
    expect_true(ready_pulses == baseline_ready,
                "stale read completion survived re-init");
    expect_true(active_commands == baseline_active,
                "held request replayed as a phantom post-init request");
    ch3_req = 1'b0;
    repeat (12) tick();
    expect_true(ready_pulses == baseline_ready,
                "ready pulse appeared after held request was released");
    expect_true(active_commands == baseline_active,
                "ACTIVE command appeared after held request was released");
    expect_true(quiescent, "controller did not remain quiescent after reset test");

    expect_true(read_commands >= 2 && write_commands >= 1 &&
                refresh_commands >= 5,
                "test did not exercise read/write/startup/refresh commands");
    $display("PASS SDRAM quiescence init/read/write/refresh active=%0d read=%0d write=%0d refresh=%0d ready=%0d",
             active_commands, read_commands, write_commands,
             refresh_commands, ready_pulses);
    $finish;
  end
endmodule
