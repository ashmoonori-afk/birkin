using System.Windows;
using System.Windows.Media.Animation;

namespace Birkin.Native.App.Views;

internal sealed class GridLengthAnimation : AnimationTimeline
{
    public GridLength From { get; init; }
    public GridLength To { get; init; }
    public IEasingFunction? EasingFunction { get; init; }
    public override Type TargetPropertyType => typeof(GridLength);

    protected override Freezable CreateInstanceCore() => new GridLengthAnimation();

    public override object GetCurrentValue(object defaultOriginValue, object defaultDestinationValue, AnimationClock animationClock)
    {
        var progress = animationClock.CurrentProgress ?? 0;
        if (EasingFunction is not null) progress = EasingFunction.Ease(progress);
        return new GridLength(From.Value + ((To.Value - From.Value) * progress));
    }
}
