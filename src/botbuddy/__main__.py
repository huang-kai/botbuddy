"""兼容 python -m botbuddy；命令实现统一在 cli。"""
from botbuddy.cli.commands import main

if __name__ == '__main__':
    raise SystemExit(main())
