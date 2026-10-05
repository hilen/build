//! What every xcodebuild of an iOS app passes.

/// The linker flags of the app. A setting on the command line replaces the
/// one of the project, so every xcodebuild call passes all of them.
///
/// The 2 weak frameworks carry modern data constants. On iOS 12 and 13 dyld
/// binds a strong data symbol eagerly, so a constant the device lacks, like
/// kCGColorSpaceExtendedDisplayP3 or kSecUseDataProtectionKeychain, kills the
/// app before main. Weak linking makes the missing constant NULL instead.
///
/// The rest is what the engine needs linked and a static library cannot ask
/// for by itself: the video decode of ffmpeg, zlib for it, and MediaPlayer
/// for the lock screen controls. An app with no video links them for nothing,
/// every iOS has them.
pub const LDFLAGS: &str = "-Wl,-weak_framework,CoreGraphics -Wl,-weak_framework,Security \
-framework VideoToolbox -framework CoreMedia -framework CoreVideo -framework MediaPlayer -lz";
