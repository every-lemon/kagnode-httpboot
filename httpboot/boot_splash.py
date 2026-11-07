"""Install the Client's distribution-native Plymouth theme during a future build."""

from pathlib import Path
import shutil
from common import atomic

THEME = """[Plymouth Theme]
Name=KagNode × Ubuntu
Description=KagNode HTTP Boot on Ubuntu
ModuleName=script
[script]
ImageDir=/usr/share/plymouth/themes/kagnode
ScriptFile=/usr/share/plymouth/themes/kagnode/kagnode.script
"""
SCRIPT = """Window.SetBackgroundTopColor(0.055, 0.059, 0.067);
Window.SetBackgroundBottomColor(0.055, 0.059, 0.067);
kagnode = Image("kagnode.png");
ubuntu = Image("ubuntu.png");
height = 72;
if (Window.GetWidth() < 700) height = 48;
kagnode = kagnode.Scale(height, height);
ubuntu = ubuntu.Scale(ubuntu.GetWidth() * height / ubuntu.GetHeight(), height);
separator = Image.Text("×", 0.6, 0.65, 0.72, 1, "Sans 22");
width = kagnode.GetWidth() + ubuntu.GetWidth() + separator.GetWidth() + 56;
x = (Window.GetWidth() - width) / 2;
y = Window.GetHeight() * 0.44;
left = Sprite(kagnode); left.SetX(x); left.SetY(y);
join = Sprite(separator); join.SetX(x + kagnode.GetWidth() + 28); join.SetY(y + (height - separator.GetHeight()) / 2);
right = Sprite(ubuntu); right.SetX(x + kagnode.GetWidth() + separator.GetWidth() + 56); right.SetY(y);
caption = Image.Text("KagNode. HTTP Boot", 0.9, 0.92, 0.96, 1, "Sans 15");
label = Sprite(caption); label.SetX((Window.GetWidth() - caption.GetWidth()) / 2); label.SetY(y + height + 32);
fun refresh(time) {
    dots = ".";
    if (Math.Int(time * 2) % 4 > 1) dots = "..";
    if (Math.Int(time * 2) % 4 > 2) dots = "...";
    progress = Image.Text("Please wait" + dots, 0.55, 0.6, 0.68, 1, "Sans 11");
    global.status.SetImage(progress);
    global.status.SetX((Window.GetWidth() - progress.GetWidth()) / 2);
    global.status.SetY(Window.GetHeight() * 0.75);
}
status = Sprite();
Plymouth.SetRefreshFunction(refresh);
"""


def boot_commandline(recovery=False, debug=False):
    # Diagnostics remain opt-in; kernel ring buffers and system journal stay intact.
    command = "console=tty0 " + (
        "httpboot.debug=1 plymouth.enable=0 loglevel=7 systemd.show_status=1"
        if debug
        else "quiet splash loglevel=3 logo.nologo vt.global_cursor_default=0 systemd.show_status=auto rd.udev.log_level=3"
    )
    return command + (" httpboot.recovery=1" if recovery else "")


def install(root):
    root = Path(root)
    ubuntu = root / "usr/share/plymouth/ubuntu-logo.png"
    if not ubuntu.is_file() or ubuntu.is_symlink():
        raise ValueError(
            "The Ubuntu plymouth package must supply its original distribution logo"
        )
    target = root / "usr/share/plymouth/themes/kagnode"
    target.mkdir(parents=True, exist_ok=True)
    target.parent.chmod(0o755)
    target.chmod(0o755)
    shutil.copyfile(
        Path(__file__).with_name("assets") / "boot/kagnode.png", target / "kagnode.png"
    )
    shutil.copyfile(ubuntu, target / "ubuntu.png")
    for image in (target / "kagnode.png", target / "ubuntu.png"):
        image.chmod(0o644)
    atomic(target / "kagnode.plymouth", THEME, 0o644)
    atomic(target / "kagnode.script", SCRIPT, 0o644)
    atomic(
        root / "etc/plymouth/plymouthd.conf",
        "[Daemon]\nTheme=kagnode\nShowDelay=0\n",
        0o644,
    )
    # The Ubuntu services perform startup/shutdown and retain Escape-to-details.
    # Configuration affects only the image root supplied by the Builder.
    return target
