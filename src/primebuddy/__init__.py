"""旧 Python 导入兼容层；实现统一在 botbuddy。"""
import importlib
import importlib.abc
import importlib.util
import sys
from pathlib import Path

from botbuddy import __version__


class _LegacyImports(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith('primebuddy.') or fullname == 'primebuddy.__main__':
            return None
        name = 'botbuddy' + fullname[len('primebuddy'):]
        spec = importlib.util.find_spec(name)
        if spec is None:
            return None
        return importlib.util.spec_from_file_location(fullname, spec.origin, loader=self,
                                                    submodule_search_locations=spec.submodule_search_locations)

    def create_module(self, spec):
        return importlib.import_module('botbuddy' + spec.name[len('primebuddy'):])

    def exec_module(self, module):
        pass

    def get_code(self, fullname):
        spec = importlib.util.find_spec('botbuddy' + fullname[len('primebuddy'):])
        return compile(Path(spec.origin).read_bytes(), spec.origin, 'exec')


sys.meta_path.insert(0, _LegacyImports())
