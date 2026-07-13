# syntax=docker/dockerfile:1.7

# Ubuntu 20.04 is a vendor-supported host for Quartus Prime 21.1. The digest is
# the official Ubuntu amd64 image manifest, not the mutable multi-architecture
# tag. This workflow intentionally has no arm64 Quartus stage.
FROM --platform=linux/amd64 ubuntu@sha256:c664f8f86ed5a386b0a340d981b8f81714e21a8b9c73f658c4bea56aa179d54a AS runtime-base

ARG TARGETARCH
ARG TARGETOS
RUN test "${TARGETOS}" = linux && test "${TARGETARCH}" = amd64

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        git \
        libdbus-1-3 \
        libfontconfig1 \
        libglib2.0-0 \
        libgtk-3-0 \
        libncurses5 \
        libsm6 \
        libusb-1.0-0 \
        libxext6 \
        libxft2 \
        libxi6 \
        libxrender1 \
        libxtst6 \
        locales \
        make \
    && sed -i 's/^# *\(en_US.UTF-8 UTF-8\)/\1/' /etc/locale.gen \
    && locale-gen \
    && rm -rf /var/lib/apt/lists/*

ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8


FROM runtime-base AS install

ARG QUARTUS_ACCEPT_EULA
RUN test "${QUARTUS_ACCEPT_EULA}" = 1 || { \
        echo "QUARTUS_ACCEPT_EULA=1 is required for unattended installation" >&2; \
        exit 64; \
    }

WORKDIR /tmp/quartus-components
COPY components/QuartusLiteSetup-21.1.1.850-linux.run ./
COPY components/cyclonev-21.1.1.850.qdz ./

# Recheck the two official per-file digests inside the amd64 build. The outer
# bundle digest is checked on the host before this context is constructed.
RUN printf '%s  %s\n' \
        6b25e8c62535d0ac02a1075b3dd334d2b04394aa QuartusLiteSetup-21.1.1.850-linux.run \
        467123b7bd5e6907beb7d6b1e073ed7bad3e5e94 cyclonev-21.1.1.850.qdz \
        | sha1sum --check --strict - \
    && chmod 0755 QuartusLiteSetup-21.1.1.850-linux.run

# Only the Lite installer and Cyclone V pack are visible to the installer.
# Questa, Help, and all other device packs are deliberately absent. Nios II is
# bundled in this release's base installer but is irrelevant to an APF compile,
# so it is removed before the clean runtime stage is materialized.
RUN ./QuartusLiteSetup-21.1.1.850-linux.run \
        --mode unattended \
        --unattendedmodeui none \
        --accept_eula 1 \
        --installdir /opt/intelFPGA \
    && rm -rf \
        /opt/intelFPGA/nios2eds \
        /opt/intelFPGA/uninstall

COPY toolchain-check.sh /usr/local/bin/toolchain-check
COPY verify-toolchain.tcl /usr/local/share/swan-song/verify-toolchain.tcl
RUN chmod 0755 /usr/local/bin/toolchain-check \
    && /usr/local/bin/toolchain-check


FROM runtime-base AS runtime

COPY --from=install /opt/intelFPGA /opt/intelFPGA
COPY toolchain-check.sh /usr/local/bin/toolchain-check
COPY verify-toolchain.tcl /usr/local/share/swan-song/verify-toolchain.tcl
COPY container-build-core.sh /usr/local/bin/container-build-core

RUN chmod 0755 \
        /usr/local/bin/toolchain-check \
        /usr/local/bin/container-build-core \
    && ln -s /opt/intelFPGA/quartus/bin/quartus_sh /usr/local/bin/quartus_sh \
    && /usr/local/bin/toolchain-check

ENV QUARTUS_ROOTDIR=/opt/intelFPGA/quartus
ENV PATH=/opt/intelFPGA/quartus/bin:/opt/intelFPGA/quartus/linux64/gnu:${PATH}

LABEL org.opencontainers.image.title="Swan Song Quartus build environment" \
      org.opencontainers.image.description="Quartus Prime Lite 21.1.1 Build 850 with Cyclone V only" \
      com.swan-song.quartus.edition="Lite" \
      com.swan-song.quartus.version="21.1.1.850" \
      com.swan-song.quartus.device="5CEBA4F23C8" \
      com.swan-song.quartus.archive-sha1="789c1133d99fde7146fdb99c1f5dcb4d2e5cc0cc"

WORKDIR /work
CMD ["/bin/bash"]
