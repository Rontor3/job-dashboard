"""Every global name a function reads must exist in its module.

A missing local import (`failing_fields` in graph._validation_refill, live 2026-10-24) only blows up when that
branch runs on a real site, and apply.py's walk() fallback then hid it. symtable sees it without running anything."""

import builtins
import importlib
import pathlib
import symtable

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"


def _globals_read(table):
    for child in table.get_children():
        if child.get_type() == "function":
            for s in child.get_symbols():
                if s.is_global() and s.is_referenced() and not (s.is_assigned() or s.is_parameter()):
                    yield child.get_name(), s.get_name()
        yield from _globals_read(child)


def test_no_undefined_globals():
    missing = []
    for path in sorted((SRC / "career_agent").rglob("*.py")):
        mod_name = ".".join(path.relative_to(SRC).with_suffix("").parts).removesuffix(".__init__")
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue                        # optional deps (playwright extras etc.): not this test's concern
        table = symtable.symtable(path.read_text(), str(path), "exec")
        defined = set(vars(mod)) | set(dir(builtins)) | {      # + names bound only under `if __name__ == "__main__"`
            s.get_name() for s in table.get_symbols() if s.is_assigned() or s.is_imported()}
        missing += [f"{mod_name}.{fn}: {name}" for fn, name in _globals_read(table) if name not in defined]
    assert not missing, "undefined names:\n" + "\n".join(missing)
