#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys,os
import shutil
import typer
import subprocess
from pathlib import Path
from importlib import resources

app = typer.Typer(
    help="Watchdog Host management tool",
    no_args_is_help=True,  # 无参数时自动显示帮助
)

def _copy_if_not_exists(src_resource: Path, dest_path: Path):
    """
    If the target file does not exist, create the directory and copy the default file.
    If it already exists, skip it without overwriting the user's modifications.
    """
    if dest_path.exists():
        typer.echo(f"Already exists, skipping: {dest_path}")
        return

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src_resource, dest_path)
    typer.echo(f"Installed: {dest_path}")

def _render_systemd_service(src: Path) -> str:
    """
    Render systemd service file content:
    replace /usr/bin/ with current python bin dir
    ONLY in ExecStart lines.
    """
    python_bin_dir = os.path.dirname(sys.executable)

    content = src.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)

    rendered = []
    for line in lines:
        if line.startswith("ExecStart=") and "/usr/bin/" in line:
            line = line.replace("/usr/bin/", f"{python_bin_dir}/")
        rendered.append(line)

    return "".join(rendered)

def _reload_systemd():
    """Reload systemd daemon"""
    try:
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        typer.echo("systemd daemon reloaded successfully.")
    except subprocess.CalledProcessError as e:
        typer.echo(f"Failed to reload systemd daemon: {e}")
    except PermissionError:
        typer.echo("Permission denied: need to run as root to reload systemd.")

@app.command()
def init():
    """Install default configuration files to system directories"""
    typer.echo("Installing default configuration files...")

    # 复制主配置文件
    default_config = resources.files("watchdog_host") / "config.yaml"
    system_config = Path("/etc/watchdog/config.yaml")
    _copy_if_not_exists(default_config, system_config)

    # 复制 systemd 配置模板
    package_systemd_dir = resources.files("watchdog_host") / "systemd"
    system_systemd_dir = Path("/etc/systemd/system")

    newly_installed_services = []  # 新增：记录本次实际新安装的 service 名称

    if package_systemd_dir.is_dir():
        config_files = list(package_systemd_dir.glob("*.service"))
        for src_config in config_files:
            dest_config = system_systemd_dir / src_config.name
            if dest_config.exists():
                typer.echo(f"Already exists, skipping: {dest_config}")
                continue

            # 新安装的才进行渲染和写入
            rendered = _render_systemd_service(src_config)
            dest_config.write_text(rendered, encoding="utf-8")
            typer.echo(f"Installed (rendered): {dest_config}")

            # 记录新安装的 service（去掉 .service 后缀）
            newly_installed_services.append(src_config.stem)

        # 自动 reload systemd
        _reload_systemd()

    typer.echo(f"Python executable directory: {os.path.dirname(sys.executable)}")
    typer.echo("Default configuration files installed successfully!")
    typer.echo("Now you can edit config to customize the settings:")
    typer.echo("  vim /etc/watchdog/config.yaml")

    # === 新增部分：根据实际新安装的 service 输出具体命令 ===
    if newly_installed_services:
        typer.echo("To enable and start the newly installed services, run:")
        for service_name in newly_installed_services:
            typer.echo(f"  systemctl enable --now {service_name}.service")
        typer.echo("\nAlternatively, enable all at once:")
        typer.echo("  systemctl enable --now " + " ".join(f"{name}.service" for name in newly_installed_services))
    else:
        typer.echo("No new systemd service files were installed this time.")
        typer.echo("If you want to enable existing services, run manually:")
        typer.echo("  systemctl enable --now <service>.service")

@app.command()
def clean():
    """Delete the .service files copied by init() and reload systemd"""
    system_systemd_dir = Path("/etc/systemd/system")
    package_systemd_dir = resources.files("watchdog_host") / "systemd"

    if not package_systemd_dir.is_dir():
        typer.echo("No systemd directory found in package, nothing to clear.")
        return

    service_files = list(package_systemd_dir.glob("*.service"))
    deleted_any = False
    for src_service in service_files:
        dest_service = system_systemd_dir / src_service.name
        if dest_service.exists():
            try:
                dest_service.unlink()
                typer.echo(f"Deleted: {dest_service}")
                deleted_any = True
            except PermissionError:
                typer.echo(f"Permission denied, cannot delete: {dest_service}")
            except Exception as e:
                typer.echo(f"Failed to delete {dest_service}: {e}")
        else:
            typer.echo(f"File not found, skipping: {dest_service}")

    # 自动 reload systemd
    _reload_systemd()

    if deleted_any:
        typer.echo("Finished deleting .service files.")
    else:
        typer.echo("No .service files were deleted.")

@app.command()
def run():
    """Run the main watchdog host service (placeholder)"""
    # 这里放 main 逻辑
    typer.echo("Watchdog Host is initializing...")

@app.command()
def version():
    """Show version information"""
    from importlib.metadata import version, PackageNotFoundError
    try:
        ver = version("watchdog-host")
    except PackageNotFoundError:
        ver = "unknown (editable install)"
    typer.echo(f"watchdog-host version {ver}")

if __name__ == "__main__":
    app()
