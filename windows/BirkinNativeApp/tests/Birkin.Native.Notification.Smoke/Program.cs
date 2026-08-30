using System.Diagnostics;
using System.Security.Principal;
using Birkin.Native.App;
using Birkin.Native.Shell.Presentation;
using Microsoft.Windows.AppNotifications;

Trace.Listeners.Add(new ConsoleTraceListener());
using var identity = WindowsIdentity.GetCurrent();
var principal = new WindowsPrincipal(identity);
var supported = AppNotificationManager.IsSupported();
Console.WriteLine(
    $"WINDOWS_APPROVAL_TOAST_HOST:identity={identity.Name};" +
    $"admin={principal.IsInRole(WindowsBuiltInRole.Administrator)};" +
    $"supported={supported}");

var approvalId = $"qa-background-{Guid.NewGuid():N}";
Console.WriteLine("WINDOWS_APPROVAL_TOAST_STAGE:registering");
using var toast = WindowsApprovalToast.Create(() => { });
if (toast is null)
{
    Console.Error.WriteLine("Windows app notifications are unavailable.");
    return 2;
}

Console.WriteLine("WINDOWS_APPROVAL_TOAST_STAGE:registered");
toast.Show(ApprovalToastContent.For(approvalId));
Console.WriteLine("WINDOWS_APPROVAL_TOAST_STAGE:shown");

var manager = AppNotificationManager.Default;
var notifications = await manager.GetAllAsync();
Console.WriteLine($"WINDOWS_APPROVAL_TOAST_STAGE:queried:{notifications.Count}");
var notification = notifications.SingleOrDefault(
    candidate => candidate.Payload.Contains(approvalId, StringComparison.Ordinal));
if (notification is null)
{
    Console.Error.WriteLine("Windows did not accept the approval notification.");
    return 3;
}

await manager.RemoveByIdAsync(notification.Id);
Console.WriteLine($"WINDOWS_APPROVAL_TOAST_ACCEPTED:{approvalId}");
return 0;
