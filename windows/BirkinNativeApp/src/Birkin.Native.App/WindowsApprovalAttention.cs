using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Automation.Peers;
using System.Windows.Interop;
using System.Windows.Shell;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App;

internal interface IWindowFlasher
{
    void Start(nint window);
    void Stop(nint window);
}

internal sealed class NativeWindowFlasher : IWindowFlasher
{
    private const uint FlashAll = 3;

    public void Start(nint window)
    {
        var info = FlashWindowInfo.Create(window, FlashAll, count: 3);
        _ = FlashWindowEx(ref info);
    }

    public void Stop(nint window)
    {
        var info = FlashWindowInfo.Create(window, flags: 0, count: 0);
        _ = FlashWindowEx(ref info);
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct FlashWindowInfo
    {
        public uint Size;
        public nint Window;
        public uint Flags;
        public uint Count;
        public uint Timeout;

        public static FlashWindowInfo Create(
            nint window,
            uint flags,
            uint count) =>
            new()
            {
                Size = Convert.ToUInt32(Marshal.SizeOf<FlashWindowInfo>()),
                Window = window,
                Flags = flags,
                Count = count,
            };
    }

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool FlashWindowEx(ref FlashWindowInfo info);
}

internal sealed class WindowsApprovalAttention : IDisposable
{
    private readonly Window _window;
    private readonly IWindowFlasher _flasher;
    private readonly IApprovalToast? _toast;
    private readonly string _defaultTitle;
    private bool _deferredFlash;
    private int _pendingCount;

    public WindowsApprovalAttention(
        Window window,
        IWindowFlasher? flasher = null,
        IApprovalToast? toast = null)
    {
        _window = window;
        _flasher = flasher ?? new NativeWindowFlasher();
        _toast = toast;
        _defaultTitle = window.Title;
        _window.Loaded += WindowLoaded;
    }

    public void SetPending(int pendingCount)
    {
        if (pendingCount == _pendingCount)
        {
            return;
        }
        _pendingCount = pendingCount;
        var pending = pendingCount > 0;
        var title = pending
            ? $"승인 대기 {pendingCount}건 - {_defaultTitle}"
            : _defaultTitle;
        _window.Title = title;
        AutomationProperties.SetName(_window, title);
        AutomationProperties.SetLiveSetting(
            _window,
            pending ? AutomationLiveSetting.Polite : AutomationLiveSetting.Off);
        _window.TaskbarItemInfo ??= new TaskbarItemInfo();
        _window.TaskbarItemInfo.ProgressState = pending
            ? TaskbarItemProgressState.Paused
            : TaskbarItemProgressState.None;
        _window.TaskbarItemInfo.ProgressValue = pending ? 1 : 0;
        if (pending && _window.IsLoaded)
        {
            Announce();
        }
        if (!pending)
        {
            _deferredFlash = false;
            StopFlash();
        }
    }

    public void Notify(ApprovalAttentionSignal signal)
    {
        _toast?.Show(ApprovalToastContent.For(signal.ApprovalId));
        if (!_window.IsLoaded)
        {
            _deferredFlash = true;
            return;
        }
        _deferredFlash = false;
        _flasher.Start(new WindowInteropHelper(_window).Handle);
    }

    public void Dispose()
    {
        _window.Loaded -= WindowLoaded;
        _deferredFlash = false;
        SetPending(0);
    }

    private void WindowLoaded(object sender, RoutedEventArgs eventArgs)
    {
        if (_deferredFlash)
        {
            Announce();
            _deferredFlash = false;
            _flasher.Start(new WindowInteropHelper(_window).Handle);
        }
    }

    private void Announce()
    {
        var peer = UIElementAutomationPeer.FromElement(_window)
            ?? new WindowAutomationPeer(_window);
        peer.RaiseAutomationEvent(AutomationEvents.LiveRegionChanged);
    }

    private void StopFlash()
    {
        if (_window.IsLoaded)
        {
            _flasher.Stop(new WindowInteropHelper(_window).Handle);
        }
    }
}
