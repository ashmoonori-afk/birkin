using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.Windows.AppNotifications;
using Microsoft.Windows.AppNotifications.Builder;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App;

internal interface IApprovalToast
{
    void Show(ApprovalToastContent content);
}

internal sealed class WindowsApprovalToast : IApprovalToast, IDisposable
{
    private readonly AppNotificationManager _manager;
    private readonly Action _navigateToApprovals;
    private bool _disposed;

    public static WindowsApprovalToast? Create(Action navigateToApprovals)
    {
        if (!AppNotificationManager.IsSupported())
        {
            return null;
        }
        try
        {
            return new WindowsApprovalToast(navigateToApprovals);
        }
        catch (COMException error)
        {
            Trace.TraceError(
                "Windows app notification registration failed: {0}",
                error.ErrorCode);
            return null;
        }
    }

    public WindowsApprovalToast(Action navigateToApprovals)
    {
        _navigateToApprovals = navigateToApprovals;
        _manager = AppNotificationManager.Default;
        _manager.NotificationInvoked += NotificationInvoked;
        _manager.Register();
    }

    public void Show(ApprovalToastContent content)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        var notification = new AppNotificationBuilder()
            .AddArgument("route", content.Route)
            .AddArgument("approval_id", content.ApprovalId)
            .AddText(content.Title)
            .AddText(content.Body)
            .BuildNotification();
        _manager.Show(notification);
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }
        _disposed = true;
        _manager.NotificationInvoked -= NotificationInvoked;
        _manager.Unregister();
    }

    private void NotificationInvoked(
        AppNotificationManager sender,
        AppNotificationActivatedEventArgs eventArgs)
    {
        if (eventArgs.Arguments.TryGetValue("route", out var route)
            && string.Equals(route, "approvals", StringComparison.Ordinal))
        {
            _navigateToApprovals();
        }
    }
}
