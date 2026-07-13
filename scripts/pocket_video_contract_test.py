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
        selector = compact(read("src/fpga/core/apf_scaler_selector.sv"))
        settings_cdc = compact(read("src/fpga/core/apf_settings_cdc.sv"))

        self.assertIn("always@(negedgeclk_sys_36_864)begin", top)
        for assignment in (
            "vid_rgb_sys_half<=vid_rgb_core;",
            "h_blank_sys_half<=h_blank;",
            "v_blank_sys_half<=v_blank;",
            "video_hs_sys_half<=video_hs_core;",
            "video_vs_sys_half<=video_vs_core;",
        ):
            self.assertIn(assignment, top)
        self.assertIn("wirede=~(h_blank_sys_half||v_blank_sys_half);", top)
        self.assertIn(".rgb(vid_rgb_sys_half)", top)
        self.assertIn("wireframe_start_video=~vs_prev&&video_vs_sys_half;", top)
        self.assertIn("apf_scaler_selectorscaler_selector(", top)
        self.assertIn(".landscape_180_sys(use_flip_horizontal_s)", top)
        self.assertNotIn(".use_flip_horizontal(use_flip_horizontal_s)", top)
        self.assertIn("apf_settings_cdc#(", top)
        self.assertIn("settings_command_cdc(", top)
        self.assertIn(".reset_n(pll_core_ready_74a)", top)
        self.assertIn(".settings_destination(settings_snapshot_s)", top)
        self.assertNotIn("settings_s(", top)
        self.assertIn("reg[9:0]settings_hold_source;", settings_cdc)
        self.assertIn("settings_destination<=settings_hold_source;", settings_cdc)

        self.assertIn("if(frame_start_video&&!request_arrived_video)begin", selector)
        self.assertIn("pending_slot_video<=slot_hold_sys;", selector)
        self.assertIn(
            "assigneol_word_video={8'd0,scaler_slot_video,10'd0,3'b000};",
            selector,
        )

    def test_exact_temporal_blend_integration(self) -> None:
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
        self.assertIn("elseif(scanout_frame_boundary)begin", swan)
        self.assertIn("{r,g,b}<=temporal_video_rgb;", swan)
        self.assertNotIn("px_addr<=32255", swan)
        self.assertNotIn("px_addr<=px_addr-1'd1", swan)
        for obsolete in ("r2_5", "r3_mul24", "r3_div24"):
            self.assertNotIn(obsolete, swan)

        self.assertIn("expanded_sum=sample_sum*10'd17;", blend)
        self.assertIn("(expanded_sum+10'd1)>>1", blend)
        self.assertIn("(expanded_sum+10'd1)/10'd3", blend)
        self.assertIn("blend_channel={newest,newest};", blend)

    def test_immutable_framebank_ownership_and_history_priming(self) -> None:
        swan = compact(read("src/fpga/core/wonderswan.sv"))
        arbiter = compact(read("src/fpga/core/apf_framebank_arbiter.sv"))

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
        for bank in range(1, 6):
            self.assertIn(f"reg[11:0]vram{bank}[32256];", swan)
            self.assertIn(
                f"if(framebank_write=={bank - 1})vram{bank}[pixel_addr]<=pixel_data;",
                swan,
            )
            self.assertIn(f"rgb{bank - 1}<=vram{bank}[px_addr];", swan)
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

        for path in (
            "core/apf_settings_cdc.sv",
            "core/apf_framebank_arbiter.sv",
            "core/apf_scaler_selector.sv",
            "core/apf_temporal_blend.sv",
        ):
            self.assertEqual(
                qsf.count(f"set_global_assignment -name SYSTEMVERILOG_FILE {path}"),
                1,
            )
        for runner in (
            "run_apf_settings_cdc_tb.sh",
            "run_apf_framebank_arbiter_tb.sh",
            "run_apf_scaler_selector_tb.sh",
            "run_apf_temporal_blend_tb.sh",
        ):
            self.assertEqual(regression.count(f'"$ROOT/sim/rtl/{runner}"'), 1)

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
