# SPDX-License-Identifier: GPL-3.0-or-later
# Yokoi Boot - WonderSwan Color/SwanCrystal splash loader

BUILDDIR := build
NASM ?= nasm
PYTHON3 ?= python3
SOURCE_LOGO ?= assets/yokoi-logo.png

.PHONY: all clean test release test-all

all: yokoi_boot.bin yokoi_boot_template.bin $(BUILDDIR)/yokoi-logo-preview.png

$(BUILDDIR)/yokoi_logo.2bpp $(BUILDDIR)/yokoi-logo-preview.png &: \
		$(SOURCE_LOGO) tools/png2ws_splash.py
	@mkdir -p $(BUILDDIR)
	$(PYTHON3) tools/png2ws_splash.py \
		--input $(SOURCE_LOGO) \
		--output $(BUILDDIR)/yokoi_logo.2bpp \
		--preview $(BUILDDIR)/yokoi-logo-preview.png

yokoi_boot.bin: yokoi_boot.asm hardware.inc $(BUILDDIR)/yokoi_logo.2bpp
	$(NASM) -DROM -o $@ yokoi_boot.asm
	@test "$$(wc -c < $@ | tr -d ' ')" = 1920

yokoi_boot_template.bin: yokoi_boot.asm hardware.inc
	$(NASM) -o $@ yokoi_boot.asm

test: all
	$(PYTHON3) -m unittest discover -s tests -v

release: all
	$(MAKE) -C installer
	$(MAKE) -C ../yokoi-cart-service

test-all: test
	$(MAKE) -C ../yokoi-cart-service test

clean:
	rm -rf $(BUILDDIR) yokoi_boot.bin yokoi_boot_template.bin
