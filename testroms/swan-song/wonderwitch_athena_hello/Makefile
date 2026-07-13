# SPDX-License-Identifier: CC0-1.0
#
# SPDX-FileContributor: Adrian "asie" Siekierka, 2023

WONDERFUL_TOOLCHAIN ?= /opt/wonderful
TARGET = wwitch
include $(WONDERFUL_TOOLCHAIN)/target/$(TARGET)/makedefs.mk

NAME := athena_hello
INFO := Swan Song Athena hello
WF_CRT0 := $(WF_CRT0_JPN2)

SOURCEDIRS := src
INCLUDEDIRS := include
LIBS := -lwsx -lww
LIBDIRS := $(WF_ARCH_LIBDIRS)

BUILDDIR := ../../../build/wonderwitch-athena/fixture
ELF := $(BUILDDIR)/$(NAME).elf
MAP := $(BUILDDIR)/$(NAME).map
EXECUTABLE := $(BUILDDIR)/$(NAME).fx
ROM := $(BUILDDIR)/$(NAME).ws
PYTHON ?= python3

WARNFLAGS := -Wall
INCLUDEFLAGS := $(foreach path,$(INCLUDEDIRS),-I$(path)) \
	$(foreach path,$(LIBDIRS),-isystem $(path)/include)
LIBDIRSFLAGS := $(foreach path,$(LIBDIRS),-L$(path)/lib)
ASFLAGS += -x assembler-with-cpp $(WF_ARCH_CFLAGS) $(INCLUDEFLAGS) \
	-fno-function-sections -fdata-sections
CFLAGS += -std=gnu11 $(WARNFLAGS) $(WF_ARCH_CFLAGS) $(INCLUDEFLAGS) \
	-fno-function-sections -fdata-sections -Os
LDFLAGS := -T$(WF_LDSCRIPT) $(LIBDIRSFLAGS) -Wl,-Map,$(MAP) \
	-Wl,--gc-sections $(WF_ARCH_LDFLAGS) $(LIBS)

SOURCES_S := $(shell find -L $(SOURCEDIRS) -name "*.s")
SOURCES_C := $(shell find -L $(SOURCEDIRS) -name "*.c")
OBJS := $(addsuffix .o,$(addprefix $(BUILDDIR)/,$(SOURCES_S))) \
	$(addsuffix .o,$(addprefix $(BUILDDIR)/,$(SOURCES_C)))
DEPS := $(OBJS:.o=.d)

.PHONY: all clean

all: $(EXECUTABLE) $(ROM)

$(ROM): $(EXECUTABLE)
	@echo "  MKROM   $@"
	@$(MKROM) -v -o $@ $< --small

$(EXECUTABLE): $(ELF) normalize_fent.py
	@echo "  MKFENT  $@"
	@$(MKFENT) -v -o $@ -s $< --info "$(INFO)"
	@$(PYTHON) normalize_fent.py $@

$(ELF): $(OBJS)
	@echo "  LD      $@"
	@$(CC) -o $@ $(OBJS) $(WF_CRT0) $(LDFLAGS)

$(BUILDDIR)/%.s.o: %.s
	@echo "  AS      $<"
	@$(MKDIR) -p $(@D)
	@$(CC) $(ASFLAGS) -MMD -MP -c -o $@ $<

$(BUILDDIR)/%.c.o: %.c
	@echo "  CC      $<"
	@$(MKDIR) -p $(@D)
	@$(CC) $(CFLAGS) -MMD -MP -c -o $@ $<

clean:
	@echo "  CLEAN"
	@$(RM) $(BUILDDIR)

-include $(DEPS)
