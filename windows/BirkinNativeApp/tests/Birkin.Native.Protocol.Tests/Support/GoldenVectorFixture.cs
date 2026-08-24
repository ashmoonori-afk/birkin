using System.Text;
using System.Text.Json;
using Birkin.Native.Protocol.Framing;

namespace Birkin.Native.Protocol.Tests.Support;

internal sealed record GoldenVector(
    string Name,
    string Kind,
    byte[] Frame,
    int FrameByteCount,
    NativeJsonValue ExpectedEnvelope);

internal static class GoldenVectorFixture
{
    public static IReadOnlyList<GoldenVector> Load()
    {
        var path = Path.Combine(AppContext.BaseDirectory, "GoldenVectors", "native-protocol-vectors.json");
        using var document = JsonDocument.Parse(File.ReadAllBytes(path));
        var vectors = new List<GoldenVector>();
        foreach (var vector in document.RootElement.GetProperty("vectors").EnumerateArray())
        {
            var envelopeJson = Encoding.UTF8.GetBytes(vector.GetProperty("envelope").GetRawText());
            vectors.Add(new GoldenVector(
                vector.GetProperty("name").GetString()!,
                vector.GetProperty("kind").GetString()!,
                Convert.FromBase64String(vector.GetProperty("frame_base64").GetString()!),
                vector.GetProperty("frame_byte_count").GetInt32(),
                NativeJsonParser.Parse(envelopeJson)));
        }

        return vectors;
    }
}
