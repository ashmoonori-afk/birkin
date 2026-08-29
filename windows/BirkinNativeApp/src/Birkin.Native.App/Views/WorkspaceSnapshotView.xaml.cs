using System.Windows;
using System.Windows.Controls;
using Birkin.Native.App.Startup;
using Birkin.Native.Shell;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Views;

public partial class WorkspaceSnapshotView : UserControl
{
    private ShellPresentationModel? _presentationModel;
    private IStartupRecovery? _startupRecovery;

    public WorkspaceSnapshotView() => InitializeComponent();

    public WorkspaceSnapshotView(ShellPresentationModel presentationModel)
        : this() => DataContext = presentationModel;

    public void AttachWorkflow(ShellPresentationModel presentationModel, ShellCoordinator coordinator)
    {
        DataContext = presentationModel;
        PrimaryColumnView.AttachWorkflow(presentationModel, coordinator);
        ContextColumnView.AttachWorkflow(presentationModel, coordinator);
    }

    public void AttachStartupRecovery(
        ShellPresentationModel presentationModel,
        IStartupRecovery startupRecovery)
    {
        _presentationModel = presentationModel;
        _startupRecovery = startupRecovery;
    }

    private async void RetryStartupClicked(
        object sender,
        RoutedEventArgs eventArgs)
    {
        if (_presentationModel is null
            || _startupRecovery is null
            || sender is not Button button)
        {
            return;
        }

        button.IsEnabled = false;
        await System.Windows.Threading.Dispatcher.Yield(
            System.Windows.Threading.DispatcherPriority.Render);
        try
        {
            var failure = await _startupRecovery.RetryAsync();
            if (failure is null)
            {
                _presentationModel.ClearStartupFailure();
            }
            else
            {
                _presentationModel.PresentStartupFailure(failure);
            }
        }
        catch (OperationCanceledException)
        {
            // App shutdown owns this cancellation.
        }
        finally
        {
            button.IsEnabled = true;
        }
    }

    private async void ConfigureExecutableClicked(
        object sender,
        RoutedEventArgs eventArgs)
    {
        if (_presentationModel is null
            || _startupRecovery is null
            || sender is not Button button)
        {
            return;
        }

        button.IsEnabled = false;
        await System.Windows.Threading.Dispatcher.Yield(
            System.Windows.Threading.DispatcherPriority.Render);
        try
        {
            var failure =
                await _startupRecovery.ConfigureExecutableAndRetryAsync(
                    ExecutablePathInput.Text);
            if (failure is null)
            {
                _presentationModel.ClearStartupFailure();
            }
            else
            {
                _presentationModel.PresentStartupFailure(failure);
            }
        }
        catch (OperationCanceledException)
        {
            // App shutdown owns this cancellation.
        }
        finally
        {
            button.IsEnabled = true;
        }
    }

    private void StartupFailureTitleVisibilityChanged(
        object sender,
        DependencyPropertyChangedEventArgs eventArgs)
    {
        if (eventArgs.NewValue is true)
        {
            _ = Dispatcher.BeginInvoke(
                new Action(() => StartupFailureTitle.Focus()));
        }
    }
}
