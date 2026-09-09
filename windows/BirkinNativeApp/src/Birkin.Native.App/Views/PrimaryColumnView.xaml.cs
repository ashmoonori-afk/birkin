using System.Windows.Automation;
using System.Windows;
using System.Windows.Controls;
using Birkin.Native.Shell;
using Birkin.Native.Shell.Presentation;

namespace Birkin.Native.App.Views;

public partial class PrimaryColumnView : UserControl
{
    public PrimaryColumnView()
    {
        InitializeComponent();
        ConversationHost.Content = new ConversationView();
        ResearchHost.Content = new ResearchReportView();
    }

    public void AttachWorkflow(ShellPresentationModel presentationModel, ShellCoordinator coordinator)
    {
        ConversationHost.Content = new ConversationView(presentationModel, coordinator);
        ResearchHost.Content = new ResearchReportView { DataContext = presentationModel };
    }

    public void ShowConversation(bool research)
    {
        WorkspaceTitle.Text = research ? "리서치" : "대화";
        WorkspaceDescription.Text = research
            ? "조사 결과의 결론, 근거와 미해결 항목을 원문 그대로 검토합니다."
            : "현재 업무의 대화와 요청을 이어갑니다.";
        ConversationHost.Visibility = research ? Visibility.Collapsed : Visibility.Visible;
        ResearchHost.Visibility = research ? Visibility.Visible : Visibility.Collapsed;
        AutomationProperties.SetName(
            PrimaryColumn,
            research ? "리서치 결과 작업 영역" : "대화 작업 영역");
    }
}
