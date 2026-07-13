`timescale 1ns/1ps
`default_nettype none

// Exclusive ownership boundary for SDRAM channel 1.
//
// The cartridge loader owns this channel during startup.  A future APF
// Memories transport may borrow it only after the system domain has stopped
// the console and reported runtime_quiesced.  Every accepted request is
// latched until the SDRAM controller returns ready; this is required because
// the inherited controller queues request edges but does not latch channel-1
// address/data at that edge.
//
// The stage interface is intentionally unused by production integration for
// now.  Keeping this mux in the live ROM path proves the drain/ownership
// boundary without advertising Memories or allowing staging traffic yet.
module apf_sdram_channel1_mux #(
    parameter integer ADDR_WIDTH = 25,
    parameter integer OWNER_GUARD_CYCLES = 6
) (
    input  wire                  clk,
    input  wire                  reset_n,

    input  wire                  stage_acquire,
    input  wire                  runtime_quiesced,
    output wire                  stage_granted,
    output reg                   protocol_error,

    input  wire                  rom_req,
    input  wire                  rom_rnw,
    input  wire [ADDR_WIDTH-1:0] rom_addr,
    input  wire [15:0]           rom_write_data,
    output reg                   rom_ready,
    output reg  [15:0]           rom_read_data,

    input  wire                  stage_req,
    input  wire                  stage_rnw,
    input  wire [ADDR_WIDTH-1:0] stage_addr,
    input  wire [15:0]           stage_write_data,
    output reg                   stage_ready,
    output reg  [15:0]           stage_read_data,

    output reg                   sdram_req,
    output reg                   sdram_rnw,
    output reg  [ADDR_WIDTH-1:0] sdram_addr,
    output reg  [15:0]           sdram_write_data,
    input  wire                  sdram_ready,
    input  wire [15:0]           sdram_read_data
);
  localparam [1:0] OWNER_ROM = 2'd0;
  localparam [1:0] GAP_TO_STAGE = 2'd1;
  localparam [1:0] OWNER_STAGE = 2'd2;
  localparam [1:0] GAP_TO_ROM = 2'd3;

  reg [1:0] owner_state;
  integer guard_count;
  reg pending;
  reg pending_stage;
  reg rom_level_served;
  reg stage_level_served;

  assign stage_granted = owner_state == OWNER_STAGE && runtime_quiesced;

  always @(posedge clk or negedge reset_n) begin
    if (!reset_n) begin
      owner_state <= OWNER_ROM;
      guard_count <= 0;
      pending <= 1'b0;
      pending_stage <= 1'b0;
      rom_level_served <= 1'b0;
      stage_level_served <= 1'b0;
      protocol_error <= 1'b0;
      rom_ready <= 1'b0;
      rom_read_data <= 16'd0;
      stage_ready <= 1'b0;
      stage_read_data <= 16'd0;
      sdram_req <= 1'b0;
      sdram_rnw <= 1'b1;
      sdram_addr <= {ADDR_WIDTH{1'b0}};
      sdram_write_data <= 16'd0;
    end else begin
      sdram_req <= 1'b0;
      rom_ready <= 1'b0;
      stage_ready <= 1'b0;

      if (!rom_req)
        rom_level_served <= 1'b0;
      if (!stage_req)
        stage_level_served <= 1'b0;

      if (pending && sdram_ready) begin
        pending <= 1'b0;
        if (pending_stage) begin
          stage_ready <= 1'b1;
          stage_read_data <= sdram_read_data;
        end else begin
          rom_ready <= 1'b1;
          rom_read_data <= sdram_read_data;
        end
      end

      case (owner_state)
        OWNER_ROM: begin
          // A held ROM request wins an acquisition race.  The loader has no
          // explicit ready-to-request signal, so it must never lose a word
          // when the Memories side asks for ownership.
          if (rom_req && !rom_level_served) begin
            if (pending) begin
              protocol_error <= 1'b1;
            end else begin
              rom_level_served <= 1'b1;
              pending <= 1'b1;
              pending_stage <= 1'b0;
              sdram_req <= 1'b1;
              sdram_rnw <= rom_rnw;
              sdram_addr <= rom_addr;
              sdram_write_data <= rom_write_data;
            end
          end else if (stage_acquire && runtime_quiesced && !pending) begin
            owner_state <= GAP_TO_STAGE;
            guard_count <= 0;
          end

          if (stage_req && !stage_level_served) begin
            stage_level_served <= 1'b1;
            protocol_error <= 1'b1;
          end
        end

        GAP_TO_STAGE: begin
          // Any newly held cartridge work cancels acquisition.  It remains
          // asserted until OWNER_ROM accepts it after this forced-low cycle.
          if (rom_req) begin
            owner_state <= OWNER_ROM;
            guard_count <= 0;
          end else if (!stage_acquire || !runtime_quiesced) begin
            owner_state <= GAP_TO_ROM;
            guard_count <= 0;
          end else if (guard_count + 1 >= OWNER_GUARD_CYCLES) begin
            owner_state <= OWNER_STAGE;
            guard_count <= 0;
          end else begin
            guard_count <= guard_count + 1;
          end

          if (stage_req && !stage_level_served) begin
            stage_level_served <= 1'b1;
            protocol_error <= 1'b1;
          end
        end

        OWNER_STAGE: begin
          // Never switch the physical response route with a request in flight.
          // Losing quiescence is a fail-closed integration error: finish the
          // accepted request, reject new staging work, then guard back to ROM.
          if (!runtime_quiesced)
            protocol_error <= 1'b1;

          if ((!stage_acquire || !runtime_quiesced) && !pending && !stage_req) begin
            owner_state <= GAP_TO_ROM;
            guard_count <= 0;
          end

          if (stage_req && !stage_level_served) begin
            if (!stage_acquire || !runtime_quiesced || pending) begin
              protocol_error <= 1'b1;
            end else begin
              stage_level_served <= 1'b1;
              pending <= 1'b1;
              pending_stage <= 1'b1;
              sdram_req <= 1'b1;
              sdram_rnw <= stage_rnw;
              sdram_addr <= stage_addr;
              sdram_write_data <= stage_write_data;
            end
          end
        end

        GAP_TO_ROM: begin
          if (guard_count + 1 >= OWNER_GUARD_CYCLES) begin
            owner_state <= OWNER_ROM;
            guard_count <= 0;
          end else begin
            guard_count <= guard_count + 1;
          end

          if (stage_req && !stage_level_served) begin
            stage_level_served <= 1'b1;
            protocol_error <= 1'b1;
          end
        end

        default: begin
          owner_state <= OWNER_ROM;
          guard_count <= 0;
          protocol_error <= 1'b1;
        end
      endcase
    end
  end

  initial begin
    if (ADDR_WIDTH < 1)
      $error("ADDR_WIDTH must be positive");
    if (OWNER_GUARD_CYCLES < 1)
      $error("OWNER_GUARD_CYCLES must be positive");
  end
endmodule

`default_nettype wire
