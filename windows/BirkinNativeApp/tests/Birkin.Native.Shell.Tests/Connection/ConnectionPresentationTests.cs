using Birkin.Native.Shell.Connection;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.Shell.Tests.Connection;

[TestClass]
public sealed class ConnectionPresentationTests
{
    [TestMethod]
    public void Create_WhenStateIsReady_ExposesLocalPrivateStatus()
    {
        // Given / When
        var presentation = ConnectionPresentation.Create(ConnectionState.Ready);

        // Then
        Assert.AreEqual(ConnectionState.Ready, presentation.State);
        Assert.AreEqual("LOCAL · PRIVATE", presentation.StatusText);
        Assert.IsNull(presentation.ErrorCode);
    }

    [DataTestMethod]
    [DataRow(ConnectionState.Disconnected)]
    [DataRow(ConnectionState.Connecting)]
    [DataRow(ConnectionState.Handshaking)]
    [DataRow(ConnectionState.Subscribing)]
    [DataRow(ConnectionState.Failed)]
    public void Create_WhenStateIsNotReady_DoesNotExposeLocalPrivateStatus(ConnectionState state)
    {
        // Given / When
        var presentation = state == ConnectionState.Failed
            ? ConnectionPresentation.Failed("E_CONNECTION")
            : ConnectionPresentation.Create(state);

        // Then
        Assert.AreNotEqual("LOCAL · PRIVATE", presentation.StatusText);
    }

    [TestMethod]
    public void Failed_WhenCodeContainsUnboundedContent_UsesStableFallback()
    {
        // Given
        var unsafeCode = $"record:{new string('x', 200)}";

        // When
        var presentation = ConnectionPresentation.Failed(unsafeCode);

        // Then
        Assert.AreEqual(ConnectionState.Failed, presentation.State);
        Assert.AreEqual("E_CONNECTION", presentation.ErrorCode);
        Assert.IsFalse(presentation.StatusText.Contains(unsafeCode, StringComparison.Ordinal));
    }
}
