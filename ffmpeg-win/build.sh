#!/bin/bash
# Runs inside the box of the Dockerfile next to it. Builds zlib, dav1d and
# ffmpeg as static libraries for x86_64-pc-windows-msvc with the static C
# runtime, and packs them into /out.
#
#   build.sh <ffmpeg version> <dav1d version> <zlib version>
set -euo pipefail

FFMPEG=$1
DAV1D=$2
ZLIB=$3
P=/opt/dist
NAME=ffmpeg-$FFMPEG-x86_64-pc-windows-msvc
mkdir -p $P/lib $P/include /src

clone() {
    [ -d /src/$1 ] || git clone -q --depth=1 -b $2 $3 /src/$1
}
clone zlib v$ZLIB https://github.com/madler/zlib
clone dav1d $DAV1D https://code.videolan.org/videolan/dav1d.git
clone ffmpeg release/$FFMPEG https://github.com/FFmpeg/FFmpeg

# zlib has no build for clang-cl on Linux, its 15 files are compiled by
# hand. ffmpeg looks for the name zlib.lib.
mkdir -p /opt/zlib-build && cd /opt/zlib-build
for f in adler32 compress crc32 deflate gzclose gzlib gzread gzwrite infback inffast inflate inftrees trees uncompr zutil; do
    clang-cl -nologo -O2 -MT -w -c /src/zlib/$f.c -Fo$f.obj
done
llvm-lib -nologo -out:$P/lib/zlib.lib *.obj
cp /src/zlib/zlib.h /src/zlib/zconf.h $P/include/
# ffmpeg defines HAVE_UNISTD_H as 0, and zconf.h only asks if it is defined.
sed -i 's|^#ifdef HAVE_UNISTD_H.*|#if 0 /* no unistd.h on Windows */|' $P/include/zconf.h

rm -rf /opt/dav1d-build
meson setup /opt/dav1d-build /src/dav1d --cross-file /opt/cross.txt --prefix=$P --libdir=lib \
    --default-library=static --buildtype=release -Db_vscrt=mt -Denable_tools=false -Denable_tests=false
ninja -C /opt/dav1d-build install
# meson names it like on unix, ffmpeg and rustc look for dav1d.lib.
mv $P/lib/libdav1d.a $P/lib/dav1d.lib

# llvm-ar, not llvm-lib: configure passes the flags of GNU ar. Autodetect is
# off, so the TLS of Windows, Schannel, is named, without it the archive has
# no https protocol. The filter list is the one of ffmpeg.rs.
mkdir -p /opt/ffmpeg-build && cd /opt/ffmpeg-build
PKG_CONFIG_PATH=$P/lib/pkgconfig /src/ffmpeg/configure --prefix=$P \
    --target-os=win64 --arch=x86_64 --enable-cross-compile --toolchain=msvc \
    --cc=clang-cl --cxx=clang-cl --ld=lld-link --ar=llvm-ar --ranlib=llvm-ranlib --nm=llvm-nm \
    --x86asmexe=nasm --host-cc=clang --host-ld=clang --host-os=linux \
    --pkg-config=pkg-config --pkg-config-flags=--static \
    --extra-cflags="-MT -I$P/include" --extra-ldflags="-libpath:$P/lib" \
    --enable-static --disable-shared --disable-autodetect --disable-programs --disable-doc --disable-debug \
    --enable-avcodec --enable-avformat --enable-swresample --enable-swscale --disable-avdevice \
    --enable-avfilter --disable-filters --enable-filter=atempo --enable-filter=abuffer --enable-filter=abuffersink \
    --enable-zlib --enable-libdav1d --enable-d3d11va --enable-schannel \
    --disable-gpl --disable-version3 --disable-nonfree
make -j"$(nproc)" install

# What has to be linked besides the ffmpeg libraries, the 2 libraries of the
# archive and the Windows ones that configure lists as EXTRALIBS.
printf 'static=dav1d\nstatic=zlib\ndylib=secur32\ndylib=ncrypt\ndylib=crypt32\ndylib=ws2_32\ndylib=ole32\ndylib=user32\ndylib=bcrypt\n' > $P/lib/link.txt

tar -C $P --exclude=lib/pkgconfig -czf /out/$NAME.tar.gz include lib
cd /out && sha256sum $NAME.tar.gz > $NAME.sha256
cat $NAME.sha256
