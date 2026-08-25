using System.Windows;
using System.Windows.Controls;
using Birkin.Native.App.Startup;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace Birkin.Native.App.Tests.Support;

internal static class ProviderOfficeProviderTurn
{
    private const string Sentinel = "OFFICE_PROVIDER_PARTICIPATED";
    private const string SentinelSha256 = "3f78f63495f2955c6b0499884a11d123ed6cfbefbf63aca74c5a41a16b9fd577";
    private const string Request =
        "Compare the imported baseline and candidate spreadsheets and draft a report from the imported template. "
        + "Reply only OFFICE_PROVIDER_PARTICIPATED.";

    public static async Task<ProviderOfficeCommandTrace> SendAsync(
        CompositionRoot composition,
        DependencyObject window,
        ProviderOfficeEventLog events,
        ProviderOfficeEvidence evidence,
        CancellationToken cancellationToken)
    {
        var draft = OfficeWorkflowViewHarness.Find<TextBox>(window, "conversation.draft");
        var send = OfficeWorkflowViewHarness.Find<Button>(window, "conversation.send");
        draft.Text = Request;
        Assert.IsTrue(send.IsEnabled);
        var trace = await ProviderOfficeJourneyActions.ClickAsync(
            composition.PresentationModel, events, send, "chat.send", cancellationToken);
        var user = await events.WaitAsync("message.user", trace.CommandId, cancellationToken);
        var assistant = await events.WaitAsync("message.assistant.completed", trace.CommandId, cancellationToken);
        await ((FrameworkElement)window).Dispatcher.InvokeAsync(() => { });
        var rows = composition.PresentationModel.Workspace!.Conversation;
        Assert.IsTrue(rows.Any(row => row.Kind == "user_message"
            && row.Id == ProviderOfficeEventLog.EventId(user)
            && row.Cursor == ProviderOfficeEventLog.Cursor(user)));
        Assert.IsTrue(rows.Any(row => row.Kind == "assistant_message"
            && row.Id == ProviderOfficeEventLog.EventId(assistant)
            && row.Cursor == ProviderOfficeEventLog.Cursor(assistant)));
        Assert.IsTrue(ProviderOfficeEventLog.Cursor(user) < ProviderOfficeEventLog.Cursor(assistant));
        var assistantRow = AssistantSentinelValidator.ValidateExact(
            rows.Where(row => row.Kind == "assistant_message"
                    && row.Id == ProviderOfficeEventLog.EventId(assistant))
                .Select(row => new AssistantSentinelRow(row.Id, row.Text))
                .ToArray(),
            Sentinel,
            SentinelSha256);
        evidence.RecordText("provider-assistant", assistantRow.Text.Trim());
        evidence.Record("provider-turn", new Dictionary<string, object?>
        {
            ["command_id"] = trace.CommandId,
            ["user_id"] = ProviderOfficeEventLog.EventId(user),
            ["user_cursor"] = ProviderOfficeEventLog.Cursor(user),
            ["assistant_id"] = ProviderOfficeEventLog.EventId(assistant),
            ["assistant_cursor"] = ProviderOfficeEventLog.Cursor(assistant),
        });
        return trace;
    }
}
