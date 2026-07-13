`timescale 1ns/1ps

module apf_rom_plan_cdc_tb;
  reg reset_n = 1'b0;
  reg clk_74a = 1'b0;
  reg clk_mem = 1'b0;
  reg clk_sys = 1'b0;
  always #7 clk_74a = ~clk_74a;
  always #3 clk_mem = ~clk_mem;
  always #5 clk_sys = ~clk_sys;

  reg [24:0] rom_size_74a = 25'd0;
  reg commit_74a = 1'b0;
  wire busy_74a;
  wire rejected_74a;
  wire [24:0] rom_size_mem;
  wire valid_mem;
  wire [24:0] rom_size_sys;
  wire valid_sys;
  integer errors = 0;
  integer mem_pulses = 0;
  integer sys_pulses = 0;
  integer timeout;

  apf_rom_plan_cdc dut (
      .reset_n(reset_n),
      .clk_74a(clk_74a),
      .rom_size_74a(rom_size_74a),
      .commit_74a(commit_74a),
      .busy_74a(busy_74a),
      .rejected_74a(rejected_74a),
      .clk_mem(clk_mem),
      .rom_size_mem(rom_size_mem),
      .valid_mem(valid_mem),
      .clk_sys(clk_sys),
      .rom_size_sys(rom_size_sys),
      .valid_sys(valid_sys)
  );

  task automatic fail(input string message);
    begin
      $display("FAIL: %s", message);
      errors = errors + 1;
    end
  endtask

  task automatic commit(input [24:0] size);
    begin
      @(negedge clk_74a);
      rom_size_74a = size;
      commit_74a = 1'b1;
      @(negedge clk_74a);
      commit_74a = 1'b0;
    end
  endtask

  always @(posedge clk_mem) begin
    if (valid_mem) begin
      mem_pulses = mem_pulses + 1;
      if (rom_size_mem != 25'd917504)
        fail("memory destination captured a torn/wrong size");
    end
  end

  always @(posedge clk_sys) begin
    if (valid_sys) begin
      sys_pulses = sys_pulses + 1;
      if (rom_size_sys != 25'd917504)
        fail("system destination captured a torn/wrong size");
    end
  end

  initial begin
    repeat (4) @(negedge clk_74a);
    reset_n = 1'b1;
    repeat (4) @(negedge clk_74a);

    commit(25'd917504);
    // Mutating the source after commit must not alter the frozen transfer.
    rom_size_74a = 25'd196608;
    timeout = 0;
    while (busy_74a && timeout < 100) begin
      @(negedge clk_74a);
      timeout = timeout + 1;
    end
    repeat (4) @(negedge clk_74a);
    if (busy_74a)
      fail("broadcast did not receive both acknowledgements");
    if (mem_pulses != 1 || sys_pulses != 1)
      fail("broadcast did not deliver exactly once to both domains");
    if (rom_size_mem != 25'd917504 || rom_size_sys != 25'd917504)
      fail("destinations did not retain the coherent snapshot");

    // A second edge while the first transfer is busy is explicitly rejected.
    commit(25'd917504);
    @(negedge clk_74a);
    commit_74a = 1'b1;
    @(posedge clk_74a);
    #1;
    if (!rejected_74a)
      fail("busy transfer was not rejected");
    @(negedge clk_74a);
    commit_74a = 1'b0;

    if (errors != 0) begin
      $display("FAIL apf_rom_plan_cdc_tb errors=%0d", errors);
      $fatal(1);
    end
    $display("PASS APF ROM plan atomic broadcast to memory and system clocks");
    $finish;
  end
endmodule
