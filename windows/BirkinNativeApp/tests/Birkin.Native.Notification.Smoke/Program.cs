using Birkin.Native.App;
using Birkin.Native.Shell.Presentation;
using Microsoft.Windows.AppNotifications;

var approvalId = $"qa-background-{Guid.NewGuid():N}";
using var toast = WindowsApprovalToast.Create(() => { });
if (toast is null)
{
    Console.Error.WriteLine("Windows app notifications are unavailable.");
    return 2;
}

toast.Show(ApprovalToastContent.For(approvalId));

var manager = AppNotificationManager.Default;
var notifications = await manager.GetAllAsync();
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
