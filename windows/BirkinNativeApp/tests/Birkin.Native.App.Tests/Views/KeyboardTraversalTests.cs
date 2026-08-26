using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Threading;
using Birkin.Native.App.Tests.Support;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Views;

[TestClass]
public sealed class KeyboardTraversalTests
{
    [TestMethod]
    public async Task KeyboardTraversal_MoveFocusVisitsExpectedControlsWithoutEventDelivery()
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        await using var sta = await StaDispatcherHarness.StartAsync(deadline.Token);
        await sta.InvokeAsync(async () =>
        {
            var commands = new HashSet<string>(["chat.send", "terminal.create"], StringComparer.Ordinal);
            await using var fixture = await OfficeWorkflowViewHarness.CreateAsync(
                emptyConversation: true,
                advertisedCommands: commands);
            var window = new MainWindow(fixture.Model, fixture.Coordinator)
            {
                Width = 1500,
                Height = 940,
                WindowStartupLocation = WindowStartupLocation.Manual,
                Left = 0,
                Top = 0,
            };
            window.Show();
            try
            {
                await window.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.Render);
                window.UpdateLayout();
                var draft = OfficeWorkflowViewHarness.Find<TextBox>(window, "conversation.draft");
                var send = OfficeWorkflowViewHarness.Find<Button>(window, "conversation.send");
                var create = OfficeWorkflowViewHarness.Find<Button>(window, "terminal.create");
                var output = OfficeWorkflowViewHarness.Find<TextBox>(window, "terminal.output");
                Assert.IsTrue(draft.Focus());
                Assert.AreSame(draft, Keyboard.FocusedElement);
                Assert.IsTrue(draft.MoveFocus(new TraversalRequest(FocusNavigationDirection.Next)));
                Assert.AreSame(send, Keyboard.FocusedElement);
                Assert.IsTrue(send.MoveFocus(new TraversalRequest(FocusNavigationDirection.Next)));
                Assert.AreSame(create, Keyboard.FocusedElement);
                Assert.IsTrue(create.MoveFocus(new TraversalRequest(FocusNavigationDirection.Next)));
                Assert.AreSame(output, Keyboard.FocusedElement);
            }
            finally
            {
                window.Close();
            }
        });
    }
}
