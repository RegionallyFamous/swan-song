.PHONY: sim regression chip32 quartus package clean

sim:
	python3 ./sim/verilator/generate_window_boundary_probe.py --output-dir build/sim/manual/roms
	./sim/verilator/run.sh --rom build/sim/manual/roms/wsc_window_inside_probe.wsc --frames 2 --max-cycles 1500000 --out build/sim/manual/frames
	python3 ./sim/verilator/verify_window_boundary_probe.py --variant inside --rom build/sim/manual/roms/wsc_window_inside_probe.wsc --frame build/sim/manual/frames/frame-1.rgb

regression:
	./scripts/regression.sh

chip32:
	python3 ./scripts/build_chip32.py --output build/chip32.bin

quartus:
	./scripts/build_core.sh

package: quartus
	./scripts/package_core.py --rbf src/fpga/output_files/ap_core.rbf --output build/SwanSong.zip

clean:
	rm -rf build
