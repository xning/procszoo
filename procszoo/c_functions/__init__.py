# Copyright 2016 Red Hat, Inc. All Rights Reserved.
# Licensed to GPL under a Contributor Agreement.

import os
import sys
import atexit
import re
from ctypes import (cdll, c_int, c_long, c_char_p, c_size_t, string_at,
                    create_string_buffer, c_void_p, CFUNCTYPE, pythonapi)
from distutils.log import warn as printf
try:
    from functools import reduce
except ImportError:
    pass

_pyroute2_module_available = False
_pyroute2_netns_available = False
try:
    import pyroute2
except ImportError:
    pass
else:
    _pyroute2_module_available = True

if _pyroute2_module_available:
    try:
        pyroute2.NetNS
    except AttributeError:
        pass
    else:
        _pyroute2_netns_available = True

import pickle
from copy import copy, deepcopy
import json

from ..namespaces import *
from .macros import *

from .atfork import atfork as c_atfork

if os.uname()[0] != "Linux":
    raise ImportError("only support Linux platform")

__version__ = '0.97.1'
__all__ = [
    "cgroup_namespace_available", "ipc_namespace_available",
    "net_namespace_available", "mount_namespace_available",
    "pid_namespace_available", "user_namespace_available",
    "uts_namespace_available", "show_namespaces_status",
    "NamespaceGenericException", "UnknownNamespaceFound",
    "UnavailableNamespaceFound", "NamespaceSettingError",
    "NamespaceRequireSuperuserPrivilege",
    "CFunctionBaseException", "CFunctionNotFound", "CFunctionCallFailed",
    "workbench", "atfork", "sched_getcpu", "mount", "umount",
    "umount2", "unshare", "pivot_root", "adjust_namespaces",
    "setns", "spawn_namespaces", "check_namespaces_available_status",
    "show_namespaces_status", "gethostname", "sethostname",
    "getdomainname", "setdomainname", "show_available_c_functions",
    "get_namespace", "unregister_fork_handlers", "to_unicode", "to_bytes",
    "__version__",]

_HOST_NAME_MAX = 256
_CDLL = cdll.LoadLibrary(None)
_ACLCHAR = 0x006
_MAX_USERS_MAP = 5
_MAX_GROUPS_MAP = 5
_PREPARE_FORKHANDLERS = []
_PARENT_FORKHANDLERS = []
_CHILD_FORKHANDLERS = []
_CALLERS_REGISTERED = False

def _register_fork_handlers(prepare=None, parent=None, child=None):
    if prepare is not None:
        _PREPARE_FORKHANDLERS.append(prepare)
    if parent is not None:
        _PARENT_FORKHANDLERS.append(parent)
    if child is not None:
        _CHILD_FORKHANDLERS.append(child)

def _prepare_caller():
    for hdr in _PREPARE_FORKHANDLERS:
        if hdr:
            hdr()

def _parent_caller():
    for hdr in _PARENT_FORKHANDLERS:
        if hdr:
            hdr()

def _child_caller():
    for hdr in _CHILD_FORKHANDLERS:
        if hdr:
            hdr()

def _handler_registered_exist():
    return (_PREPARE_FORKHANDLERS
                or _PARENT_FORKHANDLERS
                or _CHILD_FORKHANDLERS)

def _unregister_fork_handlers(prepare=None, parent=None,
                                 child=None, strict=False):
    if prepare is not None and prepare in _PREPARE_FORKHANDLERS:
        _PREPARE_FORKHANDLERS.remove(prepare)
    elif parent is not None and parent in _PARENT_FORKHANDLERS:
        _PARENT_FORKHANDLERS.remove(parent)
    elif child is not None and child in _CHILD_FORKHANDLERS:
        _CHILD_FORKHANDLERS.remove(child)
    else:
        return

    if strict:
        return _unregister_fork_handlers(prepare, parent, child, strict)

def _fork():
    pid = os.fork()
    _errno_c_int = c_int.in_dll(pythonapi, "errno")
    if pid == - 1:
        raise RuntimeError(os.strerror(_errno_c_int.value))
    return pid

def _write2file(path, str=None):
    if path is None:
        raise RuntimeError("path cannot be none")
    if str is None:
        str = ""

    fo = open(path, 'w')
    fo.write(str)
    fo.close()

def _map_id(map_file, map=None, pid=None):
    if pid is None:
        pid = "self"
    else:
        pid = "%d" % pid
    path = "/proc/%s/%s" % (pid, map_file)
    if os.path.exists(path):
        _write2file(path, map)
    else:
        raise RuntimeError("%s: No such file" % path)

def _write_to_uid_and_gid_map(maproot, users_map, groups_map, pid):
    if maproot:
        maps = ["0 %d 1" % os.geteuid()]
    else:
        maps = []
    if users_map:
        maps = maps + users_map
    if maps:
        if len(maps) > _MAX_USERS_MAP:
            raise NamespaceSettingError()
        map_str = "%s\n" % "\n".join(maps)
        _map_id("uid_map", map_str, pid)

    if maproot:
        maps = ["0 %d 1" % os.getegid()]
    else:
        maps = []
    if groups_map is not None:
        maps = maps + groups_map
    if maps:
        if len(maps) > _MAX_GROUPS_MAP:
            raise NamespaceSettingError()
        map_str = "%s\n" % "\n".join(maps)
        _map_id("gid_map", map_str, pid)

def _find_my_init(pathes=None, name=None, file_mode=None, dir_mode=None):
    if pathes is None:
        if 'PATH' in os.environ:
            pathes = os.environ['PATH'].split(':')
        else:
            pathes = []
        cwd = os.path.dirname(os.path.abspath(__file__))
        absdir = os.path.abspath("%s/../.." % cwd)
        pathes += [path for path in ["%s/lib/procszoo" % absdir,
                    "%s/bin" % absdir,
                    "/usr/local/lib/procszoo",
                    "/usr/lib/procszoo"] if os.path.exists(path)]
    if name is None:
        name = "my_init"

    if file_mode is None:
        file_mode = os.R_OK
    if dir_mode is None:
        dir_mode = os.R_OK

    for path in pathes:
        my_init = "%s/%s" % (path, name)
        if os.path.exists(my_init):
            if os.access(my_init, file_mode):
                return my_init

    dirs_access_refused = []
    files_access_refused = []
    for path in pathes:
        my_init = "%s/%s" % (path, name)
        dirs = my_init.split('/')
        tmp_path = '/'
        for path_name in dirs:
            if not path_name: continue
            tmp_path = os.path.join(tmp_path, path_name)
            if tmp_path in dirs_access_refused: break
            if tmp_path in files_access_refused: break
            if os.path.exists(tmp_path):
                if os.path.isdir(tmp_path):
                    if not os.access(tmp_path, dir_mode):
                        dirs_access_refused.append(tmp_path)
                        break
                elif os.path.isfile(tmp_path):
                    if not os.access(tmp_path, file_mode):
                        files_access_refused.append(tmp_path)
                        break

    if dirs_access_refused or files_access_refused:
        if len(dirs_access_refused) + len(files_access_refused) > 1:
            err_str = "[%s]" % "\n".join(
                dirs_access_refused + files_access_refused)
        else:
            err_str = "'%s'" % " ".join(
                dirs_access_refused + files_access_refused)
        raise IOError("Permission denied: %s" % err_str)

    raise NamespaceSettingError()

def _find_shell(name="bash", shell=None):
    if shell is not None:
        return shell
    if "SHELL" in os.environ:
        return os.environ.get("SHELL")
    for path in ["/bin", "/usr/bin", "/usr/loca/bin"]:
        fpath = "%s/%s" % (path, name)
        if os.path.isfile(fpath) and os.access(fpath, os.X_OK):
            return fpath
    return "sh"

def is_string_or_unicode(obj):
    if sys.version_info >= (3, 0):
        return isinstance(obj, (str, bytes))
    else:
        return isinstance(obj, basestring)

if sys.version_info >= (3, 0):
    def _to_str(bytes_or_str):
        if isinstance(bytes_or_str, bytes):
            value = bytes_or_str.decode('utf-8')
        else:
            value = bytes_or_str
        return value

    def _to_bytes(bytes_or_str):
        if isinstance(bytes_or_str, str):
            value = bytes_or_str.encode('utf-8')
        else:
            value = bytes_or_str
        return value
else:
    def _to_unicode(unicode_or_str):
        if isinstance(unicode_or_str, str):
            value = unicode_or_str.decode('utf-8')
        else:
            value = unicode_or_str
        return value

    def _to_str(unicode_or_str):
        if isinstance(unicode_or_str, unicode):
            value = unicode_or_str.encode('utf-8')
        else:
            value = unicode_or_str
        return value

def to_unicode(unicode_or_bytes_or_str):
    if sys.version_info >= (3, 0):
        return _to_str(unicode_or_bytes_or_str)
    else:
        return _to_unicode(unicode_or_bytes_or_str)

def to_bytes(unicode_or_bytes_or_str):
    if sys.version_info >= (3, 0):
        return _to_bytes(unicode_or_bytes_or_str)
    else:
        return _to_str(unicode_or_bytes_or_str)

def _copy_args(namespaces=None, maproot=True, mountproc=True,
                   mountpoint=None, ns_bind_dir=None, nscmd=None,
                   propagation=None, negative_namespaces=None,
                   setgroups=None, users_map=None, groups_map=None,
                   init_prog=None, func=None):
    _args = deepcopy({
        "namespaces": namespaces, "maproot": maproot,
        "mountproc": mountproc, "mountpoint": mountpoint,
        "ns_bind_dir": ns_bind_dir, "nscmd": nscmd,
        "propagation": propagation,
        "negative_namespaces": negative_namespaces,
        "setgroups": setgroups, "users_map": users_map,
        "groups_map": groups_map, "init_prog": init_prog,
        })
    if func is None or not hasattr(func, '__name__'):
        func_name = ''
    else:
        func_name = func.__name__

    _args['func'] = func_name
    return _args

def _need_super_user_privilege(namespaces, ns_bind_dir,
                                   users_map, groups_map):
    require_root_privilege = False
    if not user_namespace_available():
        require_root_privilege = True
    if namespaces and "user" not in namespaces:
        require_root_privilege = True
    if ns_bind_dir:
        require_root_privilege = True
    if users_map or groups_map:
        require_root_privilege = True
    return require_root_privilege

class CFunction(object):
    """
    wrapper class for C library function. These functions could be accessed
    by workbench._c_func_name, e.g., workbench._c_func_unshare.
    """
    def __init__(self, argtypes=None, restype=c_int,
                     exported_name=None,
                     failed=lambda res: res != 0,
                     possible_c_func_names=None,
                     extra=None, func=None):
        self.failed = failed
        self.func = func
        self.exported_name = exported_name

        if is_string_or_unicode(possible_c_func_names):
            self.possible_c_func_names = [possible_c_func_names]
        elif isinstance(possible_c_func_names, list):
            self.possible_c_func_names = possible_c_func_names
        elif possible_c_func_names is None:
            self.possible_c_func_names = [exported_name]
        self.extra = extra

        for name in self.possible_c_func_names:
            if hasattr(_CDLL, name):
                func = getattr(_CDLL, name)
                func.argtypes = argtypes
                func.restype = restype
                self.func = func
                break

class Workbench(object):
    """
    class used as a singleton.
    """
    def __init__(self):
        self.my_init = _find_my_init()
        self.functions = {}
        self.available_c_functions = []
        self.namespaces = Namespaces()
        self._init_c_functions()
        self._namespaces_available_status_checked = False

    def _init_c_functions(self):
        exported_name = "unshare"
        self.functions[exported_name] = CFunction(
            exported_name=exported_name,
            argtypes=[c_int])

        exported_name = "sched_getcpu"
        self.functions[exported_name] = CFunction(
            exported_name=exported_name,
            argtypes=None,
            failed=lambda res: res == -1)

        exported_name = "setns"
        self.functions[exported_name] = CFunction(
            exported_name=exported_name,
            argtypes=[c_int, c_int],
            extra={
                "default args": {
                    "file_instance": None,
                    "file_descriptor": None,
                    "path": None,
                    "namespace": 0}
                })

        exported_name = "syscall"
        extra = {}
        if SYSCALL_PIVOT_ROOT_AVAILABLE:
            extra["pivot_root"] = NR_PIVOT_ROOT
        if SYSCALL_SETNS_AVAILABLE:
            extra["setns"] = NR_SETNS

        self.functions[exported_name] = CFunction(
            exported_name=exported_name, extra=extra)

        exported_name = "mount"
        self.functions[exported_name] = CFunction(
            exported_name=exported_name,
            argtypes=[c_char_p, c_char_p, c_char_p, c_long, c_void_p],
            extra={
                "default args": {
                    "source": None,
                    "target": None,
                    "filesystemtype": None,
                    "flags": None,
                    "data": None,},

                "flag": {
                    "MS_NOSUID": 2, "MS_NODEV": 4,
                    "MS_NOEXEC": 8, "MS_REC": 16384,
                    "MS_PRIVATE": 1 << 18,
                    "MS_SLAVE": 1 << 19,
                    "MS_SHARED": 1 << 20,
                    "MS_BIND": 4096,},

                "propagation": {
                    "slave": ["MS_REC", "MS_SLAVE"],
                    "private": ["MS_REC", "MS_PRIVATE"],
                    "shared": ["MS_REC", "MS_SHARED"],
                    "bind": ["MS_BIND"],
                    "mount_proc": ["MS_NOSUID", "MS_NODEV", "MS_NOEXEC"],
                    "unchanged": [],}
                })

        exported_name = "umount"
        self.functions[exported_name] = CFunction(
            exported_name=exported_name,
            argtypes=[c_char_p])

        exported_name = "umount2"
        self.functions[exported_name] = CFunction(
            exported_name=exported_name,
            argtypes=[c_char_p, c_int],
            extra = {
                "flag": {
                    "MNT_FORCE": 1,
                    "MNT_DETACH": 2,
                    "MNT_EXPIRE": 4,
                    "UMOUNT_NOFOLLOW": 8,},
                "behaviors": {
                    "force": "MNT_FORCE",
                    "detach": "MNT_DETACH",
                    "expire": "MNT_EXPIRE",
                    "nofollow": "UMOUNT_NOFOLLOW",}
                })

        exported_name = "gethostname"
        self.functions[exported_name] = CFunction(
            exported_name = exported_name,
            argtypes=[c_char_p, c_size_t])

        exported_name = "sethostname"
        self.functions[exported_name] = CFunction(
            exported_name=exported_name,
            argtypes=[c_char_p, c_size_t])

        exported_name = "getdomainname"
        self.functions[exported_name] = CFunction(
            exported_name=exported_name,
            argtypes=[c_char_p, c_size_t])

        exported_name = "setdomainname"
        self.functions["setdomainname"] = CFunction(
            exported_name=exported_name,
            argtypes=[c_char_p, c_size_t])

        for func_name in self.functions:
            if func_name == 'syscall': continue
            func_obj = self.functions[func_name]
            if func_obj.func:
                self.available_c_functions.append(func_name)
            else:
                try:
                    self._syscall_nr(func_name)
                except CFunctionUnknowSyscall as e:
                    pass
                else:
                    self.available_c_functions.append(func_name)
        func_name = "pivot_root"
        if func_name not in self.available_c_functions:
            try:
                self._syscall_nr(func_name)
            except CFunctionUnknowSyscall as e:
                pass
            else:
                self.available_c_functions.append(func_name)
        self.available_c_functions.sort()

    def _syscall_nr(self, syscall_name):
        func_obj = self.functions["syscall"]
        if syscall_name in func_obj.extra:
            return func_obj.extra[syscall_name]
        else:
            raise CFunctionUnknowSyscall()


    def __getattr__(self, name):
        if name.startswith("_c_func_"):
            c_func_name = name.replace("_c_func_", "")
            if c_func_name not in self.available_c_functions:
                if c_func_name != 'syscall':
                    raise CFunctionNotFound(c_func_name)
            func_obj = self.functions[c_func_name]
            c_func = func_obj.func
            context = locals()
            def c_func_wrapper(*args, **context):
                tmp_args = []
                for arg in args:
                    if is_string_or_unicode(arg):
                        tmp_args.append(to_bytes(arg))
                    else:
                        tmp_args.append(arg)
                res = c_func(*tmp_args)
                c_int_errno = c_int.in_dll(pythonapi, "errno")
                if func_obj.failed(res):
                    if c_int_errno.value == EPERM:
                        raise NamespaceRequireSuperuserPrivilege()
                    else:
                        raise CFunctionCallFailed(os.strerror(c_int_errno.value))
                return res

            return c_func_wrapper
        else:
            raise AttributeError("'CFunction' object has no attribute '%s'"
                                     % name)

    def atfork(self, prepare=None, parent=None, child=None):
        """
        This function will let us to insert our codes before and after fork
            prepare()
            pid = os.fork()
            if pid == 0:
                child()
                ...
            elif pid > 0:
                parent()
                ...
        """
        global _CALLERS_REGISTERED
        _register_fork_handlers(prepare=prepare, parent=parent, child=child)

        if not _CALLERS_REGISTERED and _handler_registered_exist():
            ret = c_atfork(_prepare_caller, _parent_caller, _child_caller)
            if ret != 0:
                raise RuntimeError("Failed to call atfork(), return code %s" % ret)
            _CALLERS_REGISTERED = True

    def unregister_fork_handlers(self, prepare=None, parent=None,
                                     child=None, strict=False):
        return _unregister_fork_handlers(prepare, parent, child, strict)

    def check_namespaces_available_status(self):
        """
        On rhel6/7, the kernel default does not enable all namespaces
        that it supports.
        """
        if self._namespaces_available_status_checked:
            return

        unshare = self.functions["unshare"].func

        r, w = os.pipe()

        pid0 = _fork()
        if pid0 == 0:
            pid1 = _fork()
            if pid1 == 0:
                os.close(r)
                tmpfile = os.fdopen(w, 'wb')
                keys = []
                for ns in self.namespaces.namespaces:
                    ns_obj = self.get_namespace(ns)
                    val = ns_obj.value
                    res = unshare(c_int(val))
                    _errno_c_int = c_int.in_dll(pythonapi, "errno")
                    if res == -1:
                        if _errno_c_int.value != EINVAL:
                            keys.append(ns)
                    else:
                        keys.append(ns)

                pickle.dump(keys, tmpfile)
                tmpfile.close()
                sys.exit(0)
            else:
                os.waitpid(pid1, 0)
                sys.exit(0)
        else:
            os.close(w)
            tmpfile = os.fdopen(r, 'rb')
            os.waitpid(pid0, 0)
            keys = pickle.load(tmpfile)
            tmpfile.close()

            for ns_name in self.namespaces.namespaces:
                if ns_name not in keys:
                    ns_obj = self.get_namespace(ns_name)
                    ns_obj.available = False

            self._namespaces_available_status_checked = True

    def show_available_c_functions(self):
        return self.available_c_functions

    def sched_getcpu(self):
        return self._c_func_sched_getcpu()

    def cgroup_namespace_available(self):
        return self.namespaces.cgroup_namespace_available

    def ipc_namespace_available(self):
        return self.namespaces.ipc_namespace_available

    def net_namespace_available(self):
        return self.namespaces.net_namespace_available

    def mount_namespace_available(self):
        return self.namespaces.mount_namespace_available

    def pid_namespace_available(self):
        return self.namespaces.pid_namespace_available

    def user_namespace_available(self):
        return self.namespaces.user_namespace_available

    def uts_namespace_available(self):
        return self.namespaces.uts_namespace_available

    def mount(self, source=None, target=None, mount_type=None,
              filesystemtype=None, data=None):
        if not [arg for arg in [source, target, filesystemtype, mount_type]
                if arg is not None]:
            return
        func_obj = self.functions["mount"]

        if source is None:
            source = "none"
        if target is None:
            target = ""
        if filesystemtype is None:
            filesystemtype = ""
        if mount_type is None:
            mount_type = "unchanged"
        if data is None:
            data = ""

        flag = func_obj.extra["flag"]
        propagation = func_obj.extra["propagation"]
        mount_flags = propagation[mount_type]
        mount_vals = [flag[k] for k in mount_flags]
        flags = reduce(lambda res, val: res | val, mount_vals, 0)

        self._c_func_mount(source, target, filesystemtype, flags, data)

    def _mount_proc(self, mountpoint="/proc"):
        self.mount(source="none", target=mountpoint, mount_type="private")
        self.mount(source="proc", target=mountpoint, filesystemtype="proc",
                   mount_type="mount_proc")

    def umount(self, mountpoint=None):
        if mountpoint is None:
            return
        if not is_string_or_unicode(mountpoint):
            raise RuntimeError("mountpoint should be a path to a mount point")
        if not os.path.exists(mountpoint):
            raise RuntimeError("mount point '%s': cannot found")
        self._c_func_umount(mountpoint)

    def umount2(self, mountpoint=None, behavior=None):
        func_obj = self.functions["umount2"]
        if mountpoint is None:
            return
        if not is_string_or_unicode(mountpoint):
            raise RuntimeError("mountpoint should be a path to a mount point")
        if not os.path.exists(mountpoint):
            raise RuntimeError("mount point '%s': cannot found")

        behaviors = func_obj.extra["behaviors"]
        flag = func_obj.extra["flag"]
        if behavior is None or behavior not in behaviors.keys():
            raise RuntimeError("behavior should be one of [%s]"
                               % ", ".join(func_obj.behaviors.keys()))

        val = flag[behaviors[behavior]]
        self._c_func_umount2(mountpoint, c_int(val))

    def set_propagation(self, type=None):
        if type is None:
            return
        mount_func_obj = self.functions["mount"]
        propagation = mount_func_obj.extra["propagation"]
        if type not in propagation.keys():
            raise RuntimeError("%s: unknown propagation type" % type)
        if type == "unchanged":
            return
        self.mount(source="none", target="/", mount_type=type)

    def unshare(self, namespaces=None):
        if namespaces is None:
            return

        target_flags = []
        for ns_name in namespaces:
            ns_obj = self.get_namespace(ns_name)
            if ns_obj.available:
                target_flags.append(ns_obj.value)

        flags = reduce(lambda res, flag: res | flag, target_flags, 0)
        self._c_func_unshare(flags)

    def setns(self, **kwargs):
        """
        workbench.setns(path=path2ns, namespace=namespace)

        E.g., setns(pid=1234, namespace="pid")
        """
        keys = ["fd", "path", "pid", "file_obj"]
        wrong_keys = [k for k in keys if k in kwargs.keys()]
        if len(wrong_keys) != 1:
            raise TypeError("complicating named argument found: %s"
                            % ", ".join(wrong_keys))

        _kwargs = deepcopy(kwargs)
        namespace = 0
        if  "namespace" in kwargs:
            ns = kwargs["namespace"]
            if is_string_or_unicode(ns) and ns in self.namespaces.namespaces:
                namespace = self.get_namespace(ns)
            else:
                raise UnknownNamespaceFound([ns])

        _kwargs["namespace"] = namespace.value

        if "fd" in kwargs:
            fd = kwargs["fd"]
            if not isinstance(fd, int):
                raise TypeError("unavailable file descriptor found")
        elif "path" in kwargs:
            path = os.path.abspath(kwargs["path"])
            entry = os.path.basename(path)
            if "namespace" in kwargs:
                ns = kwargs["namespace"]
                ns_obj = self.get_namespace(ns)
                ns_obj_entry = ns_obj.entry
                if entry != ns_obj_entry:
                    raise TypeError("complicating path and namespace args found")
            if not os.path.exists(path):
                raise TypeError("%s not existed" % path)

            fo = open(path, 'r')
            _kwargs["file_obj"] = fo
            _kwargs["fd"] = fo.fileno()
            _kwargs["path"] = path
        elif "pid" in kwargs:
            pid = kwargs["pid"]
            if namespace == 0:
                raise TypeError("pid named argument need a namespace")
            if not isinstance(pid, int):
                raise TypeError("unknown pid found")
            ns = kwargs["namespace"]
            ns_obj = self.get_namespace(ns)
            entry = ns_obj.entry
            path = "/proc/%d/ns/%s" % (pid, entry)
            if os.path.exists(path):
                fo = open(path, 'r')
                _kwargs["file_obj"] = fo
                _kwargs["fd"] = fo.fileno()
        elif "file_obj" in kwargs:
            fo = kwargs["file_obj"]
            _kwargs["fd"] = fo.fileno()

        flags = c_int(_kwargs["namespace"])
        fd = c_int(_kwargs["fd"])
        if self.functions["setns"].func is None:
            try:
                NR_SETNS = self._syscall_nr("setns")
            except CFunctionUnknowSyscall as e:
                raise CFunctionNotFound()
            else:
                return self._c_func_syscall(c_long(NR_SETNS), fd, flags)
        else:
            return self._c_func_setns(fd, flags)

    def gethostname(self):
        buf_len = _HOST_NAME_MAX
        buf = create_string_buffer(buf_len)
        self._c_func_gethostname(buf, c_size_t(buf_len))
        return _to_str(string_at(buf))

    def sethostname(self, hostname=None):
        if hostname is None:
            return
        buf_len = c_size_t(len(hostname))
        buf = create_string_buffer(hostname)
        return self._c_func_sethostname(buf, buf_len)

    def getdomainname(self):
        """
        Note that this function will return string '(none)' if returned domain name is empty.
        """
        buf_len = _HOST_NAME_MAX
        buf = create_string_buffer(buf_len)
        self._c_func_getdomainname(buf, c_size_t(buf_len))
        return _to_str(string_at(buf))

    def setdomainname(self, domainname=None):
        if domainname is None:
            return
        buf_len = c_size_t(len(domainname))
        buf = create_string_buffer(domainname)
        return self._c_func_setdomainname(buf, buf_len)

    def pivot_root(self, new_root, put_old):
        if not is_string_or_unicode(new_root):
            raise RuntimeError("new_root argument is not an available path")
        if not is_string_or_unicode(put_old):
            raise RuntimeError("put_old argument is not an available path")
        if not os.path.exists(new_root):
            raise RuntimeError("%s: no such directory" % new_root)
        if not os.path.exists(put_old):
            raise RuntimeError("%s: no such directory" % put_old)

        try:
            NR_PIVOT_ROOT = self._syscall_nr("pivot_root")
        except CFunctionUnknowSyscall:
            raise CFunctionNotFound()
        else:
            return self._c_func_syscall(c_long(NR_PIVOT_ROOT),
                                            new_root, put_old)

    def adjust_namespaces(self, namespaces=None, negative_namespaces=None):
        self.check_namespaces_available_status()
        available_namespaces = []
        for ns_name in self.namespaces.namespaces:
            ns_obj = self.get_namespace(ns_name)
            if ns_obj.available:
                available_namespaces.append(ns_name)

        if namespaces is None:
            namespaces = available_namespaces

        unavailable_namespaces = [ns for ns in namespaces
                                  if ns not in self.namespaces.namespaces]
        if unavailable_namespaces:
            raise UnknownNamespaceFound(namespaces=unavailable_namespaces)

        if negative_namespaces:
            for ns in negative_namespaces:
                if ns in namespaces: namespaces.remove(ns)

        return namespaces

    def setgroups_control(self, setgroups=None, pid=None):
        if setgroups is None:
            return
        if pid is None:
            pid = "self"
        else:
            pid = "%d" % pid
        path = "/proc/%s/setgroups" % pid
        if not os.path.exists(path):
            if setgroups == "deny":
                raise NamespaceSettingError("cannot set setgroups to 'deny'")
            else:
                return

        ctrl_keys = self.namespaces.user.extra
        if setgroups not in ctrl_keys:
            raise RuntimeError("group control should be %s"
                               % ", ".join(ctrl_keys))
        hdr = open(path, 'r')
        line = hdr.read(16)
        old_setgroups = line.rstrip("\n")
        if old_setgroups == setgroups:
            return
        hdr.close()

        if os.path.exists(path):
            _write2file(path, setgroups)

    def get_namespace(self, name):
        if name is None:
            name="pid"
        return getattr(self.namespaces, name)

    def show_namespaces_status(self):
        status = []
        self.check_namespaces_available_status()
        namespaces = self.namespaces.namespaces
        for ns_name in namespaces:
            ns_obj = self.get_namespace(ns_name)
            status.append((ns_name, ns_obj.available))
        return status

    def bind_ns_files(self, pid, namespaces=None, ns_bind_dir=None):
        if ns_bind_dir is None or namespaces is None:
            return

        if not os.path.exists(ns_bind_dir):
            os.mkdir(ns_bind_dir)

        if not os.access(ns_bind_dir, os.R_OK | os.W_OK):
            raise RuntimeError("cannot access %s" % bind_ns_dir)

        path = "/proc/%d/ns" % pid
        for ns in namespaces:
            if ns == "mount": continue
            ns_obj = self.get_namespace(ns)
            if not ns_obj.available: continue
            entry = ns_obj.entry
            source = "%s/%s" % (path, entry)
            target = "%s/%s" % (ns_bind_dir.rstrip("/"), entry)
            if not os.path.exists(target):
                os.close(os.open(target, os.O_CREAT | os.O_RDWR))
            self.mount(source=source, target=target, mount_type="bind")

    def _run_cmd_in_new_namespaces(
            self, r1, w1, r2, w2, namespaces, mountproc, mountpoint,
            nscmd=None, propagation=None, init_prog=None, func=None):
        os.close(r1)
        os.close(w2)

        if namespaces is None:
            return

        self.unshare(namespaces)

        r3, w3 = os.pipe()
        r4, w4 = os.pipe()
        pid = _fork()

        if pid == 0:
            os.close(w1)
            os.close(r2)

            os.close(r3)
            os.close(w4)

            if "mount" in namespaces and propagation is not None:
                self.set_propagation(propagation)
            if mountproc:
                self._mount_proc(mountpoint=mountpoint)

            os.write(w3, to_bytes(chr(_ACLCHAR)))
            os.close(w3)

            if ord(os.read(r4, 1)) != _ACLCHAR:
                raise "sync failed"
            os.close(r4)

            if func is None:
                if nscmd is None:
                    nscmd = _find_shell()

                if init_prog is None:
                    try:
                        my_init = self.my_init
                    except IOError as e:
                        printf(e)
                        sys.exit(1)
                    except NamespaceSettingError as e:
                        printf(e)
                        sys.exit(1)
                    else:
                        args = ["-c", my_init, "--skip-startup-files",
                            "--skip-runit", "--quiet"]

                    if isinstance(nscmd, list):
                        args = args + nscmd
                    else:
                        args.append(nscmd)

                    if "pid" in namespaces:
                        init_prog = "python"
                    else:
                        init_prog = nscmd
                        args = [nscmd]
                else:
                    if "pid" in namespaces:
                        args = [nscmd]
                    else:
                        init_prog = nscmd
                        args = [nscmd]
                os.execlp(init_prog, *args)
            else:
                if hasattr(func, '__call__'):
                    func()
                else:
                    raise NamespaceSettingError()
            sys.exit(0)
        else:
            os.close(w3)
            os.close(r4)

            if ord(os.read(r3, 1)) != _ACLCHAR:
                raise "sync failed"
            os.close(r3)

            os.write(w1, to_bytes("%d" % pid))
            os.close(w1)

            if ord(os.read(r2, 1)) != _ACLCHAR:
                raise "sync failed"
            os.close(r2)

            os.write(w4, to_bytes(chr(_ACLCHAR)))
            os.close(w4)

            os.waitpid(pid, 0)
            sys.exit(0)

    def _continue_original_flow(
            self, r1, w1, r2, w2, namespaces, ns_bind_dir,
            setgroups, maproot, users_map, groups_map):
        if setgroups == "allow" and maproot:
            raise NamespaceSettingError()

        if maproot:
            uid = os.geteuid()
            gid = os.getegid()

        os.close(w1)
        os.close(r2)

        child_pid = os.read(r1, 64)
        os.close(r1)
        try:
            child_pid = int(child_pid)
        except ValueError:
            raise RuntimeError("failed to get the child pid")

        if "user" in namespaces:
            self.setgroups_control(setgroups, child_pid)
            _write_to_uid_and_gid_map(maproot, users_map,
                                          groups_map, child_pid)

        if ns_bind_dir is not None and "mount" in namespaces:
            self.bind_ns_files(child_pid, namespaces, ns_bind_dir)
        os.write(w2, to_bytes(chr(_ACLCHAR)))
        os.close(w2)
        return child_pid

    def _namespace_available(self, namespace):
        ns_obj = self.get_namespace( namespace)
        return ns_obj.available

    def _fix_spawn_options(self, namespaces, maproot, mountproc, mountpoint,
                               ns_bind_dir, propagation, negative_namespaces,
                               setgroups, users_map, groups_map):
        self.check_namespaces_available_status()
        if not self.user_namespace_available():
            maproot = False
            users_map = None
            group_map = None
        if setgroups == "allow" and maproot:
            maproot = False
            users_map = None
            group_map = None
        if not self.pid_namespace_available():
            mountproc = False
            mountpoint = None
        if mountproc and mountpoint is None:
            mountpoint = '/proc'
        if not self.mount_namespace_available():
            propagation = None
        if setgroups == "allow" and maproot:
            raise NamespaceSettingError()

        namespaces = self.adjust_namespaces(namespaces, negative_namespaces)

        all_namespaces = self.namespaces.namespaces
        unsupported_namespaces = []
        for ns in namespaces:
            if ns not in all_namespaces:
                unsupported_namespaces.append(ns)
            elif not self._namespace_available(ns):
                unsupported_namespaces.append(ns)
        if unsupported_namespaces:
            raise UnavailableNamespaceFound(unsupported_namespaces)

        if _need_super_user_privilege(namespaces, ns_bind_dir,
                                          users_map, groups_map):
            euid = os.geteuid()
            if euid != 0:
                raise NamespaceRequireSuperuserPrivilege()

        if mountproc:
            if self.mount_namespace_available():
                if "mount" not in namespaces:
                    namespaces.append("mount")
            else:
                raise NamespaceSettingError()

        if maproot:
            if self.user_namespace_available():
                if "user" not in namespaces:
                    namespaces.append("user")
            else:
                raise NamespaceSettingError()

        if mount_namespace_available():
            if "mount" in namespaces and propagation is None:
                propagation = "private"

        path = "/proc/self/setgroups"
        if self.user_namespace_available and "user" in namespaces:
            if os.path.exists(path):
                if setgroups is None:
                    setgroups = "deny"
            elif setgroups == "allow":
                pass
            else:
                setgroups = None
        else:
            setgroups = None

        if "user" not in namespaces:
            maproot = False
            setgroups = None
            users_map = None
            groups_map = None

        if "pid" not in namespaces:
            mountproc = False

        if "mount" not in namespaces:
             ns_bind_dir = None
             propagation = None
             mountproc = False

        return (namespaces, maproot, mountproc, mountpoint,
                    ns_bind_dir, propagation, negative_namespaces,
                    setgroups, users_map, groups_map)

    def spawn_namespaces(self, namespaces=None, maproot=True, mountproc=True,
                             mountpoint=None, ns_bind_dir=None, nscmd=None,
                             propagation=None, negative_namespaces=None,
                             setgroups=None, users_map=None, groups_map=None,
                             init_prog=None, func=None):
        """
        workbench.spawn_namespace(namespaces=["pid", "net", "mount"])
        """

        if (init_prog is not None or nscmd is not None) and func is not None:
            raise NamespaceSettingError()
        origin_args = _copy_args(namespaces, maproot, mountproc, mountpoint,
                                     ns_bind_dir, nscmd, propagation,
                                     negative_namespaces, setgroups, users_map,
                                     groups_map, init_prog, func)

        (namespaces, maproot, mountproc, mountpoint,
             ns_bind_dir, propagation, negative_namespaces,
             setgroups, users_map, groups_map
        ) = self._fix_spawn_options(
            namespaces, maproot, mountproc, mountpoint,
            ns_bind_dir, propagation, negative_namespaces,
            setgroups, users_map, groups_map)

        r1, w1 = os.pipe()
        r2, w2 = os.pipe()
        pid = _fork()

        if pid == 0:
            self._run_cmd_in_new_namespaces(
                r1, w1, r2, w2, namespaces, mountproc, mountpoint,
                nscmd, propagation, init_prog, func)
        else:
            child_pid = self._continue_original_flow(
                r1, w1, r2, w2, namespaces, ns_bind_dir,
                setgroups, maproot, users_map, groups_map)
            def ensure_wait_child_process(pid=pid):
                try:
                    os.waitpid(pid, 0)
                except OSError:
                    pass
            atexit.register(ensure_wait_child_process)

            last_args = _copy_args(namespaces, maproot, mountproc, mountpoint,
                                     ns_bind_dir, nscmd, propagation,
                                     negative_namespaces, setgroups, users_map,
                                     groups_map, init_prog, func)
            return {'pid': pid,
                        'child_pid': child_pid,
                        'origin_args': origin_args,
                        'last_args': last_args}

class CFunctionBaseException(Exception):
    pass

class CFunctionCallFailed(CFunctionBaseException):
    pass

class CFunctionNotFound(CFunctionBaseException):
    pass

class CFunctionUnknowSyscall(CFunctionNotFound):
    pass

workbench = Workbench()
del Workbench

def atfork(prepare=None, parent=None, child=None):
    return workbench.atfork(prepare, parent, child)

def sched_getcpu():
    return workbench.sched_getcpu()

def cgroup_namespace_available():
    return workbench.cgroup_namespace_available()

def ipc_namespace_available():
    return workbench.ipc_namespace_available()

def net_namespace_available():
    return workbench.net_namespace_available()

def mount_namespace_available():
    return workbench.mount_namespace_available()

def pid_namespace_available():
    return workbench.pid_namespace_available()

def user_namespace_available():
    return workbench.user_namespace_available()

def uts_namespace_available():
    return workbench.uts_namespace_available()

def mount(source=None, target=None, mount_type=None,
              filesystemtype=None, data=None):
    return workbench.mount(source, target, mount_type,
                               filesystemtype, data)

def umount(mountpoint=None):
    return workbench.umount(mountpoint)

def umount2(mountpoint=None, behavior=None):
    return workbench.umount2(mountpoint, behavior)

def unshare(namespaces=None):
    return workbench.unshare(namespaces)

def setns(**kwargs):
    """
    setns(fd, namespace)
    setns(path, namespace)
    setns(pid, namespace)
    setns(file_obj, namespace)
    """
    return workbench.setns(**kwargs)

def gethostname():
    return workbench.gethostname()

def sethostname(hostname=None):
    return workbench.sethostname(hostname)

def getdomainname():
    return workbench.getdomainname()

def setdomainname(domainname=None):
    return workbench.setdomainname(domainname)

def pivot_root(new_root, put_old):
    return workbench.pivot_root(new_root, put_old)

def adjust_namespaces(namespaces=None, negative_namespaces=None):
    return workbench.adjust_namespaces(namespaces, negative_namespaces)

def spawn_namespaces(namespaces=None, maproot=True, mountproc=True,
                         mountpoint="/proc", ns_bind_dir=None, nscmd=None,
                         propagation=None, negative_namespaces=None,
                         setgroups=None, users_map=None, groups_map=None,
                         init_prog=None, func=None):
    return workbench.spawn_namespaces(
        namespaces=namespaces, maproot=maproot, mountproc=mountproc,
        mountpoint=mountpoint, ns_bind_dir=ns_bind_dir, nscmd=nscmd,
        propagation=propagation, negative_namespaces=negative_namespaces,
        setgroups=setgroups, users_map=users_map, groups_map=groups_map,
        init_prog=init_prog, func=func)

def check_namespaces_available_status():
    return workbench.check_namespaces_available_status()

def get_namespace(name=None):
    return workbench.get_namespace(name)
def show_namespaces_status():
    return workbench.show_namespaces_status()

def show_available_c_functions():
    return workbench.show_available_c_functions()

def unregister_fork_handlers(prepare=None, parent=None,
                                 child=None, strict=False):
    return workbench.unregister_fork_handlers(prepare, parent, child, strict)

if __name__ == "__main__":
    try:
        spawn_namespaces()
    except NamespaceRequireSuperuserPrivilege():
        printf(e)
        sys.exit(1)
