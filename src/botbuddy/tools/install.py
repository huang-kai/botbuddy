#!/usr/bin/env python3
"""安装到统一应用目录：更新框架文件，保留配置、技能和运行数据。"""
import argparse
from contextlib import ExitStack
import fcntl
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

from botbuddy.paths import data_directory, environment

START = '# >>> BotBuddy PATH >>>'
END = '# <<< BotBuddy PATH <<<'


def write_atomic(path, content, mode=None):
    # 生成文件原子替换；若原位置是链接，不能沿链接覆盖其他应用文件。
    path.parent.mkdir(parents=True, exist_ok=True)
    permissions = mode if mode is not None else (path.stat().st_mode & 0o777 if path.exists() else 0o644)
    fd, name = tempfile.mkstemp(prefix='.botbuddy-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
        os.chmod(name, permissions)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def configure_shell(environment):
    shell_home = Path.home()
    if Path(os.environ.get('SHELL', '/bin/bash')).name == 'zsh':
        shell_home = Path(os.environ.get('ZDOTDIR', shell_home)).expanduser()
        files = [shell_home / '.zshrc', shell_home / '.zprofile']
    else:
        login = next((shell_home / name for name in ('.bash_profile', '.bash_login')
                      if (shell_home / name).exists()), shell_home / '.profile')
        files = [shell_home / '.bashrc', login]
    quoted = shlex.quote(str(environment))
    block = f'{START}\n[ ! -f {quoted} ] || . {quoted}\n{END}\n'
    pattern = re.compile(re.escape(START) + r'.*?' + re.escape(END) + r'\n?', re.S)
    for path in files:
        # 用户可能通过 dotfiles 链接管理 shell 配置，保留该链接和原权限。
        path = path.resolve() if path.is_symlink() else path
        original = path.read_text() if path.exists() else ''
        # 重复安装或切换目录只留一份 PATH 入口，不覆盖用户其他设置。
        text = pattern.sub('', original)
        legacy = re.escape('# >>> PrimeBuddy PATH >>>') + r'.*?' + re.escape('# <<< PrimeBuddy PATH <<<') + r'\n?'
        text = re.sub(legacy, '', text, flags=re.S).rstrip('\n')
        write_atomic(path, (text + '\n' if text else '') + block)


def prepare_dependencies(source):
    # 校验安装目标与系统依赖，不能误用下载目录或其他应用的 PYTHONPATH。
    environment = dict(os.environ, PYTHONPATH=str(source / '_deps'))
    check = [sys.executable, '-c', 'import yaml; assert callable(yaml.safe_dump)']
    if subprocess.run(check, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        return
    print('安装 YAML 依赖到应用目录 _deps/…', flush=True)
    try:
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--no-input',
                        '--retries', '1', '--timeout', '15', '--target', str(source / '_deps'),
                        '-r', str(source / 'requirements.txt')], check=True, timeout=180)
        sys.path.insert(0, str(source / '_deps'))
        subprocess.run(check, env=environment, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise RuntimeError('YAML 依赖安装失败，请检查 pip 和网络后重试。') from None


def prepare_logs(directory):
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.access(directory, os.W_OK):
            return
    except PermissionError:
        pass
    print('需要管理员权限创建日志目录：' + str(directory), flush=True)
    try:
        subprocess.run(['sudo', 'install', '-d', '-m', '700', '-o', str(os.getuid()),
                        '-g', str(os.getgid()), str(directory)], check=True, timeout=60)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        raise RuntimeError('日志目录创建失败，请由管理员准备可写目录：' + str(directory)) from None


def stage_application(source, stage):
    # 只复制框架文件；即使从已安装目录升级，也不复制私有配置和技能数据。
    names = ['main.py', 'README.md', 'CHANGELOG.md', 'release.json', 'requirements.txt', 'src', 'resource', 'scripts',
             'cfg/config.example.yaml', 'cfg/providers.example.yaml', 'cfg/skill-adapters.example.yaml']
    if (source / 'LICENSE').exists():
        names.append('LICENSE')
    if (source / 'cfg/pkg.yaml').exists():
        names.append('cfg/pkg.yaml')
    if (source / 'docs').is_dir():
        names.append('docs')
    for name in names:
        path, target = source / name, stage / name
        if path.is_symlink() or (path.is_dir() and any(item.is_symlink() for item in path.rglob('*'))):
            raise RuntimeError('框架安装文件不能包含符号链接：' + name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.is_dir():
            shutil.copytree(path, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        elif path.is_file():
            shutil.copy2(path, target)
        elif name == 'resource':
            target.mkdir()
        else:
            raise RuntimeError('框架安装文件缺失：' + name)
    return names


def replace_application(stage, home, names):
    previous = stage.parent / 'previous'
    changed = []
    try:
        for name in names:
            target, backup = home / name, previous / name
            # 不沿用户创建的链接写入统一目录之外，也不替换错误类型的路径。
            if any(path.is_symlink() for path in [target, *target.parents]):
                raise RuntimeError('安装目标不能是符号链接：' + str(target))
            if target.exists() and target.is_dir() != (stage / name).is_dir():
                raise RuntimeError('安装目标类型不匹配：' + str(target))
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if target.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                target.rename(backup)
            changed.append(name)
            (stage / name).rename(target)
        configure_shell(home / 'bin/env.sh')
    except BaseException:
        # 替换或 PATH 设置失败时恢复原代码，用户数据始终不在替换清单中。
        for name in reversed(changed):
            target, backup = home / name, previous / name
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink(missing_ok=True)
            if backup.exists():
                backup.rename(target)
        raise


def stage_launcher(stage, home):
    # 恢复入口不导入应用源码，也不依赖机器人 ROS 环境。
    quoted_home = shlex.quote(str(home))
    python = shlex.quote(sys.executable)
    content = '#!/bin/bash\nexport BOTBUDDY_HOME=' + quoted_home + '\n'
    content += 'export PRIMEBUDDY_HOME="$BOTBUDDY_HOME"\n'
    content += ('if [ -f "$BOTBUDDY_HOME/.update/transaction.json" ]; then\n'
                '  if [ "$#" -eq 2 ] && [ "$1" = update ] && [ "$2" = --recover ]; then\n'
                '    exec ' + python + ' "$BOTBUDDY_HOME/.update/runner.py" --recover "$BOTBUDDY_HOME"\n'
                '  fi\n'
                '  echo "存在未完成升级，请先运行 botbuddy update --recover。" >&2\n'
                '  exit 1\nfi\n')
    content += 'source ' + shlex.quote(str(home / 'scripts/robot_env.sh')) + ' || exit $?\n'
    content += 'export PYTHONPATH=' + shlex.quote(str(home / 'src') + os.pathsep + str(home / '_deps')) + '"${PYTHONPATH:+:$PYTHONPATH}"\n'
    content += 'exec ' + python + ' ' + shlex.quote(str(home / 'main.py')) + ' "$@"\n'
    write_atomic(stage / 'bin/botbuddy', content, 0o755)
    write_atomic(stage / 'bin/primebuddy', content, 0o755)
    quoted = shlex.quote(str(home / 'bin'))
    write_atomic(stage / 'bin/env.sh', f'# BotBuddy 命令路径，可重复加载\ncase ":$PATH:" in\n'
                 f'  *:{quoted}:*) ;;\n  *) export PATH={quoted}:"$PATH" ;;\nesac\n')
    return ['bin/botbuddy', 'bin/primebuddy', 'bin/env.sh']


def install(home):
    if sys.version_info < (3, 10):
        raise RuntimeError('需要 Python 3.10 或更高版本。')
    if sys.prefix != sys.base_prefix:
        raise RuntimeError('请退出虚拟环境，使用目标 T1/Q1 的系统 python3 运行安装器，以匹配系统 ROS 2。')
    source = Path(__file__).resolve().parents[3]
    if not (source / 'main.py').is_file():
        raise RuntimeError('缺少框架源码，请完整解压安装包。')
    home = home.expanduser().resolve()
    existing = (home / 'main.py').is_file()
    if ':' in str(home):
        raise RuntimeError('命令目录不能包含 PATH 分隔符“:”。')
    if any(home.is_relative_to(source / name) for name in ('src', 'resource', 'scripts', 'cfg')):
        raise RuntimeError('统一应用目录不能放在框架源码或资源子目录中。')
    os.environ['BOTBUDDY_HOME'] = str(home)
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    home.chmod(0o700)
    with ExitStack() as stack:
        lock = stack.enter_context((home / 'install.lock').open('a'))
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('另一个安装或配置正在进行，请结束后重试。') from None
        # 此时系统可能还没有 PyYAML，事务检查不能提前导入配置模块。
        if (home / '.update/transaction.json').exists():
            raise RuntimeError('存在未完成升级，请先运行 botbuddy update --recover。')
        temp = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='.install-', dir=home)))
        stage = temp / 'new'
        names = stage_application(source, stage)
        prepare_dependencies(stage)
        from botbuddy.tools.update import require_idle_runtime, skill_updates, prepare_skills, commit_update
        from botbuddy.config.compatibility import load_release
        manifest = load_release(source / 'release.json')
        updates = skill_updates(home, manifest)
        from botbuddy.config.logging_setup import log_directory
        from botbuddy.config.runtime import runtime_directory
        runtime = runtime_directory()
        runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        audio_lock = stack.enter_context((runtime / 'audio.lock').open('a'))
        try:
            fcntl.flock(audio_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('BotBuddy 正在运行，请先退出会话再升级。') from None
        require_idle_runtime(runtime)
        prepare_logs(log_directory().resolve())
        from botbuddy.config.storage import config_path
        for name in ('config', 'providers'):
            relative = 'cfg/' + name + '.yaml'
            if not config_path(name + '.yaml').exists():
                write_atomic(stage / relative, (stage / ('cfg/' + name + '.example.yaml')).read_text(), 0o600)
                names.append(relative)
        if (stage / '_deps').exists():
            names.append('_deps')
        names.extend(stage_launcher(stage, home))
        names.extend(prepare_skills(source, stage, manifest, updates))
        if existing or updates:
            configure_shell(home / 'bin/env.sh')
            commit_update(home, stage, names, lock_fds=(lock.fileno(), audio_lock.fileno()))
        else:
            replace_application(stage, home, names)
    return home / 'bin/botbuddy'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=None,
                        help='统一应用目录，含源码、bin、skills 和配置；新安装默认 ~/.botbuddy，已有安装沿用 ~/.primebuddy')
    parser.add_argument('--no-onboard', action='store_true', help='仅注册命令，稍后执行 botbuddy onboard')
    parser.add_argument('--shell-env-file', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    launcher = None
    try:
        from botbuddy.tools.board_install import installation_board, install_on_brain
        requested_home = args.home
        args.home = args.home or data_directory()
        existing = (args.home.expanduser() / 'main.py').is_file()
        board = None if existing else installation_board()
        if board is not None:
            return install_on_brain(board, requested_home or environment('HOME'), args.no_onboard)
        launcher = install(args.home)
        if args.shell_env_file is not None:
            args.shell_env_file.write_text(str(launcher.parent / 'env.sh') + '\n')
        print('BotBuddy 已安装到：' + str(launcher.parent.parent), flush=True)
        print('命令入口：' + str(launcher), flush=True)
        print('新终端已配置 PATH；当前终端可执行：source ' + shlex.quote(str(launcher.parent / 'env.sh')), flush=True)
        if not args.no_onboard and not existing:
            return subprocess.call([str(launcher), 'onboard'])
        return 0
    except (KeyboardInterrupt, EOFError):
        print('配置已取消，命令已安装；可运行 botbuddy onboard 继续。' if launcher else '安装已取消。', file=sys.stderr)
        return 130
    except (RuntimeError, OSError, ValueError) as error:
        print('安装未完成：' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
