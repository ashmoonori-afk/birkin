using Birkin.Native.Protocol.Framing;
using Birkin.Native.Protocol.Projection;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests.Presentation;

[TestClass]
public sealed class OfficeSupportPresentationTests
{
    [TestMethod]
    public void FromSurface_DistinguishesBackendCapabilityFromAgentWiring()
    {
        var create = new NativeJsonObject([
            new("state", new NativeJsonString("native")),
            new("availability", new NativeJsonString("conditional")),
            new("install_probe", new NativeJsonString("import package")),
            new("public_entrypoint", NativeJsonNull.Value),
        ]);
        var payload = new NativeJsonObject([
            new("inventory", new NativeJsonArray([
                new NativeJsonObject([
                    new("format", new NativeJsonString("xlsx")),
                    new("capabilities", new NativeJsonObject([
                        new("create", create),
                    ])),
                ]),
            ])),
        ]);

        var rows = OfficeSupportPresentationMapper.FromSurface(
            new NativeSurfaceProjection("office", 1, payload));

        var operations = rows.Single().Operations;
        Assert.AreEqual("하위 기능만 있음", operations.Single(row => row.Label == "생성").Status);
        Assert.AreEqual("에이전트 경로 미연결", operations.Single(row => row.Label == "생성").AgentPath);
        Assert.AreEqual("선택 패키지 필요", operations.Single(row => row.Label == "생성").InstallCondition);
        Assert.AreEqual("미지원", operations.Single(row => row.Label == "재계산").Status);
    }
}
