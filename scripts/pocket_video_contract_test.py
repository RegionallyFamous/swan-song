#!/usr/bin/env python3
"""Source-level contract for Pocket video presentation and temporal filtering."""

from __future__ import annotations

import json
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
CORE = ROOT / "dist/Cores/agg23.WonderSwan"


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def compact(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    source = re.sub(r"//[^\n]*", "", source)
    return re.sub(r"\s+", "", source)


class PocketVideoContractTest(unittest.TestCase):
    def test_exact_scaler_slots(self) -> None:
        video = json.loads((CORE / "video.json").read_text(encoding="utf-8"))["video"]
        modes = video["scaler_modes"]
        self.assertEqual(
            modes,
            [
                {
                    "width": 224,
                    "height": 144,
                    "aspect_w": 14,
                    "aspect_h": 9,
                    "rotation": 0,
                    "mirror": 0,
                },
                {
                    "width": 224,
                    "height": 144,
                    "aspect_w": 14,
                    "aspect_h": 9,
                    "rotation": 270,
                    "mirror": 0,
                },
                {
                    "width": 224,
                    "height": 144,
                    "aspect_w": 14,
                    "aspect_h": 9,
                    "rotation": 180,
                    "mirror": 0,
                },
            ],
        )

    def test_frame_atomic_scaler_integration(self) -> None:
        top = compact(read("src/fpga/core/core_top.v"))
        video_bus = compact(read("src/fpga/core/apf_video_bus.sv"))
        selector = compact(read("src/fpga/core/apf_scaler_selector.sv"))
        settings_cdc = compact(read("src/fpga/core/apf_settings_cdc.sv"))

        self.assertIn("apf_video_busvideo_bus(", top)
        self.assertIn(".clk_sys(clk_sys_36_864)", top)
        self.assertIn(".clk_video(clk_vid_3_75)", top)
        self.assertIn("always@(negedgeclk_sys)begin", video_bus)
        for assignment in (
            "core_rgb_half<=core_rgb;",
            "core_hblank_half<=core_hblank;",
            "core_vblank_half<=core_vblank;",
            "core_hs_half<=core_hs;",
            "core_vs_half<=core_vs;",
        ):
            self.assertIn(assignment, video_bus)
        self.assertIn("wirede=~(core_hblank_half||core_vblank_half);", video_bus)
        self.assertIn(".rgb(core_rgb_half)", video_bus)
        self.assertIn("assignframe_start_video=~vs_prev&&core_vs_half;", video_bus)
        self.assertIn("elseif(de_prev&&~de)begin", video_bus)
        self.assertIn("video_rgb<=scaler_eol_word;", video_bus)
        self.assertIn("if(frame_start_video)begin", video_bus)
        self.assertIn(
            "displaymode_grayscale_applied<=displaymode_grayscale_requested;",
            video_bus,
        )
        self.assertIn("apf_scaler_selectorscaler_selector(", top)
        self.assertIn(".landscape_180_sys(use_flip_horizontal_s)", top)
        self.assertNotIn(".use_flip_horizontal(use_flip_horizontal_s)", top)
        self.assertIn("apf_settings_cdc#(", top)
        self.assertIn("settings_command_cdc(", top)
        self.assertIn(".reset_n(pll_core_ready_74a)", top)
        self.assertIn(".settings_destination(settings_snapshot_s)", top)
        self.assertIn("wire[10:0]settings_snapshot_s;", top)
        self.assertIn(".DEFAULT_SETTINGS(11'h081)", top)
        self.assertIn(
            ".settings_source({configured_system,use_cpu_turbo,"
            "use_triple_buffer,configured_flickerblend,configured_orientation,"
            "use_flip_horizontal,configured_color_profile,use_fastforward_sound})",
            top,
        )
        self.assertIn(
            "assign{configured_system_s,use_cpu_turbo_s,use_triple_buffer_s,"
            "configured_flickerblend_s,configured_orientation_s,"
            "use_flip_horizontal_s,configured_color_profile_s,"
            "use_fastforward_sound_s}=settings_snapshot_s;",
            top,
        )
        self.assertNotIn("settings_s(", top)
        self.assertIn("reg[10:0]settings_hold_source;", settings_cdc)
        self.assertIn("settings_destination<=settings_hold_source;", settings_cdc)

        self.assertIn("if(frame_start_video&&!request_arrived_video)begin", selector)
        self.assertIn("pending_slot_video<=slot_hold_sys;", selector)
        self.assertIn(
            "assigneol_word_video={8'd0,scaler_slot_video,10'd0,3'b000};",
            selector,
        )

    def test_exact_temporal_blend_integration(self) -> None:
        top = compact(read("src/fpga/core/core_top.v"))
        swan = compact(read("src/fpga/core/wonderswan.sv"))
        blend = compact(read("src/fpga/core/apf_temporal_blend.sv"))

        self.assertIn(
            "wirerequested_buffervideo=use_triple_buffer|(configured_flickerblend!=2'd0);",
            swan,
        )
        self.assertIn(
            "wirebuffervideo=use_triple_buffer_applied|(flickerblend_applied!=2'd0);",
            swan,
        )
        self.assertIn("apf_temporal_blendtemporal_blend(", swan)
        self.assertIn(".mode(flickerblend_applied)", swan)
        self.assertNotIn(".mode(configured_flickerblend)", swan)
        self.assertIn(".color_profile(color_profile_applied)", swan)
        self.assertNotIn(".color_profile(configured_color_profile)", swan)
        self.assertIn(
            "color_profile_applied<=configured_color_profile&&isColor;",
            swan,
        )
        self.assertIn(
            "32'h210:beginconfigured_color_profile<=bridge_wr_data[0];end",
            top,
        )
        self.assertIn(
            ".configured_color_profile(configured_color_profile_s)",
            top,
        )
        self.assertIn("elseif(scanout_frame_boundary)begin", swan)
        self.assertIn("{r,g,b}<=temporal_video_rgb;", swan)
        self.assertNotIn("px_addr<=32255", swan)
        self.assertNotIn("px_addr<=px_addr-1'd1", swan)
        for obsolete in ("r2_5", "r3_mul24", "r3_div24"):
            self.assertNotIn(obsolete, swan)

        self.assertIn(
            "red_sum=sample[11:8]*9'd26+sample[7:4]*9'd4+sample[3:0]*9'd2;",
            blend,
        )
        self.assertIn(
            "green_sum=sample[7:4]*9'd24+sample[3:0]*9'd8;",
            blend,
        )
        self.assertIn(
            "blue_sum=sample[11:8]*9'd6+sample[7:4]*9'd4+sample[3:0]*9'd22;",
            blend,
        )
        self.assertIn(
            "transform_color={red_sum[8:1],green_sum[8:1],blue_sum[8:1]};",
            blend,
        )
        self.assertIn(
            "weighted_sum={2'b00,newest}+{2'b00,previous}+10'd1;",
            blend,
        )
        self.assertIn(
            "weighted_sum={1'b0,newest,1'b0}+{2'b00,previous}+{2'b00,oldest};",
            blend,
        )
        self.assertIn("blend_channel=weighted_sum[9:2];", blend)
        self.assertIn("blend_channel=newest;", blend)

    def test_immutable_framebank_ownership_and_history_priming(self) -> None:
        swan = compact(read("src/fpga/core/wonderswan.sv"))
        arbiter = compact(read("src/fpga/core/apf_framebank_arbiter.sv"))
        frame_ram = compact(read("src/fpga/core/apf_framebank_ram.sv"))

        self.assertIn("apf_framebank_arbiterframebank_arbiter(", swan)
        self.assertIn(".reset(reset)", swan)
        self.assertIn(".enable(buffervideo)", swan)
        self.assertIn(
            "wireproducer_frame_done=pixel_we&&pixel_addr==32255;",
            swan,
        )
        self.assertIn(
            "wirescanout_frame_boundary=ce_pix&&scanout_line_end&&y>=257;",
            swan,
        )
        self.assertIn(".producer_frame_done(producer_frame_done)", swan)
        self.assertIn(".consumer_frame_boundary(scanout_frame_boundary)", swan)
        for bank in range(5):
            self.assertIn(f"apf_framebank_ramframebank_ram{bank}(", swan)
            self.assertIn(
                f".write_enable(pixel_we&&framebank_write==3'd{bank})",
                swan,
            )
            self.assertIn(f".read_data(rgb{bank})", swan)
        self.assertIn('(*ramstyle="M10K,no_rw_check",max_depth=2048*)', frame_ram)
        self.assertIn("reg[9:0]pixels_hi[0:FRAME_PIXELS-1];", frame_ram)
        self.assertIn('(*ramstyle="M10K,no_rw_check",max_depth=4096*)', frame_ram)
        self.assertIn("reg[1:0]pixels_lo[0:FRAME_PIXELS-1];", frame_ram)
        self.assertIn("pixels_hi[write_address]<=write_data[11:2];", frame_ram)
        self.assertIn("pixels_lo[write_address]<=write_data[1:0];", frame_ram)
        self.assertIn("assignread_data={read_hi,read_lo};", frame_ram)
        self.assertNotIn("buffercnt_write", swan)
        self.assertNotIn("buffercnt_read", swan)
        self.assertIn(
            "framebank_valid_count>=2?framebank_rgb(framebank_previous):buffered_newest;",
            swan,
        )
        self.assertIn(
            "framebank_valid_count>=3?framebank_rgb(framebank_oldest):buffered_previous;",
            swan,
        )
        self.assertIn(
            "wireuse_buffered_history=buffervideo&&framebank_valid_count!=2'd0;",
            swan,
        )
        self.assertIn(
            "(!buffervideo||allow_direct_while_priming)?rgb0:12'd0;",
            swan,
        )
        self.assertIn("allow_direct_while_priming<=1'b1;", swan)

        self.assertIn("for(candidate=0;candidate<5;candidate=candidate+1)begin", arbiter)
        self.assertIn("if(reset||!enable)begin", arbiter)
        self.assertIn("case({producer_frame_done,consumer_frame_boundary})", arbiter)
        self.assertIn("write_bank_state<=pending_bank;", arbiter)
        self.assertIn("history_newest<=write_bank_state;", arbiter)

    def test_project_regression_and_timing_constraints(self) -> None:
        qsf = read("src/fpga/ap_core.qsf")
        regression = read("scripts/regression.sh")
        sdc = read("src/fpga/core/core_constraints.sdc")
        signal_tap = read("src/fpga/core/stp1.stp")

        for path in (
            "core/apf_settings_cdc.sv",
            "core/apf_framebank_ram.sv",
            "core/apf_framebank_arbiter.sv",
            "core/apf_scaler_selector.sv",
            "core/apf_temporal_blend.sv",
            "core/apf_video_bus.sv",
        ):
            self.assertEqual(
                qsf.count(f"set_global_assignment -name SYSTEMVERILOG_FILE {path}"),
                1,
            )
        for runner in (
            "run_apf_settings_cdc_tb.sh",
            "run_apf_framebank_ram_tb.sh",
            "run_apf_framebank_arbiter_tb.sh",
            "run_apf_scaler_selector_tb.sh",
            "run_apf_temporal_blend_tb.sh",
            "run_apf_video_bus_tb.sh",
        ):
            self.assertEqual(regression.count(f'"$ROOT/sim/rtl/{runner}"'), 1)

        for signal in ("video_de", "video_hs", "video_vs"):
            self.assertIn(
                f"core_top:ic|apf_video_bus:video_bus|{signal}", signal_tap
            )
            self.assertNotIn(f"core_top:ic|{signal}_reg", signal_tap)

        self.assertRegex(
            sdc,
            r"(?s)-group \{[^}]*general\[0\].*general\[1\].*general\[2\].*general\[3\]",
        )
        self.assertIn("ic|scaler_selector|slot_hold_sys[*]", sdc)
        self.assertIn("ic|scaler_selector|pending_slot_video[*]", sdc)
        self.assertIn("ic|settings_command_cdc|settings_hold_source[*]", sdc)
        self.assertIn("ic|settings_command_cdc|settings_destination[*]", sdc)
        self.assertIn(
            'error "scaler slot CDC constraint expected 2 slot_hold_sys registers"',
            sdc,
        )
        self.assertIn(
            'error "scaler slot CDC constraint expected 2 pending_slot_video registers"',
            sdc,
        )


if __name__ == "__main__":
    unittest.main()
