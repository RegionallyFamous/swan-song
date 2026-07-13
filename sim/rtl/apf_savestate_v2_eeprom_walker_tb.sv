`timescale 1ns/1ps
`default_nettype none

module apf_savestate_v2_eeprom_walker_tb;
  import apf_savestate_v2_layout_pkg::*;
  import apf_savestate_v2_eeprom_walker_pkg::*;

  logic clk = 1'b0;
  always #5 clk = ~clk;

  logic reset_n;
  logic freeze;
  logic frozen_ack;
  logic start;
  logic start_ready;
  logic abort_request;
  logic restore;
  logic select_internal;
  logic [7:0] model;
  logic [7:0] ramtype;
  logic busy;
  logic done;
  logic failed;
  logic [3:0] failure_reason;
  logic writes_committed;
  logic write_may_have_committed;
  logic poisoned;
  logic ownership_retained;

  logic stage_req;
  logic stage_write;
  logic [31:0] stage_offset;
  logic [31:0] stage_write_data;
  logic [31:0] stage_read_data;
  logic stage_ready;
  logic stage_error;

  logic mem_req;
  logic mem_write;
  logic [10:0] mem_addr;
  logic [15:0] mem_write_data;
  logic [15:0] mem_read_data;
  logic mem_ready;
  logic mem_error;

  apf_savestate_v2_eeprom_walker #(
      .MAX_WAIT_CYCLES(8)
  ) dut (
      .clk,
      .reset_n,
      .freeze,
      .frozen_ack,
      .start,
      .start_ready,
      .abort_request,
      .restore,
      .select_internal,
      .model,
      .ramtype,
      .busy,
      .done,
      .failed,
      .failure_reason,
      .writes_committed,
      .write_may_have_committed,
      .poisoned,
      .ownership_retained,
      .stage_req,
      .stage_write,
      .stage_offset,
      .stage_write_data,
      .stage_read_data,
      .stage_ready,
      .stage_error,
      .mem_req,
      .mem_write,
      .mem_addr,
      .mem_write_data,
      .mem_read_data,
      .mem_ready,
      .mem_error
  );

  logic [31:0] stage_memory [0:16383];
  logic [15:0] backing_memory [0:2047];
  logic [15:0] expected_backing [0:2047];

  logic [31:0] stage_offset_log [0:2047];
  logic [31:0] stage_data_log [0:2047];
  logic stage_write_log [0:2047];
  logic [10:0] mem_addr_log [0:2047];
  logic [15:0] mem_data_log [0:2047];
  logic mem_write_log [0:2047];

  integer unsigned checks;
  integer unsigned failures;
  integer stage_request_count;
  integer stage_completion_count;
  integer stage_read_request_count;
  integer stage_write_request_count;
  integer mem_request_count;
  integer mem_read_request_count;
  integer mem_write_request_count;
  integer mem_write_completions;
  integer first_write_stage_completions;
  integer done_pulse_count;
  integer failed_pulse_count;

  integer stage_response_delay;
  integer mem_response_delay;
  integer inject_stage_error_at;
  integer inject_mem_error_at;
  logic hold_stage_responses;
  logic hold_mem_responses;

  logic stage_pending;
  logic stage_pending_write;
  logic [31:0] stage_pending_offset;
  logic [31:0] stage_pending_data;
  logic stage_pending_error;
  integer stage_pending_delay;

  logic mem_pending;
  logic mem_pending_write;
  logic [10:0] mem_pending_addr;
  logic [15:0] mem_pending_data;
  logic mem_pending_error;
  integer mem_pending_delay;

  logic expected_internal;
  logic [7:0] expected_model;

  task automatic check(input logic condition, input string message);
    begin
      checks = checks + 1;
      if (!condition) begin
        $display("FAIL %s", message);
        failures = failures + 1;
      end
    end
  endtask

  function automatic integer section_words(input logic internal_select);
    section_words = internal_select ? 1024 : 512;
  endfunction

  function automatic integer active_first(
      input logic internal_select,
      input logic [7:0] selected_model
  );
    active_first = internal_select && selected_model == V2_MODEL_MONO ?
                   512 : 0;
  endfunction

  function automatic integer active_words(
      input logic internal_select,
      input logic [7:0] selected_model,
      input logic [7:0] selected_ramtype
  );
    if (internal_select)
      active_words = selected_model == V2_MODEL_COLOR ? 512 : 32;
    else begin
      case (selected_ramtype)
        V2_RAM_EEPROM_128: active_words = 32;
        V2_RAM_EEPROM_2K:  active_words = 512;
        V2_RAM_EEPROM_1K:  active_words = 256;
        default:            active_words = 0;
      endcase
    end
  endfunction

  function automatic integer physical_address(
      input logic internal_select,
      input logic [7:0] selected_model,
      input integer blob_word,
      input integer half
  );
    if (internal_select && selected_model == V2_MODEL_MONO)
      physical_address = 1024 + (blob_word - 512) * 2 + half;
    else
      physical_address = blob_word * 2 + half;
  endfunction

  function automatic logic [15:0] capture_pattern(
      input integer address
  );
    capture_pattern = (address * 16'h2d6b) ^ 16'ha51c;
  endfunction

  function automatic logic [15:0] restore_pattern(
      input integer address
  );
    restore_pattern = (address * 16'h71c3) ^ 16'h39e7;
  endfunction

  function automatic logic [15:0] untouched_pattern(
      input integer address
  );
    untouched_pattern = (address * 16'h1357) ^ 16'hc24a;
  endfunction

  function automatic logic [31:0] pack_words(
      input logic [15:0] first_word,
      input logic [15:0] second_word
  );
    pack_words = {
        first_word[7:0], first_word[15:8],
        second_word[7:0], second_word[15:8]
    };
  endfunction

  function automatic integer section_base_word(input logic internal_select);
    section_base_word = internal_select ?
        (P_INTERNAL_EEPROM >> 2) : (P_CART_EEPROM >> 2);
  endfunction

  // Edge-request stage model. Responses may be delayed, failed, or withheld.
  // Data remains stable for the cycle in which the DUT observes ready.
  always @(posedge clk) begin
    if (!reset_n) begin
      stage_ready <= 1'b0;
      stage_error <= 1'b0;
      stage_read_data <= 32'd0;
      stage_pending <= 1'b0;
      stage_pending_write <= 1'b0;
      stage_pending_offset <= 32'd0;
      stage_pending_data <= 32'd0;
      stage_pending_error <= 1'b0;
      stage_pending_delay <= 0;
      stage_request_count <= 0;
      stage_completion_count <= 0;
      stage_read_request_count <= 0;
      stage_write_request_count <= 0;
    end else begin
      stage_ready <= 1'b0;
      stage_error <= 1'b0;

      if (stage_pending && !hold_stage_responses) begin
        if (stage_pending_delay == 0) begin
          stage_ready <= 1'b1;
          stage_error <= stage_pending_error;
          stage_read_data <= stage_memory[stage_pending_offset >> 2];
          if (stage_pending_write && !stage_pending_error)
            stage_memory[stage_pending_offset >> 2] <= stage_pending_data;
          stage_pending <= 1'b0;
          stage_completion_count <= stage_completion_count + 1;
        end else begin
          stage_pending_delay <= stage_pending_delay - 1;
        end
      end

      if (stage_req) begin
        check(!stage_pending, "stage request issued while one is outstanding");
        check(stage_offset[1:0] == 0, "stage request is not word aligned");
        if (expected_internal)
          check(stage_offset >= P_INTERNAL_EEPROM &&
                stage_offset < P_INTERNAL_EEPROM + P_INTERNAL_EEPROM_BYTES,
                "internal stage request outside fixed section");
        else
          check(stage_offset >= P_CART_EEPROM &&
                stage_offset < P_CART_EEPROM + P_CART_EEPROM_BYTES,
                "cartridge stage request outside fixed section");
        check(stage_request_count < 2048, "stage request log overflow");
        if (stage_request_count < 2048) begin
          stage_offset_log[stage_request_count] <= stage_offset;
          stage_data_log[stage_request_count] <= stage_write_data;
          stage_write_log[stage_request_count] <= stage_write;
        end
        stage_pending <= 1'b1;
        stage_pending_write <= stage_write;
        stage_pending_offset <= stage_offset;
        stage_pending_data <= stage_write_data;
        stage_pending_error <= stage_request_count == inject_stage_error_at;
        stage_pending_delay <= stage_response_delay;
        stage_request_count <= stage_request_count + 1;
        if (stage_write)
          stage_write_request_count <= stage_write_request_count + 1;
        else
          stage_read_request_count <= stage_read_request_count + 1;
      end
    end
  end

  // Edge-request physical x16 EEPROM model.
  always @(posedge clk) begin
    if (!reset_n) begin
      mem_ready <= 1'b0;
      mem_error <= 1'b0;
      mem_read_data <= 16'd0;
      mem_pending <= 1'b0;
      mem_pending_write <= 1'b0;
      mem_pending_addr <= 11'd0;
      mem_pending_data <= 16'd0;
      mem_pending_error <= 1'b0;
      mem_pending_delay <= 0;
      mem_request_count <= 0;
      mem_read_request_count <= 0;
      mem_write_request_count <= 0;
      mem_write_completions <= 0;
      first_write_stage_completions <= -1;
    end else begin
      mem_ready <= 1'b0;
      mem_error <= 1'b0;

      if (mem_pending && !hold_mem_responses) begin
        if (mem_pending_delay == 0) begin
          mem_ready <= 1'b1;
          mem_error <= mem_pending_error;
          mem_read_data <= backing_memory[mem_pending_addr];
          if (mem_pending_write && !mem_pending_error) begin
            backing_memory[mem_pending_addr] <= mem_pending_data;
            mem_write_completions <= mem_write_completions + 1;
          end
          mem_pending <= 1'b0;
        end else begin
          mem_pending_delay <= mem_pending_delay - 1;
        end
      end

      if (mem_req) begin
        check(!mem_pending, "memory request issued while one is outstanding");
        if (expected_internal && expected_model == V2_MODEL_MONO)
          check(mem_addr >= 1024 && mem_addr <= 1087,
                "mono internal request outside physical bank");
        else
          check(mem_addr <= 1023,
                "Color/cartridge request outside physical RAM");
        check(mem_request_count < 2048, "memory request log overflow");
        if (mem_request_count < 2048) begin
          mem_addr_log[mem_request_count] <= mem_addr;
          mem_data_log[mem_request_count] <= mem_write_data;
          mem_write_log[mem_request_count] <= mem_write;
        end
        mem_pending <= 1'b1;
        mem_pending_write <= mem_write;
        mem_pending_addr <= mem_addr;
        mem_pending_data <= mem_write_data;
        mem_pending_error <= mem_request_count == inject_mem_error_at;
        mem_pending_delay <= mem_response_delay;
        mem_request_count <= mem_request_count + 1;
        if (mem_write) begin
          if (mem_write_request_count == 0)
            first_write_stage_completions <= stage_completion_count;
          mem_write_request_count <= mem_write_request_count + 1;
        end else begin
          mem_read_request_count <= mem_read_request_count + 1;
        end
      end
    end
  end

  always @(posedge clk) begin
    if (!reset_n) begin
      done_pulse_count <= 0;
      failed_pulse_count <= 0;
    end else begin
      if (done)
        done_pulse_count <= done_pulse_count + 1;
      if (failed)
        failed_pulse_count <= failed_pulse_count + 1;
      check(!(stage_req && mem_req), "stage and memory request overlap");
      if (stage_req)
        check(!($past(stage_req)), "stage request is wider than one cycle");
      if (mem_req)
        check(!($past(mem_req)), "memory request is wider than one cycle");
      check(!(done && failed), "done and failed overlap");
      check(!ownership_retained || frozen_ack,
            "retained ownership lost frozen acknowledge");
      if (poisoned)
        check(ownership_retained,
              "poisoned transaction did not retain ownership");
    end
  end

  task automatic reset_dut;
    begin
      @(negedge clk);
      reset_n = 1'b0;
      freeze = 1'b0;
      start = 1'b0;
      abort_request = 1'b0;
      restore = 1'b0;
      select_internal = 1'b0;
      model = V2_MODEL_MONO;
      ramtype = V2_RAM_NONE;
      expected_internal = 1'b0;
      expected_model = V2_MODEL_MONO;
      stage_response_delay = 0;
      mem_response_delay = 0;
      inject_stage_error_at = -1;
      inject_mem_error_at = -1;
      hold_stage_responses = 1'b0;
      hold_mem_responses = 1'b0;
      repeat (3) @(negedge clk);
      reset_n = 1'b1;
      @(negedge clk);
      check(!busy && !done && !failed && !poisoned &&
            !ownership_retained,
            "reset did not return walker to idle");
    end
  endtask

  task automatic launch_operation(
      input logic restore_value,
      input logic internal_value,
      input logic [7:0] model_value,
      input logic [7:0] ramtype_value,
      input logic mutate_inputs,
      input logic pulse_start_while_busy
  );
    integer guard;
    begin
      expected_internal = internal_value;
      expected_model = model_value;
      restore = restore_value;
      select_internal = internal_value;
      model = model_value;
      ramtype = ramtype_value;
      freeze = 1'b1;
      guard = 0;
      while (!frozen_ack && guard < 10) begin
        @(negedge clk);
        guard = guard + 1;
      end
      check(frozen_ack && start_ready, "freeze did not acknowledge start");
      start = 1'b1;
      @(negedge clk);
      start = 1'b0;
      check(busy, "valid operation did not become busy");

      if (mutate_inputs) begin
        select_internal = !internal_value;
        model = model_value == V2_MODEL_COLOR ? V2_MODEL_MONO : V2_MODEL_COLOR;
        ramtype = V2_RAM_NONE;
      end

      if (pulse_start_while_busy) begin
        start = 1'b1;
        @(negedge clk);
        start = 1'b0;
        check(busy, "busy start pulse interrupted operation");
      end
    end
  endtask

  task automatic wait_for_success(input string label);
    integer guard;
    begin
      guard = 0;
      while (!done && !failed && guard < 100000) begin
        @(negedge clk);
        guard = guard + 1;
      end
      check(guard < 100000, $sformatf("%s timed out", label));
      check(done && !failed, $sformatf("%s did not finish successfully", label));
      check(!busy && !poisoned, $sformatf("%s completion state wrong", label));
      check(!ownership_retained,
            $sformatf("%s retained ownership after success", label));
      @(posedge clk);
      @(negedge clk);
      check(done_pulse_count == 1 && failed_pulse_count == 0,
            $sformatf("%s result pulse count wrong", label));
      check(!done && !failed, $sformatf("%s result pulse was not one cycle", label));
    end
  endtask

  task automatic wait_for_failure(
      input logic [3:0] expected_reason,
      input logic expected_poisoned,
      input string label
  );
    integer guard;
    begin
      guard = 0;
      while (!done && !failed && guard < 100000) begin
        @(negedge clk);
        guard = guard + 1;
      end
      check(guard < 100000, $sformatf("%s timed out", label));
      check(failed && !done, $sformatf("%s did not fail", label));
      check(failure_reason == expected_reason,
            $sformatf("%s failure reason wrong", label));
      check(poisoned == expected_poisoned,
            $sformatf("%s poison state wrong", label));
      check(ownership_retained == expected_poisoned,
            $sformatf("%s ownership-retention state wrong", label));
      if (expected_poisoned)
        check(frozen_ack,
              $sformatf("%s released frozen acknowledge while poisoned", label));
      check(!busy, $sformatf("%s remained busy after failure", label));
      @(posedge clk);
      @(negedge clk);
      check(done_pulse_count == 0 && failed_pulse_count == 1,
            $sformatf("%s result pulse count wrong", label));
      check(!done && !failed, $sformatf("%s result pulse was not one cycle", label));
    end
  endtask

  task automatic release_freeze;
    begin
      freeze = 1'b0;
      abort_request = 1'b0;
      @(posedge clk);
      @(negedge clk);
      check(!frozen_ack, "freeze acknowledge did not clear");
    end
  endtask

  task automatic run_capture_case(
      input logic internal_value,
      input logic [7:0] model_value,
      input logic [7:0] ramtype_value,
      input logic mutate_inputs,
      input logic pulse_start_while_busy,
      input string label
  );
    integer i;
    integer j;
    integer base_word;
    integer fixed_words;
    integer first_active;
    integer count_active;
    integer address0;
    integer address1;
    logic [31:0] expected_word;
    begin
      reset_dut();
      fixed_words = section_words(internal_value);
      first_active = active_first(internal_value, model_value);
      count_active = active_words(internal_value, model_value, ramtype_value);
      base_word = section_base_word(internal_value);
      for (i = 0; i < 2048; i = i + 1)
        backing_memory[i] = capture_pattern(i);
      for (i = 0; i < fixed_words; i = i + 1)
        stage_memory[base_word + i] = 32'hdead_beef;

      launch_operation(1'b0, internal_value, model_value, ramtype_value,
                       mutate_inputs, pulse_start_while_busy);
      wait_for_success(label);

      check(stage_write_request_count == fixed_words,
            $sformatf("%s stage write count wrong", label));
      check(stage_read_request_count == 0,
            $sformatf("%s unexpectedly read staging", label));
      check(mem_read_request_count == count_active * 2,
            $sformatf("%s memory read count wrong", label));
      check(mem_write_request_count == 0,
            $sformatf("%s unexpectedly wrote backing memory", label));
      check(stage_completion_count == fixed_words,
            $sformatf("%s completed stage count wrong", label));
      check(!writes_committed,
            $sformatf("%s claimed restore writes", label));
      check(!write_may_have_committed,
            $sformatf("%s claimed a possible restore write", label));

      for (i = 0; i < fixed_words; i = i + 1) begin
        check(stage_write_log[i],
              $sformatf("%s stage direction %0d wrong", label, i));
        check(stage_offset_log[i] ==
              (internal_value ? P_INTERNAL_EEPROM : P_CART_EEPROM) + i * 4,
              $sformatf("%s stage offset %0d wrong", label, i));
        if (i >= first_active && i < first_active + count_active) begin
          address0 = physical_address(internal_value, model_value, i, 0);
          address1 = physical_address(internal_value, model_value, i, 1);
          expected_word = pack_words(capture_pattern(address0),
                                     capture_pattern(address1));
        end else begin
          expected_word = 32'd0;
        end
        check(stage_memory[base_word + i] == expected_word,
              $sformatf("%s payload word %0d wrong", label, i));
        check(stage_data_log[i] == expected_word,
              $sformatf("%s emitted word %0d wrong", label, i));
      end

      for (j = 0; j < count_active; j = j + 1) begin
        i = first_active + j;
        address0 = physical_address(internal_value, model_value, i, 0);
        address1 = physical_address(internal_value, model_value, i, 1);
        check(!mem_write_log[j * 2] && !mem_write_log[j * 2 + 1],
              $sformatf("%s memory direction %0d wrong", label, j));
        check(mem_addr_log[j * 2] == address0 &&
              mem_addr_log[j * 2 + 1] == address1,
              $sformatf("%s memory address pair %0d wrong", label, j));
      end
      release_freeze();
    end
  endtask

  task automatic run_restore_case(
      input logic internal_value,
      input logic [7:0] model_value,
      input logic [7:0] ramtype_value,
      input string label
  );
    integer i;
    integer j;
    integer base_word;
    integer fixed_words;
    integer first_active;
    integer count_active;
    integer address0;
    integer address1;
    logic [15:0] desired0;
    logic [15:0] desired1;
    begin
      reset_dut();
      fixed_words = section_words(internal_value);
      first_active = active_first(internal_value, model_value);
      count_active = active_words(internal_value, model_value, ramtype_value);
      base_word = section_base_word(internal_value);
      for (i = 0; i < 2048; i = i + 1) begin
        backing_memory[i] = untouched_pattern(i);
        expected_backing[i] = untouched_pattern(i);
      end
      for (i = 0; i < fixed_words; i = i + 1)
        stage_memory[base_word + i] = 32'd0;
      for (j = 0; j < count_active; j = j + 1) begin
        i = first_active + j;
        address0 = physical_address(internal_value, model_value, i, 0);
        address1 = physical_address(internal_value, model_value, i, 1);
        desired0 = restore_pattern(address0);
        desired1 = restore_pattern(address1);
        stage_memory[base_word + i] = pack_words(desired0, desired1);
        expected_backing[address0] = desired0;
        expected_backing[address1] = desired1;
      end

      launch_operation(1'b1, internal_value, model_value, ramtype_value,
                       1'b1, 1'b0);
      wait_for_success(label);

      check(stage_read_request_count == fixed_words + count_active,
            $sformatf("%s stage read count wrong", label));
      check(stage_write_request_count == 0,
            $sformatf("%s unexpectedly wrote staging", label));
      check(mem_write_request_count == count_active * 2,
            $sformatf("%s memory write count wrong", label));
      check(mem_read_request_count == 0,
            $sformatf("%s unexpectedly read backing memory", label));
      check(writes_committed == (count_active != 0),
            $sformatf("%s write-history result wrong", label));
      check(write_may_have_committed == (count_active != 0),
            $sformatf("%s possible-write result wrong", label));
      if (count_active != 0)
        check(first_write_stage_completions >= fixed_words,
              $sformatf("%s wrote memory before padding validation", label));

      for (i = 0; i < fixed_words; i = i + 1) begin
        check(!stage_write_log[i],
              $sformatf("%s validation direction %0d wrong", label, i));
        check(stage_offset_log[i] ==
              (internal_value ? P_INTERNAL_EEPROM : P_CART_EEPROM) + i * 4,
              $sformatf("%s validation offset %0d wrong", label, i));
      end
      for (j = 0; j < count_active; j = j + 1) begin
        i = first_active + j;
        check(stage_offset_log[fixed_words + j] ==
              (internal_value ? P_INTERNAL_EEPROM : P_CART_EEPROM) + i * 4,
              $sformatf("%s apply offset %0d wrong", label, j));
        address0 = physical_address(internal_value, model_value, i, 0);
        address1 = physical_address(internal_value, model_value, i, 1);
        check(mem_write_log[j * 2] && mem_write_log[j * 2 + 1],
              $sformatf("%s apply direction %0d wrong", label, j));
        check(mem_addr_log[j * 2] == address0 &&
              mem_addr_log[j * 2 + 1] == address1,
              $sformatf("%s apply address %0d wrong", label, j));
        check(mem_data_log[j * 2] == restore_pattern(address0) &&
              mem_data_log[j * 2 + 1] == restore_pattern(address1),
              $sformatf("%s apply data %0d wrong", label, j));
      end
      for (i = 0; i < 2048; i = i + 1)
        check(backing_memory[i] == expected_backing[i],
              $sformatf("%s backing word %0d changed incorrectly", label, i));
      release_freeze();
    end
  endtask

  task automatic test_first_freeze_edge;
    begin
      reset_dut();
      expected_internal = 1'b0;
      expected_model = V2_MODEL_MONO;
      restore = 1'b0;
      select_internal = 1'b0;
      model = V2_MODEL_MONO;
      ramtype = V2_RAM_NONE;
      freeze = 1'b1;
      start = 1'b1;
      @(negedge clk);
      start = 1'b0;
      check(frozen_ack, "first freeze edge did not acknowledge");
      check(!busy && !done && !failed,
            "start was accepted before prior-cycle freeze acknowledge");
      check(stage_request_count == 0 && mem_request_count == 0,
            "early start issued a request");
      release_freeze();
    end
  endtask

  task automatic test_invalid_config(
      input logic internal_value,
      input logic [7:0] model_value,
      input logic [7:0] ramtype_value,
      input string label
  );
    begin
      reset_dut();
      expected_internal = internal_value;
      expected_model = model_value;
      select_internal = internal_value;
      model = model_value;
      ramtype = ramtype_value;
      restore = 1'b0;
      freeze = 1'b1;
      while (!frozen_ack) @(negedge clk);
      start = 1'b1;
      @(negedge clk);
      start = 1'b0;
      check(failed && !busy, $sformatf("%s was not rejected", label));
      check(failure_reason == EEPROM_WALK_FAILURE_CONFIG,
            $sformatf("%s failure code wrong", label));
      check(stage_request_count == 0 && mem_request_count == 0,
            $sformatf("%s issued a request", label));
      @(posedge clk);
      @(negedge clk);
      check(failed_pulse_count == 1, $sformatf("%s pulse count wrong", label));
      release_freeze();
    end
  endtask

  task automatic test_padding_rejection;
    integer i;
    integer base_word;
    begin
      reset_dut();
      base_word = P_INTERNAL_EEPROM >> 2;
      for (i = 0; i < 1024; i = i + 1)
        stage_memory[base_word + i] = 32'd0;
      // First word after the active Color slice.
      stage_memory[base_word + 512] = 32'h0000_0001;
      launch_operation(1'b1, 1'b1, V2_MODEL_COLOR, V2_RAM_NONE,
                       1'b0, 1'b0);
      wait_for_failure(EEPROM_WALK_FAILURE_PADDING, 1'b0,
                       "nonzero internal padding");
      check(stage_read_request_count == 513,
            "padding failure did not stop at the first bad word");
      check(mem_request_count == 0 && !writes_committed,
            "padding failure mutated backing memory");
      check(!write_may_have_committed,
            "padding failure issued a backing write");
      release_freeze();
    end
  endtask

  task automatic test_backend_errors;
    integer i;
    begin
      reset_dut();
      for (i = 0; i < 512; i = i + 1)
        stage_memory[(P_CART_EEPROM >> 2) + i] = 32'hffff_ffff;
      inject_stage_error_at = 0;
      launch_operation(1'b0, 1'b0, V2_MODEL_MONO, V2_RAM_NONE,
                       1'b0, 1'b0);
      wait_for_failure(EEPROM_WALK_FAILURE_STAGE_BACKEND, 1'b0,
                       "stage backend error");
      check(stage_request_count == 1 && mem_request_count == 0,
            "stage error request counts wrong");
      release_freeze();

      reset_dut();
      inject_mem_error_at = 0;
      launch_operation(1'b0, 1'b0, V2_MODEL_MONO, V2_RAM_EEPROM_128,
                       1'b0, 1'b0);
      wait_for_failure(EEPROM_WALK_FAILURE_MEMORY_BACKEND, 1'b0,
                       "memory backend error");
      check(mem_request_count == 1 && stage_request_count == 0,
            "memory error request counts wrong");
      release_freeze();

      reset_dut();
      for (i = 0; i < 512; i = i + 1)
        stage_memory[(P_CART_EEPROM >> 2) + i] = 32'd0;
      inject_mem_error_at = 0;
      launch_operation(1'b1, 1'b0, V2_MODEL_MONO, V2_RAM_EEPROM_128,
                       1'b0, 1'b0);
      wait_for_failure(EEPROM_WALK_FAILURE_MEMORY_BACKEND, 1'b1,
                       "restore memory backend error");
      check(mem_request_count == 1 && mem_write_request_count == 1,
            "restore memory error request counts wrong");
      check(write_may_have_committed && !writes_committed,
            "failed restore write did not preserve mutation uncertainty");

      reset_dut();
      for (i = 0; i < 512; i = i + 1)
        stage_memory[(P_CART_EEPROM >> 2) + i] = 32'd0;
      // Validation consumes requests 0..511. Request 512 loads the first
      // active word; after its two writes, request 513 must fail closed.
      inject_stage_error_at = 513;
      launch_operation(1'b1, 1'b0, V2_MODEL_MONO, V2_RAM_EEPROM_128,
                       1'b0, 1'b0);
      wait_for_failure(EEPROM_WALK_FAILURE_STAGE_BACKEND, 1'b1,
                       "restore stage error after writes");
      check(mem_write_completions == 2 && writes_committed &&
            write_may_have_committed,
            "post-write stage error lost restore taint");
    end
  endtask

  task automatic test_timeouts;
    integer requests_before_restart;
    integer completions_before_release;
    integer failed_pulses_before_release;
    integer i;
    begin
      reset_dut();
      hold_stage_responses = 1'b1;
      launch_operation(1'b0, 1'b0, V2_MODEL_MONO, V2_RAM_NONE,
                       1'b0, 1'b0);
      wait_for_failure(EEPROM_WALK_FAILURE_STAGE_TIMEOUT, 1'b1,
                       "stage timeout");
      requests_before_restart = stage_request_count;
      check(!start_ready, "poisoned stage timeout allowed restart");
      start = 1'b1;
      @(negedge clk);
      start = 1'b0;
      @(negedge clk);
      check(stage_request_count == requests_before_restart && !busy,
            "poisoned stage timeout restarted");
      check(poisoned && ownership_retained && frozen_ack,
            "stage timeout restart attempt cleared retained ownership");
      completions_before_release = stage_completion_count;
      failed_pulses_before_release = failed_pulse_count;
      hold_stage_responses = 1'b0;
      while (stage_completion_count == completions_before_release)
        @(negedge clk);
      check(stage_completion_count == completions_before_release + 1,
            "late stage completion did not retire exactly once");
      check(poisoned && ownership_retained && frozen_ack && !busy,
            "late stage completion escaped poison ownership");
      check(stage_request_count == requests_before_restart &&
            failed_pulse_count == failed_pulses_before_release &&
            !done && !failed,
            "late stage completion created a new operation result");
      freeze = 1'b0;
      @(posedge clk);
      @(negedge clk);
      check(poisoned && ownership_retained && frozen_ack,
            "stage timeout released ownership before lifecycle reset");

      reset_dut();
      for (i = 0; i < 512; i = i + 1)
        stage_memory[(P_CART_EEPROM >> 2) + i] = 32'd0;
      backing_memory[0] = 16'hbeef;
      hold_mem_responses = 1'b1;
      launch_operation(1'b1, 1'b0, V2_MODEL_MONO, V2_RAM_EEPROM_128,
                       1'b0, 1'b0);
      wait_for_failure(EEPROM_WALK_FAILURE_MEMORY_TIMEOUT, 1'b1,
                       "memory timeout");
      check(!start_ready && mem_request_count == 1,
            "poisoned memory timeout state wrong");
      check(write_may_have_committed && !writes_committed,
            "timed-out restore write did not preserve mutation uncertainty");
      requests_before_restart = mem_request_count;
      start = 1'b1;
      @(negedge clk);
      start = 1'b0;
      @(negedge clk);
      check(mem_request_count == requests_before_restart && !busy &&
            poisoned && ownership_retained && frozen_ack,
            "poisoned memory timeout restarted or released ownership");
      completions_before_release = mem_write_completions;
      failed_pulses_before_release = failed_pulse_count;
      hold_mem_responses = 1'b0;
      while (mem_write_completions == completions_before_release)
        @(negedge clk);
      check(mem_write_completions == completions_before_release + 1 &&
            backing_memory[0] == 16'd0,
            "late timed-out write did not complete as modeled");
      check(mem_request_count == requests_before_restart &&
            failed_pulse_count == failed_pulses_before_release &&
            write_may_have_committed && !writes_committed,
            "late write completion cleared restore uncertainty");
      check(poisoned && ownership_retained && frozen_ack &&
            !done && !failed && !busy,
            "late memory completion escaped poison ownership");
      freeze = 1'b0;
      @(posedge clk);
      @(negedge clk);
      check(poisoned && ownership_retained && frozen_ack,
            "memory timeout released ownership before lifecycle reset");
    end
  endtask

  task automatic test_abort_drains;
    begin
      reset_dut();
      stage_response_delay = 3;
      launch_operation(1'b0, 1'b0, V2_MODEL_MONO, V2_RAM_NONE,
                       1'b0, 1'b0);
      while (!stage_pending) @(negedge clk);
      abort_request = 1'b1;
      wait_for_failure(EEPROM_WALK_FAILURE_ABORT, 1'b0,
                       "stage abort drain");
      check(stage_request_count == 1 && stage_completion_count == 1,
            "stage abort did not drain exactly one request");
      release_freeze();

      reset_dut();
      mem_response_delay = 3;
      launch_operation(1'b0, 1'b0, V2_MODEL_MONO, V2_RAM_EEPROM_128,
                       1'b0, 1'b0);
      while (!mem_pending) @(negedge clk);
      freeze = 1'b0;
      @(posedge clk);
      @(negedge clk);
      check(busy && ownership_retained && frozen_ack,
            "freeze-release dropped acknowledgement before memory drain");
      wait_for_failure(EEPROM_WALK_FAILURE_ABORT, 1'b0,
                       "freeze-release memory drain");
      check(mem_request_count == 1 && !frozen_ack,
            "freeze-release drain state wrong");
    end
  endtask

  task automatic test_abort_after_restore_write;
    integer i;
    integer base_word;
    integer stage_requests_before_restart;
    integer mem_requests_before_restart;
    begin
      reset_dut();
      base_word = P_CART_EEPROM >> 2;
      for (i = 0; i < 512; i = i + 1)
        stage_memory[base_word + i] = pack_words(
            restore_pattern(i * 2), restore_pattern(i * 2 + 1));
      launch_operation(1'b1, 1'b0, V2_MODEL_COLOR, V2_RAM_EEPROM_2K,
                       1'b0, 1'b0);
      while (mem_write_completions < 3) @(negedge clk);
      abort_request = 1'b1;
      wait_for_failure(EEPROM_WALK_FAILURE_ABORT, 1'b1,
                       "restore abort after commit");
      check(writes_committed, "partial restore did not expose committed writes");
      check(write_may_have_committed,
            "partial restore did not expose possible mutation");
      check(mem_write_completions >= 3 && mem_write_completions < 1024,
            "restore abort committed an unexpected number of words");
      check(done_pulse_count == 0,
            "partial restore incorrectly reported completion");
      abort_request = 1'b0;
      stage_requests_before_restart = stage_request_count;
      mem_requests_before_restart = mem_request_count;
      start = 1'b1;
      @(negedge clk);
      start = 1'b0;
      @(negedge clk);
      check(stage_request_count == stage_requests_before_restart &&
            mem_request_count == mem_requests_before_restart && !busy,
            "partial restore poison accepted a restart");
      check(poisoned && ownership_retained && frozen_ack &&
            writes_committed && write_may_have_committed,
            "restart attempt cleared partial-restore poison or taint");
      freeze = 1'b0;
      @(posedge clk);
      @(negedge clk);
      check(poisoned && ownership_retained && frozen_ack,
            "partial restore poison released ownership without reset");
    end
  endtask

  initial begin
    integer i;
    reset_n = 1'b0;
    freeze = 1'b0;
    start = 1'b0;
    abort_request = 1'b0;
    restore = 1'b0;
    select_internal = 1'b0;
    model = V2_MODEL_MONO;
    ramtype = V2_RAM_NONE;
    expected_internal = 1'b0;
    expected_model = V2_MODEL_MONO;
    stage_response_delay = 0;
    mem_response_delay = 0;
    inject_stage_error_at = -1;
    inject_mem_error_at = -1;
    hold_stage_responses = 1'b0;
    hold_mem_responses = 1'b0;
    checks = 0;
    failures = 0;
    for (i = 0; i < 16384; i = i + 1)
      stage_memory[i] = 32'd0;
    for (i = 0; i < 2048; i = i + 1) begin
      backing_memory[i] = 16'd0;
      expected_backing[i] = 16'd0;
    end

    test_first_freeze_edge();

    run_capture_case(1'b1, V2_MODEL_COLOR, V2_RAM_NONE,
                     1'b0, 1'b1, "capture internal Color");
    run_capture_case(1'b1, V2_MODEL_MONO, V2_RAM_NONE,
                     1'b1, 1'b0, "capture internal mono");
    run_capture_case(1'b0, V2_MODEL_MONO, V2_RAM_EEPROM_128,
                     1'b0, 1'b0, "capture cartridge 128-byte");
    run_capture_case(1'b0, V2_MODEL_COLOR, V2_RAM_EEPROM_2K,
                     1'b0, 1'b0, "capture cartridge 2-KiB");
    run_capture_case(1'b0, V2_MODEL_MONO, V2_RAM_EEPROM_1K,
                     1'b0, 1'b0, "capture cartridge 1-KiB");
    run_capture_case(1'b0, V2_MODEL_COLOR, V2_RAM_NONE,
                     1'b0, 1'b0, "capture cartridge absent");
    run_capture_case(1'b0, V2_MODEL_MONO, V2_RAM_SRAM_32K_A,
                     1'b0, 1'b0, "capture cartridge SRAM 32K A identity");
    run_capture_case(1'b0, V2_MODEL_COLOR, V2_RAM_SRAM_32K_B,
                     1'b0, 1'b0, "capture cartridge SRAM 32K B identity");
    run_capture_case(1'b0, V2_MODEL_MONO, V2_RAM_SRAM_128K,
                     1'b0, 1'b0, "capture cartridge SRAM 128K identity");
    run_capture_case(1'b0, V2_MODEL_COLOR, V2_RAM_SRAM_256K,
                     1'b0, 1'b0, "capture cartridge SRAM 256K identity");
    run_capture_case(1'b0, V2_MODEL_MONO, V2_RAM_SRAM_512K,
                     1'b0, 1'b0, "capture cartridge SRAM identity");

    run_restore_case(1'b1, V2_MODEL_COLOR, V2_RAM_NONE,
                     "restore internal Color");
    run_restore_case(1'b1, V2_MODEL_MONO, V2_RAM_NONE,
                     "restore internal mono");
    run_restore_case(1'b0, V2_MODEL_MONO, V2_RAM_EEPROM_128,
                     "restore cartridge 128-byte");
    run_restore_case(1'b0, V2_MODEL_COLOR, V2_RAM_EEPROM_2K,
                     "restore cartridge 2-KiB");
    run_restore_case(1'b0, V2_MODEL_MONO, V2_RAM_EEPROM_1K,
                     "restore cartridge 1-KiB");
    run_restore_case(1'b0, V2_MODEL_COLOR, V2_RAM_NONE,
                     "restore cartridge absent");
    run_restore_case(1'b0, V2_MODEL_MONO, V2_RAM_SRAM_32K_A,
                     "restore cartridge SRAM 32K A identity");
    run_restore_case(1'b0, V2_MODEL_COLOR, V2_RAM_SRAM_32K_B,
                     "restore cartridge SRAM 32K B identity");
    run_restore_case(1'b0, V2_MODEL_MONO, V2_RAM_SRAM_128K,
                     "restore cartridge SRAM 128K identity");
    run_restore_case(1'b0, V2_MODEL_COLOR, V2_RAM_SRAM_256K,
                     "restore cartridge SRAM 256K identity");
    run_restore_case(1'b0, V2_MODEL_MONO, V2_RAM_SRAM_512K,
                     "restore cartridge SRAM identity");

    test_invalid_config(1'b1, 8'h02, V2_RAM_NONE, "invalid model");
    test_invalid_config(1'b1, V2_MODEL_COLOR, 8'hff,
                        "unknown internal RAM type");
    test_invalid_config(1'b0, V2_MODEL_MONO, 8'hff, "unknown RAM type");
    test_padding_rejection();
    test_backend_errors();
    test_abort_drains();
    test_abort_after_restore_write();
    test_timeouts();

    if (failures != 0) begin
      $display("FAIL APF savestate v2 EEPROM walker failures=%0d checks=%0d",
               failures, checks);
      $fatal(1);
    end
    $display("PASS APF savestate v2 EEPROM walker checks=%0d", checks);
    $finish;
  end
endmodule

`default_nettype wire
