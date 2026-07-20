# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Regionally Famous contributors

WONDERFUL_TOOLCHAIN ?= /opt/wonderful
TARGET := wswan/medium
include $(WONDERFUL_TOOLCHAIN)/target/$(TARGET)/makedefs.mk

MAKEFLAGS += --no-builtin-rules

NAME := swanframe
BUILDDIR := build
ELF := $(BUILDDIR)/$(NAME).elf
ELF_STAGE1 := $(BUILDDIR)/$(NAME)_stage1.elf
ROM := $(NAME).wsc

SOURCEDIRS := src
ASSETDIRS := assets/runtime
INCLUDEDIRS := src $(BUILDDIR)/assets
LIBS := -lwse -lwsx -lws
LIBDIRS := $(WF_TARGET_DIR)

INCLUDEFLAGS := $(foreach path,$(INCLUDEDIRS),-I$(path)) \
	$(foreach path,$(LIBDIRS),-isystem $(path)/include)
LIBDIRFLAGS := $(foreach path,$(LIBDIRS),-L$(path)/lib)

CFLAGS := -std=gnu11 -Wall -Wextra -Werror \
	$(WF_ARCH_CFLAGS) $(INCLUDEFLAGS) \
	-ffunction-sections -fdata-sections -fno-common -Os -MMD -MP
LDFLAGS := -T$(WF_LDSCRIPT) $(LIBDIRFLAGS) $(WF_ARCH_LDFLAGS) $(LIBS)

SOURCES_C := $(shell find $(SOURCEDIRS) -name "*.c")
SOURCES_WFPROCESS := $(shell find $(ASSETDIRS) -name "*.lua")
OBJS_ASSETS := $(addsuffix .o,$(addprefix $(BUILDDIR)/,$(SOURCES_WFPROCESS)))
OBJS_C := $(patsubst %.c,$(BUILDDIR)/%.o,$(SOURCES_C))
OBJS := $(OBJS_ASSETS) $(OBJS_C)

.PHONY: all clean verify package

all: $(ROM)

$(ROM): $(ELF_STAGE1)
	@echo "  ROM     $@"
	$(BUILDROM) -c wfconfig.toml -o $@ --output-elf $(ELF) $<

$(ELF_STAGE1): $(OBJS)
	@mkdir -p $(@D)
	@echo "  LD      $@"
	$(CC) -r -o $@ $(OBJS) $(WF_CRT0) $(LDFLAGS) -lgcc

$(BUILDDIR)/%.o: %.c | $(OBJS_ASSETS)
	@mkdir -p $(@D)
	@echo "  CC      $<"
	$(CC) $(CFLAGS) -c -o $@ $<

$(BUILDDIR)/%.lua.o: %.lua
	@mkdir -p $(@D)
	@echo "  PROCESS $<"
	$(WF)/bin/wf-process -o $(BUILDDIR)/$*.c -t $(TARGET) \
		--depfile $(BUILDDIR)/$*.lua.d \
		--depfile-target $(BUILDDIR)/$*.lua.o $<
	python3 scripts/normalize_wfprocess_c.py $(BUILDDIR)/$*.c
	$(CC) $(CFLAGS) -c -o $@ $(BUILDDIR)/$*.c

clean:
	$(RM) $(BUILDDIR) $(ROM)

verify: $(ROM)
	python3 scripts/verify_release.py

package: verify
	python3 scripts/package_release.py

-include $(OBJS:.o=.d)
