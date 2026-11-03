"""名称迁移的路径规则；安装引导阶段只依赖标准库。"""
import os
from pathlib import Path


def environment(name, default=None):
    return os.environ.get('BOTBUDDY_' + name, os.environ.get('PRIMEBUDDY_' + name, default))


def data_directory():
    explicit = environment('HOME')
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    current, legacy = Path.home() / '.botbuddy', Path.home() / '.primebuddy'
    if current.exists() and legacy.exists() and current.resolve() != legacy.resolve():
        raise ValueError('同时存在 ~/.botbuddy 和 ~/.primebuddy；请用 BOTBUDDY_HOME 或安装 --home 明确选择，未合并数据。')
    return (legacy if legacy.exists() else current).resolve()
