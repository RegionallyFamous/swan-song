.PHONY: sim regression chip32 quartus package clean

sim:
	./sim/verilator/run.sh --rom testroms/spritepriority/spritepriority.ws --frames 6 --out build/sim/manual

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
