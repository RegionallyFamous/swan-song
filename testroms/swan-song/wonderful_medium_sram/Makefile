# SPDX-License-Identifier: CC0-1.0
#
# SPDX-FileContributor: Adrian "asie" Siekierka, 2023
# SPDX-FileContributor: Swan Song contributors, 2026

WONDERFUL_TOOLCHAIN ?= /opt/wonderful
TARGET = wswan/medium-sram
include $(WONDERFUL_TOOLCHAIN)/target/$(TARGET)/makedefs.mk

NAME		:= medium_sram_probe

INCLUDEDIRS	:= include
SOURCEDIRS	:= src
ASSETDIRS	:=
CBINDIRS	:=
DEFINES		:=
LIBS		:= -lwse -lwsx -lws
LIBDIRS		:= $(WF_TARGET_DIR)

BUILDDIR	:= build
ELF		:= build/$(NAME).elf
ELF_STAGE1	:= build/$(NAME)_stage1.elf
ROM		:= $(NAME).wsc

ifeq ($(V),1)
_V		:=
else
_V		:= @
endif

ifneq ($(ASSETDIRS),)
    SOURCES_WFPROCESS	:= $(shell find -L $(ASSETDIRS) -name "*.lua")
    INCLUDEDIRS		+= $(addprefix $(BUILDDIR)/,$(ASSETDIRS))
endif
ifneq ($(CBINDIRS),)
    SOURCES_CBIN	:= $(shell find -L $(CBINDIRS) -name "*.bin")
    INCLUDEDIRS		+= $(addprefix $(BUILDDIR)/,$(CBINDIRS))
endif
CRT0_LOCAL	:= src/crt0_color.s
SOURCES_S	:= $(filter-out $(CRT0_LOCAL),$(shell find -L $(SOURCEDIRS) -name "*.s"))
SOURCES_C	:= $(shell find -L $(SOURCEDIRS) -name "*.c")

WARNFLAGS	:= -Wall -Wextra -Werror
INCLUDEFLAGS	:= $(foreach path,$(INCLUDEDIRS),-I$(path)) \
		   $(foreach path,$(LIBDIRS),-isystem $(path)/include)
LIBDIRSFLAGS	:= $(foreach path,$(LIBDIRS),-L$(path)/lib)
ASFLAGS		+= -x assembler-with-cpp $(DEFINES) $(WF_ARCH_CFLAGS) \
		   $(INCLUDEFLAGS) -ffunction-sections -fdata-sections -fno-common
CFLAGS		+= -std=gnu11 $(WARNFLAGS) $(DEFINES) $(WF_ARCH_CFLAGS) \
		   $(INCLUDEFLAGS) -ffunction-sections -fdata-sections -fno-common -O2
LDFLAGS		:= -T$(WF_LDSCRIPT) $(LIBDIRSFLAGS) \
		   $(WF_ARCH_LDFLAGS) $(LIBS)
BUILDROMFLAGS	:=

OBJS_ASSETS	:= $(addsuffix .o,$(addprefix $(BUILDDIR)/,$(SOURCES_CBIN))) \
		   $(addsuffix .o,$(addprefix $(BUILDDIR)/,$(SOURCES_WFPROCESS)))
OBJS_SOURCES	:= $(addsuffix .o,$(addprefix $(BUILDDIR)/,$(SOURCES_S))) \
		   $(addsuffix .o,$(addprefix $(BUILDDIR)/,$(SOURCES_C)))
CRT0_OBJ	:= $(BUILDDIR)/$(CRT0_LOCAL).o
OBJS		:= $(OBJS_ASSETS) $(OBJS_SOURCES)
DEPS		:= $(OBJS:.o=.d) $(CRT0_OBJ:.o=.d)

.PHONY: all clean

all: $(ROM) compile_commands.json

$(ROM) $(ELF): $(ELF_STAGE1)
	@echo "  ROM     $@"
	$(_V)$(BUILDROM) -o $(ROM) --output-elf $(ELF) $(BUILDROMFLAGS) $<

$(ELF_STAGE1): $(OBJS) $(CRT0_OBJ)
	@echo "  LD      $@"
	$(_V)$(CC) -r -o $(ELF_STAGE1) $(CRT0_OBJ) $(OBJS) $(LDFLAGS)

clean:
	@echo "  CLEAN"
	$(_V)$(RM) $(ROM) $(BUILDDIR) compile_commands.json

compile_commands.json: $(OBJS) | Makefile
	@echo "  MERGE   compile_commands.json"
	$(_V)$(WF)/bin/wf-compile-commands-merge $@ $(patsubst %.o,%.cc.json,$^)

$(BUILDDIR)/%.s.o : %.s | $(OBJS_ASSETS)
	@echo "  AS      $<"
	@$(MKDIR) -p $(@D)
	$(_V)$(CC) $(ASFLAGS) -MMD -MP -MJ $(patsubst %.o,%.cc.json,$@) -c -o $@ $<

$(BUILDDIR)/%.c.o : %.c | $(OBJS_ASSETS)
	@echo "  CC      $<"
	@$(MKDIR) -p $(@D)
	$(_V)$(CC) $(CFLAGS) -MMD -MP -MJ $(patsubst %.o,%.cc.json,$@) -c -o $@ $<

$(BUILDDIR)/%.bin.o $(BUILDDIR)/%_bin.h : %.bin
	@echo "  BIN2C   $<"
	@$(MKDIR) -p $(@D)
	$(_V)$(WF)/bin/wf-bin2c -a 2 --address-space __far $(@D) $<
	$(_V)$(CC) $(CFLAGS) -MMD -MP -c -o $(BUILDDIR)/$*.bin.o $(BUILDDIR)/$*_bin.c

$(BUILDDIR)/%.lua.o : %.lua
	@echo "  PROCESS $<"
	@$(MKDIR) -p $(@D)
	$(_V)$(WF)/bin/wf-process -o $(BUILDDIR)/$*.c -t $(TARGET) --depfile $(BUILDDIR)/$*.lua.d --depfile-target $(BUILDDIR)/$*.lua.o $<
	$(_V)$(CC) $(CFLAGS) -MMD -MP -c -o $@ $(BUILDDIR)/$*.c

-include $(DEPS)
