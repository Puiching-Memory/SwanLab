# 导出初始化函数和log函数
from .data import (
    login,
    register_callbacks,
    init,
    log,
    finish,
    Audio,
    Image,
    Text,
    Run,
    State,
    get_run,
    get_config,
    config,
    get_url,
    get_project_url,
    get_run_dir,
)
from .env import SwanLabEnv
from .package import get_package_version
from .sync import sync_wandb, sync_tensorboardX, sync_tensorboard_torch, sync_mlflow

# 设置默认环境变量
SwanLabEnv.set_default()
# 检查当前需要检查的环境变量
SwanLabEnv.check()

__version__ = get_package_version()

__all__ = [
    "login",
    "init",
    "log",
    "finish",
    "Audio",
    "Image",
    "Text",
    "Run",
    "State",
    "get_run",
    "get_config",
    "config",
    "__version__",
]
