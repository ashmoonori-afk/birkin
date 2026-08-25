using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using Birkin.Native.Shell.Presentation;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Support;

internal sealed record ProviderOfficeCommandTrace(string CommandId, long CompletionCursor);

internal static class ProviderOfficeJourneyActions
{
    public static async Task<ProviderOfficeCommandTrace> ClickAsync(
        ShellPresentationModel model,
        ProviderOfficeEventLog events,
        Button button,
        string commandType,
        CancellationToken cancellationToken)
    {
        return await RunAsync(
            model,
            events,
            commandType,
            () =>
            {
                button.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                return Task.FromResult(true);
            },
            cancellationToken);
    }

    public static Task<ProviderOfficeCommandTrace> SubmitAsync(
        ShellPresentationModel model,
        ProviderOfficeEventLog events,
        string commandType,
        Func<Task<bool>> submit,
        CancellationToken cancellationToken) =>
        RunAsync(model, events, commandType, submit, cancellationToken);

    private static async Task<ProviderOfficeCommandTrace> RunAsync(
        ShellPresentationModel model,
        ProviderOfficeEventLog events,
        string commandType,
        Func<Task<bool>> submit,
        CancellationToken cancellationToken)
    {
        var begun = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        PropertyChangedEventHandler changed = (_, eventArgs) =>
        {
            if (eventArgs.PropertyName == nameof(ShellPresentationModel.OfficeWorkflow)
                && model.OfficeWorkflow.CommandState == WorkflowCommandState.PendingReceipt
                && model.OfficeWorkflow.CommandType == commandType
                && model.OfficeWorkflow.CommandId is { } commandId)
            {
                begun.TrySetResult(commandId);
            }
        };
        model.PropertyChanged += changed;
        try
        {
            var submitted = submit();
            var commandId = await begun.Task.WaitAsync(cancellationToken);
            var terminal = await events.WaitAsync(
                envelope => ProviderOfficeEventLog.CommandId(envelope) == commandId
                    && ProviderOfficeEventLog.Type(envelope) is "command.completed" or "command.failed",
                cancellationToken);
            Assert.AreEqual("command.completed", ProviderOfficeEventLog.Type(terminal),
                $"{commandType} ended with command.failed");
            Assert.IsTrue(await submitted.WaitAsync(cancellationToken), $"{commandType} was refused");
            return new ProviderOfficeCommandTrace(commandId, ProviderOfficeEventLog.Cursor(terminal));
        }
        finally
        {
            model.PropertyChanged -= changed;
        }
    }
}
