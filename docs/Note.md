## 项目开发虚拟环境配置 (UV)

```shell
sudo pip install uv
uv init my-package -p 3.13 --package --build-backend hatchling
uv sync
uv add requests
uv run src/mediapump/mian.py
uv build
```
```shell
uv add --dev ruff
uv remove --dev ruff
uv tool install ruff
uv tool list
```

## 用 PyInstaller 生成多个独立 exe

```shell
uv add --dev pyinstaller
uv run pyinstaller --onefile
```

## 测试后发布到 PyPI

```shell
pip install twine
twine check dist/*
twine upload --repository testpypi dist/*
pip install --index-url https://test.pypi.org/simple/ example_package
twine upload dist/*
```

## 安装&卸载

```shell
sudo pip install watchdog-host
sudo watchdog-host init
sudo vim /etc/watchdog/config.yaml
sudo systemctl enable --now watchdog-bandwidth.service
```
```shell
systemctl disable --now watchdog-bandwidth.service
watchdog-host clean
pip uninstall -y watchdog-host
rm -f /etc/watchdog/config.yaml
rm -rf /etc/watchdog
```

## 功能需求

- [x] 带宽额度使用超过 90% 通知
