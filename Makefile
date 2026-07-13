.PHONY: sim regression quartus package clean

sim:
	./sim/verilator/run.sh --rom testroms/spritepriority/spritepriority.ws --frames 6 --out build/sim/manual

regression:
	./scripts/regression.sh

quartus:
	./scripts/build_core.sh

package: quartus
	./scripts/package_core.py --rbf src/fpga/output_files/ap_core.rbf --output build/SwanSong.zip

clean:
	rm -rf build
