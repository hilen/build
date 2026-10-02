# The box that cross builds the static ffmpeg for x86_64 Windows, see
# ffmpeg-win.rs. clang in cl mode, the MSVC headers and libraries from xwin,
# nasm for the x86 assembly, meson and ninja for dav1d. It runs on any host
# cpu, clang builds for x86_64 either way.
FROM debian:trixie

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    clang lld llvm nasm meson ninja-build pkg-config git make curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# The unpack of the SDK takes about 40 minutes, so it is its own layer.
ARG XWIN=0.10.0
RUN curl -sSfL https://github.com/Jake-Shadle/xwin/releases/download/$XWIN/xwin-$XWIN-$(uname -m)-unknown-linux-musl.tar.gz \
    | tar xz -C /tmp \
 && /tmp/xwin-*/xwin --accept-license --arch x86_64 --cache-dir /tmp/xwin-cache splat --output /opt/xwin \
 && rm -rf /tmp/xwin-*

# lld-link reads the library folders from here.
ENV LIB="/opt/xwin/crt/lib/x86_64;/opt/xwin/sdk/lib/um/x86_64;/opt/xwin/sdk/lib/ucrt/x86_64"

COPY clang-cl /usr/local/bin/clang-cl
COPY cross.txt /opt/cross.txt
COPY build.sh /opt/build.sh
RUN chmod +x /usr/local/bin/clang-cl /opt/build.sh
