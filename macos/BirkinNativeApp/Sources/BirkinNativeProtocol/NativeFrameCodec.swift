import Foundation

/// The length-prefixed frame layer of the native protocol.
///
/// Wave 4.1 T03 needs only enough framing to reach the envelope: the body is
/// whatever follows the four-byte prefix. The declared-length bound and the
/// truncation and trailing-data refusals arrive with T05.
enum NativeFrameCodec {
    /// The JSON body carried by one frame.
    static func body(of frame: Data) -> Data {
        frame.dropFirst(4)
    }
}
