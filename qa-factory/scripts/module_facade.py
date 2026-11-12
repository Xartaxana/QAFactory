"""The one forwarding facade of the package: makes a file that was cut into part modules keep its meaning.

A large script is cut into part modules; the original file stays as the entry point and as an import
FACADE. Before the cut one module global was seen by all the file's code and by every reader through
`<stem>.<name>`; after it each part has its own globals. `install(__name__, [<parts, low rank first>])`
is the single place that gives `<stem>.<name>` its old meaning back (AR-15, one survivor for every
cut file):

    import part_a
    import part_b
    import module_facade
    module_facade.install(__name__, [part_a, part_b])       # parts may also be given by module name

MIRROR. At install every name a part binds is copied into the facade's own dict (the first part in the
given order wins, a name the facade binds itself stays), so a reader sees it as a plain module attribute
(`vars`, `import *`, `mock.patch.object` treat it as local). Not mirrored: the names the module machinery
owns (`__spec__`, `__file__`, `__all__`, ...) and every name that ANY part's bytecode rebinds through
`global` (STORE_GLOBAL / DELETE_GLOBAL): those stay forwarded, so a cache a part refills is read live.

READS. `facade.x`, for a name the facade's own dict does not bind, returns the value bound in the part that
bound it at install if it still binds it, else in the FIRST part (the given order) that binds it, LIVE:
no cache. A name bound nowhere raises `AttributeError` exactly as a module does. A module-level
`__getattr__` the facade defined BEFORE install is chained AFTER the parts (it is taken out of the
module dict at install, because the interpreter would otherwise call it before the parts).

WRITES. At install the facade records, per part, the names the part binds at module level and the GLOBAL
names its code accesses (`dis` over every code object and its nested ones: LOAD/STORE/DELETE of
GLOBAL or NAME, builtin names such as `open` included; a name only used as an attribute, `o.x`, is not
recorded; the code objects are the ones the import ALREADY built, reached from the part's dict: its
functions, the members of its classes, staticmethod/classmethod/property/partial/`__wrapped__` inner
functions, closure cells, defaults, and functions inside module-level containers; nothing is compiled a
second time, but for the loader code of a part whose source has a `global` line, read for its rebinding names
only. The module's own top-level code is not kept by Python: what it accessed at import time is
over and what it bound is the dict, which is read. A module-level callable object whose code is not
reachable is listed per part in the state's `skipped`, never an error), and the same for the facade's
own code (the frame that calls `install`). `facade.n = v`, `setattr`, and
`mock.patch.object(facade, n, v)` write `n` into the facade's dict when the facade binds it or its own
code accesses it, into every part whose recorded set holds `n`; a name bound nowhere at all is created
in the facade's dict. `del facade.n` removes `n` from the same places where it is present and raises
`AttributeError` only if it was bound nowhere. `mock.patch.object` round-trips: the first write or
delete of a name remembers the original of each place (or that the place did not bind it, as with a
builtin a part only reads); the write of the object the patch had read, back, or a restoring `del`
followed by that write, puts every place back to ITS original and removes the binding from a place that
had none, provided no other code rebound the name in between; a `patch.object(..., create=True)` of an
absent name leaves no trace.

REFUSED at install: a name a part rebinds through `global` that the facade binds (`from part import n` in
the facade's code) or another part binds: that copy would read stale; the code that rebinds it and
every bare reader of it must live in one part, outsiders read it through the facade.

NOT COVERED, the same as for one plain module today: `from facade import x` taken by an outside module is a
COPY of the value at that moment, not reached by a later patch. Writes do not reach code that is reachable
neither from a part's dict nor from its classes (a function held only as an attribute of a module-level
instance, or in a foreign registry); for the `global` rebinding such code can do, a part whose source has a
line starting with `global` takes its rebinding names from its loader's module code instead (the REFUSED
check stays whole). Not reached either: a name a part reads or
binds only through a string (`globals()["x"]`, `getattr(module, "x")`), a part imported after install, and
a builtin read as a free name by code that is neither a part nor the facade's own module code. A direct
write into a part module (`part.x = v`, or its own non-`global` rebinding) bypasses the facade: the mirrored
copy in the facade is then stale. `importlib.reload` of a facade is not supported. The module object stays
the same object in `sys.modules`: only its `__class__` is swapped for a `ModuleType` subclass; `__name__`,
`__file__`, `__doc__`, `__spec__` are untouched, so it works when the facade is `__main__` (directly, or
through `run_py_entry.run_as_main`).

THREADS. Writes (and deletes) take a re-entrant lock; reads take none and walk the part dicts in a plain loop.
"""
import dis
import functools
import re
import sys
import threading
import types

_MISSING = object()

# What the import system and the module object own: never forwarded to a part, never written to one.
_MACHINERY = frozenset({
    "__builtins__", "__cached__", "__doc__", "__file__", "__loader__", "__name__", "__package__",
    "__path__", "__spec__", "__all__", "__getattr__", "__dir__", "__annotations__",
})
_GLOBAL_OPS = frozenset({"LOAD_GLOBAL", "STORE_GLOBAL", "DELETE_GLOBAL", "LOAD_NAME", "STORE_NAME",
                         "DELETE_NAME", "LOAD_FROM_DICT_OR_GLOBALS"} & set(dis.opmap))
_REBIND_OPS = frozenset({"STORE_GLOBAL", "DELETE_GLOBAL"})
# `dis.get_instructions` builds an object per instruction and cost 0.23 s over the driver's 872 code objects; the
# scan reads the raw bytes for the few opcodes it wants. The test table compares it with `dis` on every run.
_SCAN_OPS = tuple(dis.opmap[name] for name in sorted(_GLOBAL_OPS))
_REBIND_CODES = frozenset(dis.opmap[name] for name in _REBIND_OPS)
_EXTENDED_ARG = dis.opmap["EXTENDED_ARG"]
_LOAD_GLOBAL = dis.opmap["LOAD_GLOBAL"]
_GLOBAL_ARG_SHIFTED = sys.version_info >= (3, 11)      # LOAD_GLOBAL's low argument bit says "push NULL" from 3.11 on


def _scan_dis(code: types.CodeType):
    """The reference scan, by `dis`: (names `code` and its nested code objects access as globals, names they
    rebind through `global`). The fallback of `_scan` and the oracle of its test."""
    access: set = set()
    rebound: set = set()
    stack = [code]
    while stack:
        current = stack.pop()
        for ins in dis.get_instructions(current):
            if ins.opname in _GLOBAL_OPS:
                access.add(ins.argval)
                if ins.opname in _REBIND_OPS:
                    rebound.add(ins.argval)
        stack.extend(const for const in current.co_consts if isinstance(const, types.CodeType))
    return access - _MACHINERY, rebound - _MACHINERY


_PROBE = ("\n".join(f"v{i} = g{i}" for i in range(300)) + "\n"
          "def f():\n    global s1, s2\n    s1 = g1\n    del s2\n    return [o.attr for o in g3]\n"
          "class C:\n    k = g4\n    def m(self):\n        return g5\n")
_fast_ok = None         # None: not compared yet; True: the raw scan equals `dis` on this Python; False: `dis` is used


def _fast_agrees() -> bool:
    try:
        probe = compile(_PROBE, "<module_facade probe>", "exec")
        return _scan_fast(probe) == _scan_dis(probe)
    except Exception:       # any decoding error on this Python: the slow road
        return False


def _scan(code: types.CodeType):
    """`_scan_dis` of `code`, by the fast road when this Python agrees with `dis` on a fixed probe (compared once
    per process); a code object the fast road cannot decode goes to `_scan_dis` alone."""
    global _fast_ok
    if _fast_ok is None:
        _fast_ok = _fast_agrees()
    if _fast_ok:
        try:
            return _scan_fast(code)
        except Exception:
            pass
    return _scan_dis(code)


def _scan_fast(code: types.CodeType):
    """The same answer as `_scan_dis`, read from the raw opcode bytes."""
    access: set = set()
    rebound: set = set()
    stack = [code]
    while stack:
        current = stack.pop()
        raw = current.co_code
        ops = raw[::2]                      # the opcode bytes; the argument byte follows each at raw[2 * k + 1]
        names = current.co_names
        for op in _SCAN_OPS:
            k = ops.find(op)
            while k >= 0:
                arg, j, shift = raw[2 * k + 1], k - 1, 8
                while j >= 0 and ops[j] == _EXTENDED_ARG:      # the high bytes of a long argument
                    arg |= raw[2 * j + 1] << shift
                    j, shift = j - 1, shift + 8
                name = names[arg >> 1 if op == _LOAD_GLOBAL and _GLOBAL_ARG_SHIFTED else arg]
                access.add(name)
                if op in _REBIND_CODES:
                    rebound.add(name)
                k = ops.find(op, k + 1)
        stack.extend(const for const in current.co_consts if isinstance(const, types.CodeType))
    return access - _MACHINERY, rebound - _MACHINERY


_CONTAINERS = (list, tuple, set, frozenset)
_GLOBAL_LINE = re.compile(rb"(?m)^\s*global\s")


def _live_codes(part: types.ModuleType):
    """(code objects of the functions and methods the import of `part` ALREADY built and that run on its globals,
    the names its classes bind, names of the part's callables that are not reachable that way). Python keeps no
    module code object, so what the module-level code itself accessed at import time is not here: it is over, and
    what it bound is the dict."""
    globals_of = part.__dict__
    codes: list = []
    seen: set = set()
    skipped: list = []
    members: set = set()        # what the class bodies bound: the old module-code scan saw them as STORE_NAME

    def visit(obj, top: str | None = None):
        if id(obj) in seen:
            return
        seen.add(id(obj))
        if isinstance(obj, types.FunctionType):
            ours = obj.__globals__ is globals_of
            if ours:
                codes.append(obj.__code__)
            for cell in obj.__closure__ or ():
                try:
                    visit(cell.cell_contents)
                except ValueError:          # an empty cell
                    pass
            if ours:
                for default in (*(obj.__defaults__ or ()), *(obj.__kwdefaults__ or {}).values()):
                    visit(default)
            visit(vars(obj).get("__wrapped__"))
        elif isinstance(obj, type):
            if getattr(obj, "__module__", None) == part.__name__:
                members.update(key for key in vars(obj) if not (key.startswith("__") and key.endswith("__")))
                for member in list(vars(obj).values()):
                    visit(member)
        elif isinstance(obj, dict):
            for member in list(obj.values()):
                visit(member)
        elif isinstance(obj, _CONTAINERS):
            for member in list(obj):
                visit(member)
        elif isinstance(obj, (staticmethod, classmethod, types.MethodType)):
            visit(obj.__func__)
        elif isinstance(obj, property):
            for member in (obj.fget, obj.fset, obj.fdel):
                visit(member)
        elif isinstance(obj, functools.partial):
            visit(obj.func)
            visit(obj.args)
            visit(obj.keywords)
        elif isinstance(obj, functools.cached_property):
            visit(obj.func)
        elif "__wrapped__" in (getattr(obj, "__dict__", None) or ()):
            visit(obj.__dict__["__wrapped__"])      # functools.lru_cache and every other wrapper that says what it wraps
        elif top is not None and callable(obj) and not isinstance(obj, types.BuiltinFunctionType):
            skipped.append(top)         # a callable object: whatever code it runs is not reachable from here

    for key, value in list(globals_of.items()):
        visit(value, key)
    return codes, members, skipped


def _loader_code(part: types.ModuleType):
    spec = part.__spec__
    return spec.loader.get_code(spec.name)


def _has_global_statement(part: types.ModuleType) -> bool:
    """True when the part's source has a line starting with `global` (a hit in a string or comment only costs
    time), or when the source cannot be read: then the rebinding names come from the loader's module code."""
    try:
        with open(part.__spec__.origin, "rb") as handle:
            return _GLOBAL_LINE.search(handle.read()) is not None
    except (OSError, TypeError, ValueError):
        return True


def _prepare(name: str, parts, own_code: types.CodeType):
    """Validate the call and scan the code; nothing is changed.
    Returns (facade, parts, recorded, rebound, own, skipped)."""
    facade = sys.modules.get(name)
    if not isinstance(facade, types.ModuleType):
        raise ValueError(f"module_facade.install: {name!r} is not an imported module")
    if getattr(type(facade), "__module_facade__", False):
        raise ValueError(f"module_facade.install: {name!r} already has a facade installed "
                         "(reload of a facade is not supported)")
    mods = []
    for part in parts:
        mod = sys.modules.get(part) if isinstance(part, str) else part
        if not isinstance(mod, types.ModuleType):
            raise ValueError(f"module_facade.install: part {part!r} is not an imported module")
        if mod is facade:
            raise ValueError(f"module_facade.install: part {part!r} is the facade {name!r} itself")
        if any(mod is other for other in mods):
            raise ValueError(f"module_facade.install: part {part!r} is given twice")
        mods.append(mod)
    recorded, rebound, skipped = [], [], {}
    for mod in mods:
        if not hasattr(getattr(getattr(mod, "__spec__", None), "loader", None), "get_code"):
            raise ValueError(f"module_facade.install: cannot read the code of part {mod.__name__!r} "
                             "(it has no source loader); a part is an imported module of a file")
        codes, members, skipped[mod.__name__] = _live_codes(mod)
        access = set(members)
        stored: set = set()
        for code in codes:
            got_access, got_stored = _scan(code)         # the one scan; only where the code objects come from differs
            access |= got_access
            stored |= got_stored
        if _has_global_statement(mod):                   # code the walk cannot reach may rebind: the old road, this part only
            stored = _scan(_loader_code(mod))[1]
        recorded.append(frozenset((set(mod.__dict__) | access) - _MACHINERY))
        rebound.append(stored)
    for i, stored in enumerate(rebound):
        for attr in sorted(stored):
            copies = [f"facade {name!r}"] if attr in facade.__dict__ else []
            copies += [f"part {m.__name__!r}" for j, m in enumerate(mods) if j != i and attr in m.__dict__]
            if copies:
                raise ValueError(f"module_facade.install: {attr!r} is rebound through `global` in part "
                                 f"{mods[i].__name__!r} and also bound in {copies[0]}: that copy would read stale; "
                                 "keep the rebinding code and every bare reader in one part")
    return facade, mods, recorded, set().union(*rebound), _scan(own_code)[0], skipped


class _Shadow:
    """What one name looked like before the first write or delete through the facade."""
    __slots__ = ("read", "facade", "parts", "last", "places")

    def __init__(self, read, facade, parts):
        self.read = read          # what getattr(facade, name) returned (_MISSING: nothing)
        self.facade = facade      # the facade dict's own binding, or _MISSING
        self.parts = parts        # {part index: that part's binding or _MISSING}
        self.last = _MISSING      # the value written last
        self.places = ()          # where it went: -1 is the facade, i >= 0 is part i


class _State:
    """Everything one installed facade knows; the facade class only forwards to it."""

    def __init__(self, name, ns, dicts, recorded, own, home, chained, skipped=None):
        self.name, self.ns, self.dicts = name, ns, dicts
        self.skipped = skipped or {}        # debug: {part name: names of its callable objects whose code was not reachable}
        self.recorded, self.own, self.home, self.chained = recorded, own, home, chained
        self.lock = threading.RLock()       # a value's __del__ may write through the facade while we hold it
        self.shadows: dict = {}

    def part_value(self, attr):
        if attr in _MACHINERY:
            return _MISSING
        i = self.home.get(attr)
        if i is not None:
            found = self.dicts[i].get(attr, _MISSING)
            if found is not _MISSING:
                return found
        for d in self.dicts:
            found = d.get(attr, _MISSING)
            if found is not _MISSING:
                return found
        return _MISSING

    def forward(self, attr):
        found = self.part_value(attr)
        if found is not _MISSING:
            return found
        if self.chained is not None:
            return self.chained(attr)
        raise AttributeError(f"module {self.name!r} has no attribute {attr!r}")

    def read_now(self, attr):
        return self.ns[attr] if attr in self.ns else self.part_value(attr)

    def place_dict(self, place):
        return self.ns if place < 0 else self.dicts[place]

    def new_shadow(self, attr, holders):
        return _Shadow(self.read_now(attr), self.ns.get(attr, _MISSING),
                       {i: self.dicts[i].get(attr, _MISSING) for i in holders})

    def still_ours(self, shadow, attr):
        for place in shadow.places:
            current = self.place_dict(place).get(attr, _MISSING)
            if current is not shadow.last and current is not _MISSING:
                return False
        return True

    def restore(self, shadow, attr):
        for place, original in [(-1, shadow.facade), *shadow.parts.items()]:
            d = self.place_dict(place)
            if original is _MISSING:
                d.pop(attr, None)
            else:
                d[attr] = original

    def write(self, attr, value):
        if attr in _MACHINERY:
            self.ns[attr] = value
            return
        with self.lock:
            shadow = self.shadows.get(attr)
            if shadow is not None and not self.still_ours(shadow, attr):
                shadow = None                           # someone else rebound it: the old originals are stale
            if shadow is not None and value is shadow.read:
                self.restore(shadow, attr)              # the patch hands the original back
                del self.shadows[attr]
                return
            holders = [i for i, names in enumerate(self.recorded) if attr in names]
            if shadow is None:
                shadow = self.shadows[attr] = self.new_shadow(attr, holders)
            places = list(holders)
            if attr in self.ns or attr in self.own or not holders:
                places.append(-1)
            for place in places:
                self.place_dict(place)[attr] = value
            shadow.last = value
            shadow.places = tuple(places)

    def delete(self, attr):
        if attr in _MACHINERY:
            try:
                del self.ns[attr]
            except KeyError:
                raise AttributeError(f"module {self.name!r} has no attribute {attr!r}") from None
            return
        with self.lock:
            holders = [i for i, names in enumerate(self.recorded) if attr in names]
            present = [i for i in holders if attr in self.dicts[i]]
            if attr not in self.ns and not present:
                raise AttributeError(f"module {self.name!r} has no attribute {attr!r}")
            shadow = self.shadows.get(attr)
            if shadow is None:
                shadow = self.shadows[attr] = self.new_shadow(attr, holders)   # a restoring write needs it
            self.ns.pop(attr, None)
            for i in present:
                del self.dicts[i][attr]
            if shadow.read is _MISSING:
                del self.shadows[attr]                  # a created name: nothing to put back


class _Facade(types.ModuleType):
    """The class a facade module is switched to; install makes one subclass per facade carrying the state."""
    __module_facade__ = True

    def __getattr__(self, attr):
        return type(self).__module_facade_state__.forward(attr)

    def __setattr__(self, attr, value):
        type(self).__module_facade_state__.write(attr, value)

    def __delattr__(self, attr):
        type(self).__module_facade_state__.delete(attr)

    def __dir__(self):
        state = type(self).__module_facade_state__
        out = set(state.ns)
        for d in state.dicts:
            out.update(key for key in d if key not in _MACHINERY)
        return sorted(out)


def install(name: str, parts) -> None:
    """Turn the imported module `name` (its `__name__`; `"__main__"` works) into a facade over `parts`
    (imported module objects or their names, LOW rank first). Call it from the facade's module code: that
    code is the facade's own place for writes. ValueError names the problem (a part that is not an
    imported module, the facade itself as a part, a part twice, a second install, a name that would read
    stale) and leaves the module a plain module."""
    facade, mods, recorded, rebound, own, skipped = _prepare(name, parts, sys._getframe(1).f_code)
    ns = facade.__dict__
    dicts = tuple(mod.__dict__ for mod in mods)
    chained = ns.pop("__getattr__", None)
    home: dict = {}
    for i, d in enumerate(dicts):
        for key in d:
            if key not in _MACHINERY:
                home.setdefault(key, i)
    for key, i in home.items():
        if key not in rebound and key not in ns:
            ns[key] = dicts[i][key]
    state = _State(name, ns, dicts, tuple(recorded), own, home, chained, skipped)
    facade.__class__ = type("_Facade", (_Facade,), {"__module_facade_state__": state})
