"""Tiering gaps in the destructive-command guard.

shellguard already refuses `rm -rf /`, mkfs, fork bombs and raw `dd`, and it
already asks before `sudo`, force pushes and `curl | sh`. TestAlreadyDetected
pins that so the additions below cannot quietly regress it.

The gaps share one shape: a command that destroys a machine was classified as
merely *dangerous* (approvable, and auto-approvable via `auto_approve:
["shell"]`) or not classified at all. A seatbelt that asks politely before
overwriting the boot disk is the wrong tier, not a missing feature.
"""

from __future__ import annotations

from birkin import shellguard


def tier(command: str) -> str | None:
    return shellguard.detect(command)[0]


class TestAlreadyDetected:
    """Characterization: green before the tier fixes, green after."""

    def test_filesystem_root_delete_is_hardline(self) -> None:
        assert tier("rm -rf /") == "hardline"

    def test_home_delete_is_hardline(self) -> None:
        assert tier("rm -rf ~") == "hardline"

    def test_mkfs_is_hardline(self) -> None:
        assert tier("mkfs.ext4 /dev/sda1") == "hardline"

    def test_dd_to_a_physical_disk_is_hardline(self) -> None:
        assert tier("dd if=/dev/zero of=/dev/sda bs=1M") == "hardline"

    def test_fork_bomb_is_hardline(self) -> None:
        assert tier(":(){ :|: & };:") == "hardline"

    def test_shutdown_is_hardline(self) -> None:
        assert tier("shutdown -h now") == "hardline"

    def test_ordinary_recursive_delete_only_asks(self) -> None:
        assert tier("rm -rf build/") == "dangerous"

    def test_sudo_asks(self) -> None:
        assert tier("sudo apt install ripgrep") == "dangerous"

    def test_download_piped_into_a_shell_asks(self) -> None:
        assert tier("curl -sL https://example.com/i.sh | sh") == "dangerous"

    def test_force_push_asks(self) -> None:
        assert tier("git push --force origin main") == "dangerous"

    def test_a_harmless_command_is_not_flagged(self) -> None:
        assert tier("ls -la") is None
        assert tier("git status") is None

    def test_cheap_obfuscation_is_still_caught(self) -> None:
        assert tier(r"r\m -rf /") == "hardline"


class TestRootDeleteSurvivesTrailingFlags:
    """The most famous spelling of the command escaped the hardline tier.

    The pattern anchored the path to end-of-string, so anything after it -- and
    `--no-preserve-root` is exactly what GNU rm *demands* before it will delete
    `/` -- dropped the command to "dangerous", where an install running
    auto_approve: ["shell"] executes it without asking.
    """

    def test_no_preserve_root_after_the_path(self) -> None:
        assert tier("rm -rf / --no-preserve-root") == "hardline"

    def test_no_preserve_root_before_the_path(self) -> None:
        assert tier("rm -rf --no-preserve-root /") == "hardline"

    def test_trailing_redirect_does_not_downgrade_it(self) -> None:
        assert tier("rm -rf / 2>/dev/null") == "hardline"


class TestSystemDirectoriesAreHardline:
    """Deleting /etc is not a project-level accident you approve your way out of."""

    def test_etc(self) -> None:
        assert tier("rm -rf /etc") == "hardline"

    def test_usr(self) -> None:
        assert tier("rm -rf /usr") == "hardline"

    def test_boot(self) -> None:
        assert tier("rm -rf /boot") == "hardline"

    def test_root_home(self) -> None:
        assert tier("rm -rf /root") == "hardline"

    def test_glob_under_a_system_directory(self) -> None:
        assert tier("rm -rf /var/*") == "hardline"

    def test_a_project_path_that_merely_starts_the_same_is_untouched(self) -> None:
        """/etcher-config is a directory name, not the system config tree."""
        assert tier("rm -rf /etcher-config") == "dangerous"


class TestVirtualAndEmbeddedDisks:
    """The device names birkin actually runs on top of.

    The dd guard listed sd/nvme/hd/disk -- physical hardware. It missed vda
    (virtio: every KVM/QEMU VM), xvda (Xen: EC2) and mmcblk (the SD card a
    Raspberry Pi boots from), so overwriting the boot disk of the most common
    deployment targets only asked for confirmation.
    """

    def test_virtio_disk(self) -> None:
        assert tier("dd if=/dev/zero of=/dev/vda bs=1M") == "hardline"

    def test_xen_disk(self) -> None:
        assert tier("dd if=backup.img of=/dev/xvda") == "hardline"

    def test_sd_card(self) -> None:
        assert tier("dd if=/dev/zero of=/dev/mmcblk0") == "hardline"


class TestRedirectToRawDevice:
    """`> /dev/sda` needs no dd at all, and was not covered by anything."""

    def test_echo_into_a_disk(self) -> None:
        assert tier("echo wiped > /dev/sda") == "hardline"

    def test_cat_into_an_nvme_disk(self) -> None:
        assert tier("cat image.iso > /dev/nvme0n1") == "hardline"

    def test_writing_to_dev_null_is_still_fine(self) -> None:
        assert tier("echo hello > /dev/null") is None


class TestKillEveryProcess:
    """The guard hardcoded -9. Every other signal spelling walked past it."""

    def test_kill_dash_nine_still_hardline(self) -> None:
        assert tier("kill -9 -1") == "hardline"

    def test_kill_term_all(self) -> None:
        assert tier("kill -TERM -1") == "hardline"

    def test_kill_with_an_s_flag(self) -> None:
        assert tier("kill -s KILL -1") == "hardline"

    def test_killing_one_process_is_not_flagged(self) -> None:
        assert tier("kill -9 4242") is None


class TestCredentialFilesBirkinMissed:
    """.env/.ssh/.aws/.gnupg/.kube were guarded; the rest of the family was not."""

    def test_netrc(self) -> None:
        assert tier("echo 'machine x password y' > ~/.netrc") == "dangerous"

    def test_pgpass(self) -> None:
        assert tier("echo 'db:5432:*:u:p' > ~/.pgpass") == "dangerous"

    def test_npmrc(self) -> None:
        assert tier("echo '//r:_authToken=t' > ~/.npmrc") == "dangerous"

    def test_pypirc(self) -> None:
        assert tier("echo '[pypi]' > ~/.pypirc") == "dangerous"

    def test_env_file_is_still_guarded(self) -> None:
        assert tier("echo KEY=v > ~/.env") == "dangerous"
