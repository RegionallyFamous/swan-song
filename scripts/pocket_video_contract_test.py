#!/usr/bin/env python3
"""Source-level contract for Pocket video presentation and temporal filtering."""

from __future__ import annotations

import json
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
CORE = ROOT / "dist/Cores/RegionallyFamous.SwanSong"


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def compact(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    source = re.sub(r"//[^\n]*", "", source)
    return re.sub(r"\s+", "", source)


class PocketVideoContractTest(unittest.TestCase):
    def test_direct_to_buffered_priming_contract_is_explicit(self) -> None:
        readme = " ".join(read("README.md").casefold().split())
        controls = " ".join(
            read("docs/wiki/Controls-and-Settings.md").casefold().split()
        )
        delivery = " ".join(read("FRAME_DELIVERY.md").casefold().split())
        protocol = " ".join(read("HARDWARE_QA_PROTOCOL.md").casefold().split())
        qa_schema = read("scripts/pocket_hardware_qa.py")
        swan = compact(read("src/fpga/core/wonderswan.sv"))

        for public_document in (readme, controls, delivery):
            self.assertIn("one producer-frame priming interval", public_document)
            self.assertIn("first completed buffered frame", public_document)
        self.assertIn("one producer-frame priming interval", protocol)
        self.assertIn("beginning with the first completed buffered frame", protocol)
        self.assertIn(
            '"complete_frames_60_9_no_tearing_or_resync_after_priming"',
            qa_schema,
        )
        self.assertNotIn(
            '"complete_frames_60_9_no_tearing_or_resync"', qa_schema
        )

        # The documentation and QA exception are coupled to the intentional
        # live/direct fallback; completed history still takes over atomically.
        self.assertIn("allow_direct_while_priming<=1'b1;", swan)
        self.assertIn(
            "wireuse_buffered_history=buffervideo&&framebank_valid_count!=2'd0;",
            swan,
        )
        self.assertIn(
            "(!buffervideo||allow_direct_while_priming)?rgb0:12'd0;", swan
        )

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
        self.assertIn(".requested_slot_sys(scaler_slot_command_sys)", top)
        self.assertIn(".configured_orientation(configured_orientation_s)", top)
        self.assertIn(".use_flip_horizontal(use_flip_horizontal_s)", top)
        self.assertIn(".scaler_slot_command(scaler_slot_command_sys)", top)
        self.assertNotIn(".landscape_180_sys(", top)
        self.assertIn("apf_settings_cdc#(", top)
        self.assertIn("settings_command_cdc(", top)
        self.assertIn(".reset_n(pll_core_ready_74a)", top)
        self.assertIn(".settings_destination(settings_snapshot_s)", top)
        self.assertIn("wire[12:0]settings_snapshot_s;", top)
        self.assertIn(".DEFAULT_SETTINGS(13'h0201)", top)
        self.assertIn(
            "wire[12:0]settings_source_74a={configured_system,use_cpu_turbo,"
            "use_triple_buffer,configured_flickerblend,configured_orientation,"
            "configured_control_layout,"
            "use_flip_horizontal,configured_color_profile,use_fastforward_sound};",
            top,
        )
        self.assertIn("apf_interact_readbackinteract_settings_readback(", top)
        self.assertEqual(
            top.count(".settings_source(settings_source_74a)"),
            2,
            "the exact requested-settings bundle must feed Interact readback "
            "and the atomic system-domain transfer",
        )
        self.assertIn(
            "assign{configured_system_s,use_cpu_turbo_s,use_triple_buffer_s,"
            "configured_flickerblend_s,configured_orientation_s,"
            "configured_control_layout_s,"
            "use_flip_horizontal_s,configured_color_profile_s,"
            "use_fastforward_sound_s}=settings_snapshot_s;",
            top,
        )
        self.assertNotIn("settings_s(", top)
        self.assertIn("reg[12:0]settings_hold_source;", settings_cdc)
        self.assertIn("settings_destination<=settings_hold_source;", settings_cdc)

        self.assertIn("if(frame_start_video&&!request_arrived_video)begin", selector)
        self.assertIn("inputwire[2:0]requested_slot_sys", selector)
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
        self.assertIn(
            "{r,g,b}<=blank_presentation?24'd0:temporal_video_rgb;",
            swan,
        )
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
        orientation = compact(read("src/fpga/core/apf_frame_orientation.sv"))
        transition = compact(
            read("src/fpga/core/apf_orientation_transition_guard.sv")
        )
        cadence = compact(read("src/fpga/core/apf_scanout_cadence.sv"))
        frame_ram = compact(read("src/fpga/core/apf_framebank_ram.sv"))

        self.assertIn("apf_framebank_arbiterframebank_arbiter(", swan)
        self.assertIn(".reset(reset)", swan)
        self.assertIn(".enable(buffervideo)", swan)
        self.assertIn(
            "wireproducer_frame_done=pixel_we&&pixel_addr==32255;",
            swan,
        )
        self.assertIn(
            "apf_scanout_cadencescanout_cadence(",
            swan,
        )
        self.assertIn("parameter[8:0]STANDARD_LINE_PIXELS=9'd397", cadence)
        self.assertIn("parameter[8:0]SMOOTH_LINE_PIXELS=9'd391", cadence)
        self.assertIn("parameter[8:0]FRAME_LINES=9'd258", cadence)
        self.assertIn("inputwiresmooth_61hz", cadence)
        self.assertIn("localparam[8:0]FRAME_LAST=FRAME_LINES-1'd1;", cadence)
        self.assertIn(
            "wire[8:0]line_last=smooth_61hz?SMOOTH_LINE_PIXELS-1'd1:"
            "STANDARD_LINE_PIXELS-1'd1;",
            cadence,
        )
        self.assertIn("assignline_end=x>=line_last;", cadence)
        self.assertIn(
            "assignframe_boundary=pixel_enable&&line_end&&y>=FRAME_LAST;",
            cadence,
        )
        self.assertIn(
            "wirecomplete_frames_60_9_applied=flickerblend_applied==2'd3;",
            swan,
        )
        self.assertIn(
            ".smooth_61hz(complete_frames_60_9_applied)",
            swan,
        )
        self.assertIn(".producer_frame_done(producer_frame_done)", swan)
        self.assertIn(".consumer_frame_boundary(scanout_frame_boundary)", swan)
        self.assertIn(".defer_candidate(framebank_defer_candidate)", swan)
        self.assertIn(".protect_pending(framebank_protect_pending)", swan)
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

        # The Pocket scaler must rotate the frame selected for scanout, not a
        # newer live console state that may have outrun the buffered pixels.
        self.assertIn("apf_frame_orientationframe_orientation(", swan)
        self.assertIn(".producer_orientation(vertical)", swan)
        self.assertIn(".buffered_frame_visible(use_buffered_history)", swan)
        self.assertIn(".history_newest(framebank_newest)", swan)
        self.assertIn(".candidate_bank(framebank_candidate)", swan)
        self.assertIn(
            ".candidate_uses_live_orientation(candidate_uses_live_orientation)",
            swan,
        )
        self.assertIn("assignis_vertical=presented_vertical;", swan)
        self.assertNotIn("assignis_vertical=vertical;", swan)
        self.assertIn("reg[4:0]bank_orientation=5'b00000;", orientation)
        self.assertIn("if(producer_frame_done)begin", orientation)
        self.assertIn("elseif(consumer_frame_boundary)begin", orientation)
        self.assertIn(
            "assignpresented_orientation=buffered_frame_visible?"
            "stored_orientation(history_newest):direct_orientation;",
            orientation,
        )
        self.assertIn(
            "assigncandidate_orientation=candidate_uses_live_orientation?"
            "producer_orientation:stored_orientation(candidate_bank);",
            orientation,
        )

        # APF applies the last EOL slot command on the next frame. A completed
        # bank needing another slot is therefore held immutable for one frame,
        # while direct scanout fails closed until the applied slot catches up.
        self.assertIn(
            "apf_orientation_transition_guardorientation_transition(", swan
        )
        self.assertIn(".candidate_valid(framebank_candidate_valid)", swan)
        self.assertIn(".command_slot(scaler_slot_command)", swan)
        self.assertIn(
            "assigndefer_candidate=frame_boundary&&buffered_mode&&"
            "!protect_pending&&candidate_valid&&"
            "candidate_target_slot!=command_slot;",
            transition,
        )
        self.assertIn("elseif(protect_pending)begin", arbiter)
        self.assertIn("elseif(defer_candidate&&consumer_frame_boundary)begin", arbiter)
        self.assertIn("pending_valid<=1'b0;", arbiter)
        self.assertIn(
            "assignblank_presentation=frame_blank||"
            "((!buffered_mode||!current_frame_valid)&&"
            "producer_target_slot!=expected_applied_slot);",
            transition,
        )

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
            "core/apf_framebank_ram.sv",
            "core/apf_framebank_arbiter.sv",
            "core/apf_frame_orientation.sv",
            "core/apf_orientation_transition_guard.sv",
            "core/apf_scanout_cadence.sv",
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
            "run_apf_frame_orientation_tb.sh",
            "run_apf_orientation_transition_guard_tb.sh",
            "run_apf_orientation_delivery_e2e_tb.sh",
            "run_apf_scanout_cadence_tb.sh",
            "run_apf_scaler_selector_tb.sh",
            "run_apf_temporal_blend_tb.sh",
            "run_apf_video_bus_tb.sh",
        ):
            self.assertEqual(regression.count(f'"$ROOT/sim/rtl/{runner}"'), 1)

        self.assertEqual(
            qsf.count("set_global_assignment -name ENABLE_SIGNALTAP OFF"), 1
        )
        self.assertNotIn("SIGNALTAP_FILE", qsf)
        self.assertNotIn("USE_SIGNALTAP_FILE", qsf)
        self.assertFalse((ROOT / "src/fpga/core/stp1.stp").exists())

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
