using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Views;

public partial class DiffView : UserControl, INotifyPropertyChanged
{
    private readonly ShellPresentationModel? _model;
    private IReadOnlyList<PanelItemPresentation> _diffRows = [];

    public DiffView()
    {
        InitializeComponent();
        Visibility = System.Windows.Visibility.Collapsed;
    }

    public DiffView(ShellPresentationModel model) : this()
    {
        _model = model;
        DataContext = model;
        model.PropertyChanged += ModelPropertyChanged;
        UpdateRows();
        Unloaded += ViewUnloaded;
    }

    public event PropertyChangedEventHandler? PropertyChanged;
    public IReadOnlyList<PanelItemPresentation> DiffRows
    {
        get => _diffRows;
        private set
        {
            _diffRows = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(DiffRows)));
        }
    }

    private void ModelPropertyChanged(object? sender, PropertyChangedEventArgs eventArgs)
    {
        if (eventArgs.PropertyName == nameof(ShellPresentationModel.Workspace))
        {
            UpdateRows();
        }
    }

    private void UpdateRows()
    {
        DiffRows = _model?.Workspace?.Office
            .Where(row => string.Equals(row.Kind, "diff", StringComparison.Ordinal)).ToArray() ?? [];
        Visibility = DiffRows.Count == 0
            ? System.Windows.Visibility.Collapsed
            : System.Windows.Visibility.Visible;
    }

    private void ViewUnloaded(object sender, RoutedEventArgs eventArgs)
    {
        if (_model is not null)
        {
            _model.PropertyChanged -= ModelPropertyChanged;
        }
    }
}
