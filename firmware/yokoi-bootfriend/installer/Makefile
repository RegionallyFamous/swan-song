# SPDX-License-Identifier: CC0-1.0

WONDERFUL_TOOLCHAIN ?= /opt/wonderful
TARGET := wswan/small
include $(WONDERFUL_TOOLCHAIN)/target/$(TARGET)/makedefs.mk

NAME := yokoi_boot_installer
SOURCEDIRS := src
BUILDDIR := build
ELF := $(BUILDDIR)/$(NAME).elf
ELF_STAGE1 := $(BUILDDIR)/$(NAME)_stage1.elf
ROM := $(NAME).wsc

LIBS := -lwse -lwsx -lws
LIBDIRS := $(WF_ARCH_LIBDIRS)
SOURCES_C := $(shell find -L $(SOURCEDIRS) -name "*.c")
OBJS_SOURCES := $(addsuffix .o,$(addprefix $(BUILDDIR)/,$(SOURCES_C)))
OBJS_ASSETS := $(BUILDDIR)/yokoi_boot.bin.o
OBJS := $(OBJS_ASSETS) $(OBJS_SOURCES)
DEPS := $(OBJS:.o=.d)

INCLUDEFLAGS := -I$(BUILDDIR) $(foreach path,$(LIBDIRS),-isystem $(path)/include)
LIBDIRSFLAGS := $(foreach path,$(LIBDIRS),-L$(path)/lib)
CFLAGS += -std=gnu11 -Wall -Wextra -Werror $(WF_ARCH_CFLAGS) $(INCLUDEFLAGS) \
	-ffunction-sections -fdata-sections -fno-common -Os
LDFLAGS := -T$(WF_LDSCRIPT) $(LIBDIRSFLAGS) -Wl,--gc-sections -fno-common \
	$(WF_ARCH_LDFLAGS) $(LIBS)

.PHONY: all clean

all: $(ROM) compile_commands.json

$(ROM) $(ELF): $(ELF_STAGE1)
	@echo "  ROM     $@"
	@$(BUILDROM) -o $(ROM) --output-elf $(ELF) $<

$(ELF_STAGE1): $(OBJS)
	@echo "  LD      $@"
	@$(CC) -r -o $@ $(OBJS) $(WF_CRT0) $(LDFLAGS)

$(BUILDDIR)/src/%.c.o: src/%.c $(BUILDDIR)/yokoi_boot_bin.h
	@echo "  CC      $<"
	@$(MKDIR) -p $(@D)
	@$(CC) $(CFLAGS) -MMD -MP -MJ $(patsubst %.o,%.cc.json,$@) -c -o $@ $<

$(BUILDDIR)/yokoi_boot.bin.o $(BUILDDIR)/yokoi_boot_bin.h &: ../yokoi_boot.bin
	@echo "  BIN2C   $<"
	@$(MKDIR) -p $(BUILDDIR)
	@$(WF)/bin/wf-bin2c -a 2 --address-space __far $(BUILDDIR) $<
	@$(CC) $(CFLAGS) -MMD -MP -c -o $(BUILDDIR)/yokoi_boot.bin.o \
		$(BUILDDIR)/yokoi_boot_bin.c

compile_commands.json: $(OBJS) | Makefile
	@echo "  MERGE   $@"
	@$(WF)/bin/wf-compile-commands-merge $@ $(patsubst %.o,%.cc.json,$^)

clean:
	@echo "  CLEAN"
	@$(RM) $(ROM) $(BUILDDIR) compile_commands.json

-include $(DEPS)
