`timescale 1ns/1ps

module apf_sdram_channel1_mux_tb;
  localparam integer ADDR_WIDTH = 25;

  reg clk = 1'b0;
  reg reset_n = 1'b0;
  always #5 clk = ~clk;

  reg stage_acquire = 1'b0;
  reg runtime_quiesced = 1'b0;
  wire stage_granted;
  wire protocol_error;

  reg rom_req = 1'b0;
  reg rom_rnw = 1'b1;
  reg [ADDR_WIDTH-1:0] rom_addr = 0;
  reg [15:0] rom_write_data = 0;
  wire rom_ready;
  wire [15:0] rom_read_data;

  reg stage_req = 1'b0;
  reg stage_rnw = 1'b1;
  reg [ADDR_WIDTH-1:0] stage_addr = 0;
  reg [15:0] stage_write_data = 0;
  wire stage_ready;
  wire [15:0] stage_read_data;

  wire sdram_req;
  wire sdram_rnw;
  wire [ADDR_WIDTH-1:0] sdram_addr;
  wire [15:0] sdram_write_data;
  reg sdram_ready = 1'b0;
  reg [15:0] sdram_read_data = 0;

  integer physical_requests = 0;
  reg previous_sdram_req = 1'b0;

  apf_sdram_channel1_mux #(
      .ADDR_WIDTH(ADDR_WIDTH)
  ) dut (
      .clk(clk),
      .reset_n(reset_n),
      .stage_acquire(stage_acquire),
      .runtime_quiesced(runtime_quiesced),
      .stage_granted(stage_granted),
      .protocol_error(protocol_error),
      .rom_req(rom_req),
      .rom_rnw(rom_rnw),
      .rom_addr(rom_addr),
      .rom_write_data(rom_write_data),
      .rom_ready(rom_ready),
      .rom_read_data(rom_read_data),
      .stage_req(stage_req),
      .stage_rnw(stage_rnw),
      .stage_addr(stage_addr),
      .stage_write_data(stage_write_data),
      .stage_ready(stage_ready),
      .stage_read_data(stage_read_data),
      .sdram_req(sdram_req),
      .sdram_rnw(sdram_rnw),
      .sdram_addr(sdram_addr),
      .sdram_write_data(sdram_write_data),
      .sdram_ready(sdram_ready),
      .sdram_read_data(sdram_read_data)
  );

  always @(posedge clk) begin
    previous_sdram_req <= sdram_req;
    if (sdram_req) begin
      physical_requests <= physical_requests + 1;
      if (previous_sdram_req)
        $fatal(1, "physical request was not a one-cycle edge");
    end
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

  task automatic complete_request(input [15:0] read_data);
    begin
      repeat (3) tick();
      sdram_read_data = read_data;
      sdram_ready = 1'b1;
      tick();
      sdram_ready = 1'b0;
      sdram_read_data = 16'd0;
      tick();
    end
  endtask

  initial begin
    repeat (3) tick();
    reset_n = 1'b1;
    tick();

    // Acquisition is impossible until the console-side drain is acknowledged.
    stage_acquire = 1'b1;
    repeat (2) tick();
    expect_true(!stage_granted, "stage ownership escaped before quiescence");

    // A ROM request already at the boundary wins over a simultaneous grant.
    runtime_quiesced = 1'b1;
    rom_rnw = 1'b0;
    rom_addr = 25'h0001234;
    rom_write_data = 16'ha55a;
    rom_req = 1'b1;
    tick();
    expect_true(sdram_req && !stage_granted, "ROM request did not win acquisition race");
    expect_true(!sdram_rnw && sdram_addr == 25'h0001234 &&
                sdram_write_data == 16'ha55a,
                "latched ROM request fields are wrong");
    rom_req = 1'b0;

    // Fields must remain stable while the inherited SDRAM controller stalls.
    repeat (3) begin
      tick();
      expect_true(sdram_addr == 25'h0001234 && sdram_write_data == 16'ha55a,
                  "ROM request fields changed before ready");
      expect_true(!rom_ready && !stage_ready,
                  "a client was acknowledged before SDRAM completion");
    end
    complete_request(16'hc001);
    expect_true(!stage_ready, "ROM completion leaked to stage client");

    repeat (5) begin
      tick();
      expect_true(!stage_granted && !sdram_req,
                  "stage owner changed inside six-cycle low guard");
    end
    tick();
    expect_true(stage_granted, "stage ownership was not granted after ROM drain");

    // A staging read uses the full 25-bit word address and routes data only to
    // the staging client.
    stage_rnw = 1'b1;
    stage_addr = 25'h0880000;
    stage_req = 1'b1;
    tick();
    expect_true(sdram_req && sdram_rnw && sdram_addr == 25'h0880000,
                "staging request was not forwarded exactly");
    stage_req = 1'b0;
    repeat (2) tick();
    sdram_read_data = 16'h5aa5;
    sdram_ready = 1'b1;
    tick();
    expect_true(stage_ready && stage_read_data == 16'h5aa5,
                "staging completion/data were not routed back");
    expect_true(!rom_ready, "staging completion leaked to ROM client");
    sdram_ready = 1'b0;
    sdram_read_data = 16'd0;
    tick();

    // A ROM word held while staging owns the channel must survive ownership
    // release; it is accepted after the exclusive window closes.
    rom_rnw = 1'b1;
    rom_addr = 25'h0002222;
    rom_req = 1'b1;
    repeat (2) tick();
    expect_true(!sdram_req, "ROM request escaped during stage ownership");
    stage_acquire = 1'b0;
    tick();
    repeat (6) begin
      tick();
      expect_true(!sdram_req,
                  "ROM request escaped inside six-cycle low release guard");
    end
    tick();
    expect_true(sdram_req && sdram_addr == 25'h0002222,
                "held ROM request was lost across stage release");
    rom_req = 1'b0;
    complete_request(16'hbeef);

    expect_true(physical_requests == 3,
                "unexpected physical request count before fail-closed case");
    expect_true(!protocol_error, "legal ownership sequence raised protocol error");

    // A staging request without an exclusive grant is rejected and records a
    // sticky integration fault without touching SDRAM.
    stage_req = 1'b1;
    stage_addr = 25'h0880002;
    tick();
    stage_req = 1'b0;
    tick();
    expect_true(protocol_error, "illegal staging request did not fail closed");
    expect_true(physical_requests == 3,
                "illegal staging request reached physical SDRAM");

    $display("PASS APF SDRAM channel1 mux requests=%0d race=rom drain=held fail_closed=1",
             physical_requests);
    $finish;
  end
endmodule
