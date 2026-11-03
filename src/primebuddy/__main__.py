"""兼容 python -m primebuddy。"""
from botbuddy.cli.commands import main

if __name__ == '__main__':
    raise SystemExit(main())
