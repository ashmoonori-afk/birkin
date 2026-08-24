using Birkin.Native.Protocol.Transport;

namespace Birkin.Native.Shell.Lifecycle;

public abstract record BridgeAttachment(int ProcessId)
{
    public sealed record AttachedExternal : BridgeAttachment
    {
        public AttachedExternal(BridgeAnnouncement announcement)
            : base(announcement.ProcessId) => Announcement = announcement;

        public BridgeAnnouncement Announcement { get; }
    }

    internal sealed record RunningOwned : BridgeAttachment
    {
        internal RunningOwned(int processId)
            : base(processId)
        {
        }
    }
}
