# Reproducible Wonderful-toolchain build for the open glyph fixture, adapted
# from the CC0-1.0 WonderfulToolchain/target-wswan-examples
# templates/wswan/Makefile at commit
# 811b739ab1f0203336a08da8db34365d29869617.

WONDERFUL_TOOLCHAIN ?= /opt/wonderful
TARGET = wswan/medium
include $(WONDERFUL_TOOLCHAIN)/target/$(TARGET)/makedefs.mk

NAME := sjis_glyph_provenance
SOURCEDIRS := .
BUILDDIR := build
ELF := $(BUILDDIR)/$(NAME).elf
ELF_STAGE1 := $(BUILDDIR)/$(NAME)_stage1.elf
ROM := $(NAME).wsc

SOURCES_C := $(shell find -L $(SOURCEDIRS) -maxdepth 1 -name "*.c")
OBJS := $(addsuffix .o,$(addprefix $(BUILDDIR)/,$(SOURCES_C)))
DEPS := $(OBJS:.o=.d)

INCLUDEFLAGS := -I. -isystem $(WF_TARGET_DIR)/include
LIBDIRSFLAGS := -L$(WF_TARGET_DIR)/lib
CFLAGS += -std=gnu11 -Wall -Wextra -Werror $(WF_ARCH_CFLAGS) $(INCLUDEFLAGS) \
	-ffunction-sections -fdata-sections -fno-common -O2
LDFLAGS := -T$(WF_LDSCRIPT) $(LIBDIRSFLAGS) $(WF_ARCH_LDFLAGS) -lws

.PHONY: all clean

all: $(ROM)

$(ROM) $(ELF): $(ELF_STAGE1)
	$(BUILDROM) -o $(ROM) --output-elf $(ELF) $<

$(ELF_STAGE1): $(OBJS)
	$(CC) -r -o $@ $(OBJS) $(WF_CRT0) $(LDFLAGS)

$(BUILDDIR)/%.c.o: %.c
	$(MKDIR) -p $(@D)
	$(CC) $(CFLAGS) -MMD -MP -c -o $@ $<

clean:
	$(RM) $(ROM) $(BUILDDIR)

-include $(DEPS)
