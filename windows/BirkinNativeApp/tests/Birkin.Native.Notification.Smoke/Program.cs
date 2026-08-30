using System.Diagnostics;
using System.Security.Principal;
using Birkin.Native.App;
using Birkin.Native.Shell.Presentation;
using Microsoft.Windows.AppNotifications;

Trace.Listeners.Add(new ConsoleTraceListener());
if (args.Length == 0)
{
    return RestrictedProcessLauncher.RunCurrentExecutable();
}

if (args.Length != 3 ||
    !string.Equals(args[0], "--medium-child", StringComparison.Ordinal) ||
    !string.Equals(args[1], "--result", StringComparison.Ordinal))
{
    Console.Error.WriteLine(
        "Usage: Birkin.Native.Notification.Smoke [--medium-child --result PATH]");
    return 64;
}

using var output = new StreamWriter(args[2], append: false) { AutoFlush = true };
Console.SetOut(output);
Console.SetError(output);

var integrityRid = RestrictedProcessLauncher.GetCurrentIntegrityRid();
var integrity = RestrictedProcessLauncher.IsMediumIntegrity(integrityRid)
    ? "medium"
    : "unexpected";
Console.WriteLine(
    $"WINDOWS_APPROVAL_TOAST_INTEGRITY:{integrity};rid=0x{integrityRid:x}");
if (!RestrictedProcessLauncher.IsMediumIntegrity(integrityRid))
{
    Console.Error.WriteLine("The notification smoke child is not medium integrity.");
    return 4;
}

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
