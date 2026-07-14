`timescale 1ns/1ps

module apf_control_layout_tb;
    reg [1:0] configured_layout;
    reg native_vertical;
    reg button_a;
    reg button_b;
    reg button_x;
    reg button_y;
    reg button_trig_l;
    reg button_trig_r;
    wire key_y1;
    wire key_y2;
    wire key_y3;
    wire key_y4;
    wire key_a;
    wire key_b;

    integer layout_index;
    integer native_index;
    integer buttons_index;
    reg expected_vertical;

    apf_control_layout dut (
        .configured_layout(configured_layout),
        .native_vertical(native_vertical),
        .button_a(button_a),
        .button_b(button_b),
        .button_x(button_x),
        .button_y(button_y),
        .button_trig_l(button_trig_l),
        .button_trig_r(button_trig_r),
        .key_y1(key_y1),
        .key_y2(key_y2),
        .key_y3(key_y3),
        .key_y4(key_y4),
        .key_a(key_a),
        .key_b(key_b)
    );

    initial begin
        // Exhaust all 4 encodings, both native orientations, and all 64 input
        // combinations. Encoding 3 is intentionally identical to Auto.
        for (layout_index = 0; layout_index < 4; layout_index = layout_index + 1) begin
            for (native_index = 0; native_index < 2; native_index = native_index + 1) begin
                for (buttons_index = 0; buttons_index < 64; buttons_index = buttons_index + 1) begin
                    configured_layout = layout_index[1:0];
                    native_vertical = native_index[0];
                    {button_trig_r, button_trig_l, button_y,
                     button_x, button_b, button_a} = buttons_index[5:0];
                    #1;

                    expected_vertical = configured_layout == 2'd1 ? 1'b0 :
                                        configured_layout == 2'd2 ? 1'b1 :
                                        native_vertical;
                    if (key_y1 !== (expected_vertical ? button_x : button_trig_l) ||
                        key_y2 !== (expected_vertical ? button_a : button_trig_r) ||
                        key_y3 !== (expected_vertical ? button_b : button_x) ||
                        key_y4 !== button_y ||
                        key_a !== (expected_vertical ? button_trig_l : button_a) ||
                        key_b !== (expected_vertical ? button_trig_r : button_b)) begin
                        $fatal(
                            1,
                            "mapping mismatch layout=%0d native=%0d buttons=%02x",
                            layout_index,
                            native_index,
                            buttons_index
                        );
                    end
                end
            end
        end

        $display("PASS APF control layout vectors=512 invalid=auto display-independent");
        $finish;
    end
endmodule
