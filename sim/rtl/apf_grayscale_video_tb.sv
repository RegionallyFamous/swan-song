`timescale 1ns/1ps

module apf_grayscale_video_tb;
    reg  [23:0] rgb = 24'h000000;
    reg         enabled = 1'b0;
    wire [23:0] rgb_out;

    integer red;
    integer green;
    integer blue;
    integer expected;

    apf_grayscale_video dut (
        .rgb(rgb),
        .enabled(enabled),
        .rgb_out(rgb_out)
    );

    initial begin
        rgb = 24'h12_34_56;
        enabled = 1'b0;
        #1;
        if (rgb_out !== rgb) begin
            $fatal(1, "disabled grayscale path changed RGB: %06x", rgb_out);
        end

        enabled = 1'b1;
        for (red = 0; red <= 255; red = red + 17) begin
            for (green = 0; green <= 255; green = green + 17) begin
                for (blue = 0; blue <= 255; blue = blue + 17) begin
                    rgb = {red[7:0], green[7:0], blue[7:0]};
                    expected = (red + 2 * green + blue) >> 2;
                    #1;
                    if (rgb_out !== {3{expected[7:0]}}) begin
                        $fatal(1,
                               "grayscale mismatch rgb=%06x got=%06x expected=%02x",
                               rgb, rgb_out, expected[7:0]);
                    end
                end
            end
        end

        rgb = 24'h00_00_00;
        #1;
        if (rgb_out !== 24'h00_00_00) begin
            $fatal(1, "black endpoint is not full-range zero");
        end
        rgb = 24'hff_ff_ff;
        #1;
        if (rgb_out !== 24'hff_ff_ff) begin
            $fatal(1, "white endpoint is not full-range 255");
        end

        $display("PASS APF grayscale bypass/1:2:1/full-range 4096-color matrix");
        $finish;
    end
endmodule
