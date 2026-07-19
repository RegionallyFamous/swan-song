# SPDX-License-Identifier: CC0-1.0
#
# Based on the Wonderful Toolchain BootFriend project template.

WONDERFUL_TOOLCHAIN ?= /opt/wonderful
TARGET := wswan/bootfriend
include $(WONDERFUL_TOOLCHAIN)/target/$(TARGET)/makedefs.mk

NAME := yokoi-cart-service
SOURCEDIRS := src
BUILDDIR := build
ELF := $(BUILDDIR)/$(NAME).elf
ELF_STAGE1 := $(BUILDDIR)/$(NAME)_stage1.elf
EXECUTABLE := $(NAME).bfb

VERSION_MAJOR ?= 0
VERSION_MINOR ?= 2
VERSION_PATCH ?= 0
DEFINES := -DYOKOI_VERSION_MAJOR=$(VERSION_MAJOR) \
	-DYOKOI_VERSION_MINOR=$(VERSION_MINOR) -DYOKOI_VERSION_PATCH=$(VERSION_PATCH)
LIBS := -lwse -lws
LIBDIRS := $(WF_ARCH_LIBDIRS)

SOURCES_C := $(shell find -L $(SOURCEDIRS) -name "*.c")
OBJS := $(addsuffix .o,$(addprefix $(BUILDDIR)/,$(SOURCES_C)))
DEPS := $(OBJS:.o=.d)

INCLUDEFLAGS := $(foreach path,$(LIBDIRS),-isystem $(path)/include)
LIBDIRSFLAGS := $(foreach path,$(LIBDIRS),-L$(path)/lib)
CFLAGS += -std=gnu11 -Wall -Wextra -Werror $(DEFINES) $(WF_ARCH_CFLAGS) \
	$(INCLUDEFLAGS) -ffunction-sections -fdata-sections -fno-common -Os -g
LDFLAGS := -T$(WF_LDSCRIPT) $(LIBDIRSFLAGS) -Wl,--gc-sections -fno-common \
	$(WF_ARCH_LDFLAGS) $(LIBS)

.PHONY: all clean test

all: $(EXECUTABLE) compile_commands.json

$(EXECUTABLE): $(ELF_STAGE1)
	@echo "  BFB     $@"
	@$(BUILDBFB) -o $@ --output-elf $(ELF) $(BUILDGATEFLAGS) $<

$(ELF_STAGE1): $(OBJS)
	@echo "  LD      $@"
	@$(CC) -r -o $@ $(OBJS) $(WF_CRT0) $(LDFLAGS)

$(BUILDDIR)/%.c.o: %.c
	@echo "  CC      $<"
	@$(MKDIR) -p $(@D)
	@$(CC) $(CFLAGS) -MMD -MP -MJ $(patsubst %.o,%.cc.json,$@) -c -o $@ $<

compile_commands.json: $(OBJS) | Makefile
	@echo "  MERGE   $@"
	@$(WF)/bin/wf-compile-commands-merge $@ $(patsubst %.o,%.cc.json,$^)

test:
	python3 -m unittest discover -s tests -v

clean:
	@echo "  CLEAN"
	@$(RM) $(EXECUTABLE) $(BUILDDIR) compile_commands.json

-include $(DEPS)
