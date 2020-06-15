import os

if os.uname()[0] != "Linux":
    raise ImportError("only support Linux platform")

import sys
import resource
import re
from ctypes import (cdll, c_int, c_long, c_char_p, c_size_t, string_at,
                    create_string_buffer, POINTER, c_void_p, CFUNCTYPE,
                    pythonapi)
import pwd
import grp
import errno

try:
    from functools import reduce
except ImportError:
    pass

import pickle
from copy import copy, deepcopy
import json

from procszoo.utils import *
from procszoo.namespaces import *
try:
    from procszoo.version import PROCSZOO_VERSION
    from procszoo.c_functions.macros import *
    from procszoo.c_functions.atfork import atfork as c_atfork
except ImportError:
    printf('seems you do not install/build procszoo completely')
    raise SystemExit()
from procszoo.scripts import my_init

__version__ = PROCSZOO_VERSION
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
    "get_available_propagations", "__version__", "find_shell",
    "get_current_users_and_groups", "getresuid", "getresgid",
    "setresuid", "setresgid", "SpawnNamespacesConfig"]

_HOST_NAME_MAX = 256
_CDLL = cdll.LoadLibrary(None)
_ACKCHAR = 0x006
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

def _covert_map_to_tuple(_map, map_type=None):
    if map_type is None:
        map_type = 'user'

    if map_type not in ['group', 'user']:
        raise RuntimeError()

    _list = [v for v in _map.expandtabs().split(' ') if v != ' ']

    if len(_list) < 2 or len(_list) > 3:
        raise NamespaceSettingError()

    if len(_list) == 2:
        _range = 1
    else:
        try:
            _range = int(_list[2])
        except ValueError:
            raise NamespaceSettingError()

    if map_type == 'user':
        inter_id = get_uid_from_name_or_uid(_list[0])
        outer_id = get_uid_from_name_or_uid(_list[1])
    elif map_type == 'group':
        inter_id = get_gid_from_name_or_gid(_list[0])
        outer_id = get_gid_from_name_or_gid(_list[1])

    return tuple([inter_id, outer_id, _range])


def _accetable_user_map(user_map):
    if not user_map:
        return False

    ruid, euid, suid = getresuid()

    inter_id, outer_id, _range = _covert_map_to_tuple(user_map, 'user')

    if i_am_not_superuser():
        _id = outer_id
        _max_id = outer_id + _range
        if _range > 3:
            return False
        while _id < _max_id:
            if _id not in [ruid, euid, suid]:
                return False
            _id += 1

    return True


def _accetable_group_map(group_map):
    if not group_map:
        return False

    rgid, egid, sgid = getresgid()

    inter_id, outer_id, _range = _covert_map_to_tuple(group_map, 'group')

    if i_am_not_superuser():
        _id = outer_id
        _max_id = outer_id + _range
        if _range > 3:
            return False
        while _id < _max_id:
            if _id not in [rgid, egid, sgid]:
                return False
            _id += 1

    return True


def _write_to_uid_and_gid_map(maproot, users_map, groups_map, pid):
    if maproot is None:
        return

    if users_map is None:
        _maps = ["0 %d 1" % os.geteuid()]
    else:
        _maps = users_map

    if _maps:
        if len(_maps) > _MAX_USERS_MAP:
            raise NamespaceSettingError()
        map_str = "%s\n" % "\n".join(_maps)
        try:
            _map_id("uid_map", map_str, pid)
        except IOError:
            raise NamespaceRequireSuperuserPrivilege()

    if groups_map is None:
        _maps = ["0 %d 1" % os.getegid()]
    else:
        _maps = groups_map

    if _maps:
        if len(_maps) > _MAX_GROUPS_MAP:
            raise NamespaceSettingError()
        map_str = "%s\n" % "\n".join(_maps)
        try:
            _map_id("gid_map", map_str, pid)
        except IOError:
            raise NamespaceRequireSuperuserPrivilege()

def _review_sync_signal(r, size=1):
    _signal = os.read(r, size)
    if len(_signal) == 0 and is_string_or_unicode(_signal):
        raise SystemExit
    elif len(_signal) <= size:
        return _signal
    else:
        raise RuntimeError('sync failed')

class SpawnNamespacesConfig(object):
    def __init__(self, namespaces=None, maproot=True, mountproc=True,
                mountpoint=None, ns_bind_dir=None, nscmd=None,
                propagation=None, negative_namespaces=None,
                setgroups=None, users_map=None, groups_map=None,
                init_prog=None, func=None,
                interactive=None,
                strict=None,
                extra=None,
                pid=None,
                top_halves_child_pid=None,
                bottom_halves_child_pid=None,
                parse_conf=None,
                top_halves_before_fork=None,
                top_halves_before_sync=None,
                top_halves_half_sync=None,
                top_halves_after_sync=None,
                top_halves_before_exit=None,
                bottom_halves_before_fork=None,
                bottom_halves_before_sync=None,
                bottom_halves_half_sync=None,
                bottom_halves_after_sync=None,
                bottom_halves_before_main=None,
                bottom_halves_main=None,
                bottom_halves_before_exit=None,
                top_halves_entry_point=None,
                bottom_halves_entry_point=None,
                     entry_point=None):
        if namespaces is None:
            self.namespaces = adjust_namespaces()
        else:
            self.namespaces = namespaces
        self.maproot = maproot
        self.mountproc = mountproc
        if mountpoint is None:
            self.mountpoint = '/proc'
        else:
            self.mountpoint = mountpoint
        self.ns_bind_dir = ns_bind_dir
        self.nscmd = nscmd
        self.propagation = propagation
        self.negative_namespaces = negative_namespaces
        self.setgroups = setgroups
        if setgroups is not None and setgroups not in ['allow', 'deny']:
            raise NamespaceSettingError()
        self.users_map = users_map
        self.groups_map = groups_map
        self.init_prog = init_prog
        self.func = func
        if interactive is None:
            self.interactive = True
        else:
            self.interactive=interactive
        if strict is None:
            self.strict = True
        else:
            self.strict = strict

        self.extra = extra

        if pid is None:
            self.pid = os.getpid()
        else:
            self.pid = pid
        self.top_halves_child_pid = top_halves_child_pid
        self.bottom_halves_child_pid = bottom_halves_child_pid

        if parse_conf is None:
            self.parse_conf = self.default_handler_to_parse_conf
        elif not callable(parse_conf):
            raise NamespaceSettingError('handler must be a callable')
        else:
            setattr(self, 'parse_conf', parse_conf)

        if top_halves_before_fork is None:
            self.top_halves_before_fork = self.default_top_halves_before_fork
        elif not callable(top_halves_before_fork):
            raise NamespaceSettingError('handler must be a callable')
        else:
            setattr(self, 'top_halves_before_fork', top_halves_before_fork)

        if top_halves_before_sync is None:
            self.top_halves_before_sync = self.default_top_halves_before_sync
        elif not callable(top_halves_before_sync):
            raise NamespaceSettingError('handler must be a callable')
        else:
            setattr(self, 'top_halves_before_sync', top_halves_before_sync)

        if top_halves_half_sync is None:
            self.top_halves_half_sync = self.default_top_halves_half_sync
        elif not callable(top_halves_half_sync):
            raise NamespaceSettingError('handler must be a callable')
        else:
            setattr(self, 'top_halves_half_sync', top_halves_half_sync)

        if top_halves_after_sync is None:
            self.top_halves_after_sync = self.default_top_halves_after_sync
        elif not callable(top_halves_after_sync):
            raise NamespaceSettingError('handler must be a callable')
        else:
            setattr(self, 'top_halves_after_sync', top_halves_after_sync)

        if top_halves_before_exit is None:
            self.top_halves_before_exit = self.default_top_halves_before_exit
        elif not callable(top_halves_before_exit):
            raise NamespaceSettingError('handler must be a callable')
        else:
            setattr(self, 'top_halves_before_exit', top_halves_before_exit)

        if bottom_halves_before_fork is None:
            self.bottom_halves_before_fork = (
                self.default_bottom_halves_before_fork)
        elif not callable(bottom_halves_before_fork):
            raise NamespaceSettingError('handler must be a callable')
        else:
            setattr(self, 'bottom_halves_before_fork',
                        bottom_halves_before_fork)

        if bottom_halves_before_sync is None:
            self.bottom_halves_before_sync = (
                self.default_bottom_halves_before_sync)
        elif not callable(bottom_halves_before_sync):
            raise NamespaceSettingError('handler must be a callable')
        else:
            setattr(self, 'bottom_halves_before_sync',
                        bottom_halves_before_sync)

        if bottom_halves_half_sync is None:
            self.bottom_halves_half_sync = self.default_bottom_halves_half_sync
        elif not callable(bottom_halves_half_sync):
            raise NamespaceSettingError('handler must be a callable')
        else:
            setattr(self, 'bottom_halves_half_sync', bottom_halves_half_sync)

        if bottom_halves_after_sync is None:
            self.bottom_halves_after_sync = (
                self.default_bottom_halves_after_sync)
        elif not callable(bottom_halves_after_sync):
            raise NamespaceSettingError('handler must be a callable')
        else:
            setattr(self, 'bottom_halves_after_sync', bottom_halves_after_sync)

        if bottom_halves_before_main is None:
            self.bottom_halves_before_main = (
                self.default_bottom_halves_before_main)
        elif not callable(bottom_halves_before_main):
            raise NamespaceSettingError('handler must be a callable')
        else:
            setattr(self, 'bottom_halves_before_main',
                        bottom_halves_before_main)

        if bottom_halves_main is None:
            self.bottom_halves_main = (self.default_bottom_halves_main)
        elif not callable(bottom_halves_main):
            raise NamespaceSettingError('handler must be a callable')
        else:
            setattr(self, 'bottom_halves_main', bottom_halves_main)

        if bottom_halves_before_exit is None:
            self.bottom_halves_before_exit = (
                self.default_bottom_halves_before_exit)
        elif not callable(bottom_halves_before_exit):
            raise NamespaceSettingError('handler must be a callable')
        else:
            setattr(self, 'bottom_halves_before_exit', bottom_halves_before_exit)

        if top_halves_entry_point is None:
            self.top_halves_entry_point = self.default_top_halves_entry_point
        elif not callable(top_halves_entry_point):
            raise NamespaceSettingError('handler must be a callable')
        else:
            setattr(self, 'top_halves_entry_point', top_halves_entry_point)

        if bottom_halves_entry_point is None:
            self.bottom_halves_entry_point = (
                self.default_bottom_halves_entry_point)
        elif not callable(bottom_halves_entry_point):
            raise NamespaceSettingError('handler must be a callable')
        else:
            setattr(self, 'bottom_halves_entry_point',
                        bottom_halves_entry_point)

        if entry_point is None:
            self.entry_point = self.default_entry_point
        elif not callable(entry_point):
            raise NamespaceSettingError('handler must be a callable')
        else:
            setattr(self, 'entry_point', entry_point)

    def __getattr__(self, name):
        if name.startswith('default_'):
            return self.default_null_handler

    def default_entry_point(self, *args, **kwargs):
        self.parse_conf(*args, **kwargs)

        r1, w1 = os.pipe()
        r2, w2 = os.pipe()

        self.top_halves_before_fork(*args, **kwargs)

        pid = _fork()

        if pid == 0:
            self.bottom_halves_entry_point(r1, w1, r2, w2, *args, **kwargs)
            sys.exit(0)
        elif pid > 0:
            self.top_halves_child_pid = pid
            self.top_halves_entry_point(r1, w1, r2, w2, *args, **kwargs)
        else:
            sys.exit(0)

    def default_top_halves_entry_point(self, r1, w1, r2, w2, *args, **kwargs):

        self.top_halves_before_sync(*args, **kwargs)

        os.close(w1)
        os.close(r2)

        _info_by_signal = _review_sync_signal(r1, 64)
        os.close(r1)
        try:
            child_pid = int(_info_by_signal)
        except ValueError:
            raise RuntimeError("failed to get the child pid")

        self.bottom_halves_child_pid = child_pid

        self.top_halves_half_sync(*args, **kwargs)

        os.write(w2, to_bytes(chr(_ACKCHAR)))
        os.close(w2)

        self.top_halves_after_sync(*args, **kwargs)

        if self.interactive:
            os.waitpid(self.top_halves_child_pid, 0)
            self.top_halves_before_exit(*args, **kwargs)
        else:
            self.top_halves_before_exit(*args, **kwargs)

        sys.exit(0)

    def default_bottom_halves_entry_point(self, r1, w1, r2, w2,
                                               *args, **kwargs):
        os.close(r1)
        os.close(w2)

        self.bottom_halves_before_fork(*args, **kwargs)

        r3, w3 = os.pipe()
        r4, w4 = os.pipe()
        pid = _fork()

        if pid == 0:
            if not self.interactive:
                process_id = os.setsid()
                if process_id == -1:
                    sys.exit(1)

            os.close(w1)
            os.close(r2)

            os.close(r3)
            os.close(w4)

            self.bottom_halves_before_sync(*args, **kwargs)

            os.write(w3, to_bytes(chr(_ACKCHAR)))
            os.close(w3)

            self.bottom_halves_half_sync(*args, **kwargs)

            sync_signal = _review_sync_signal(r4)
            if ord(sync_signal) != _ACKCHAR:
                raise RuntimeError('sync failed')
            os.close(r4)

            if not self.interactive:
                devnull = "/dev/null"
                if hasattr(os, "devnull"):
                    devnull = os.devnull

                for fd in range(
                        3, resource.getrlimit(resource.RLIMIT_NOFILE)[0]):
                    try:
                        os.close(fd)
                    except OSError:
                        pass

                os.chdir('/')
                devnull_fd = os.open(devnull, os.O_RDWR)
                os.dup2(devnull_fd, 0)
                os.dup2(devnull_fd, 1)
                os.dup2(devnull_fd, 2)
                os.close(devnull_fd)
                os.umask(0)

            self.bottom_halves_after_sync(*args, **kwargs)

            sys.exit(0)
        else:

            os.close(w3)
            os.close(r4)

            sync_signal = _review_sync_signal(r3)
            if ord(sync_signal) != _ACKCHAR:
                raise RuntimeError('sync failed')
            os.close(r3)

            os.write(w1, to_bytes("%d" % pid))
            os.close(w1)

            sync_signal = _review_sync_signal(r2)
            if ord(sync_signal) != _ACKCHAR:
                raise RuntimeError('sync failed')
            os.close(r2)

            os.write(w4, to_bytes(chr(_ACKCHAR)))
            os.close(w4)

            if self.interactive:
                os.waitpid(pid, 0)
            else:
                sys.exit(0)


    def default_handler_to_parse_conf(self):
        if self.init_prog is not None or self.nscmd is not None:
            if self.func is not None:
                raise NamespaceSettingError()

        check_namespaces_available_status()
        if not user_namespace_available():
            if self.strict:
                if (self.maproot or self.users_map or self.groups_map):
                    raise NamespaceSettingError(
                        'cannot do users/groups mapping')
            else:
                self.maproot = False
                self.users_map = None
                self.group_map = None
        if self.setgroups == "allow" and (
                self.maproot or self.users_map or self.groups_map):
            if self.strict:
                raise NamespaceSettingError(
                    'setgroups and users/groups mapping conflict')
            else:
                self.maproot = False
                self.users_map = None
                self.group_map = None
        if not pid_namespace_available():
            if self.strict and self.mountproc:
                raise NamespaceSettingError('cannot mount procfs')
            else:
                self.mountproc = False
                self.mountpoint = None
        if not mount_namespace_available():
            if self.strict and self.propagation is not None:
                raise NamespaceSettingError()
            else:
                self.propagation = None
        if self.setgroups == "allow" and (
                self.maproot or self.users_map or self.groups_map):
            raise NamespaceSettingError()

        self.namespaces = adjust_namespaces(self.namespaces,
                                                self.negative_namespaces)

        path = "/proc/self/setgroups"
        if not os.path.exists(path) and self.setgroups is not None:
            if self.setgroups != 'allow':
                raise NamespaceSettingError('do not support setgroups')

        if self.need_super_privilege():
            raise NamespaceRequireSuperuserPrivilege()

        if self.mountproc:
            if mount_namespace_available():
                if "mount" not in self.namespaces:
                    if self.strict:
                        raise NamespaceSettingError()
                    else:
                        self.namespaces.append("mount")
            else:
                raise NamespaceSettingError()

        if self.maproot:
            if user_namespace_available():
                if "user" not in self.namespaces:
                    if strict:
                        raise NamespaceSettingError()
                    else:
                        self.namespaces.append("user")
            else:
                raise NamespaceSettingError()

        if mount_namespace_available():
            if "mount" in self.namespaces and self.propagation is None:
                self.propagation = "private"

        path = "/proc/self/setgroups"
        if self.setgroups is None:
            if user_namespace_available() and "user" in self.namespaces:
                if self.maproot and os.path.exists(path):
                    self.setgroups = "deny"

        if "user" not in self.namespaces:
            self.maproot = False
            self.setgroups = None
            self.users_map = None
            self.groups_map = None

        if "pid" not in self.namespaces:
            self.mountproc = False

        if "mount" not in self.namespaces:
             self.ns_bind_dir = None
             self.propagation = None
             self.mountproc = False

        if self.users_map:
            _users_map = []
            for _map in self.users_map:
                inter_id, outer_id, _range = _covert_map_to_tuple(_map, 'user')
                _users_map.append('%d %d %d' % (inter_id, outer_id, _range))

            for _map in _users_map:
                if not _accetable_user_map(_map):
                    raise NamespaceRequireSuperuserPrivilege()
            self.users_map = _users_map

        if self.groups_map:
            _groups_map = []
            for _map in self.groups_map:
                inter_id, outer_id, _range = _covert_map_to_tuple(
                    _map, 'group')
                _groups_map.append('%d %d %d' % (inter_id, outer_id, _range))

            for _map in _groups_map:
                if not _accetable_group_map(_map):
                    raise NamespaceRequireSuperuserPrivilege()
            self.groups_map = _groups_map

        if self.maproot:
            if not self.users_map:
                self.users_map = ['0 %d 1' % os.geteuid()]
            if not self.groups_map:
                self.groups_map = ['0 %d 1' % os.getegid()]

    def need_super_privilege(self):
        require_root_privilege = False
        if not user_namespace_available():
            require_root_privilege = True
        if self.namespaces and "user" not in self.namespaces:
            require_root_privilege = True
        if self.ns_bind_dir:
            require_root_privilege = True
        if require_root_privilege:
            euid = os.geteuid()
            require_root_privilege = (euid != 0)
        return require_root_privilege

    def default_null_handler(self, *args, **kwargs):
        pass

    def default_bottom_halves_before_fork(self, *args, **kwargs):
        unshare(self.namespaces)

    def default_bottom_halves_before_sync(self, *args, **kwargs):
        if "mount" in self.namespaces and self.propagation is not None:
            workbench.set_propagation(self.propagation)
        if self.mountproc:
            workbench._mount_proc(mountpoint=self.mountpoint)

    def default_bottom_halves_main(self, *args, **kwargs):
        my_init.main(*args, **kwargs)

    def default_bottom_halves_before_exit(self, *args, **kwargs):
        my_init.kill_all_processes(*args, **kwargs)

    def default_bottom_halves_after_sync(self, *args, **kwargs):
        if self.func is None:
            if not self.nscmd:
                self.nscmd = [find_shell()]
            elif not isinstance(self.nscmd, list):
                self.nscmd = [self.nscmd]

            _args = None
            if "pid" not in self.namespaces:
                _args = self.nscmd
            elif self.init_prog is not None:
                _args = [self.init_prog] + self.nscmd

            self.bottom_halves_before_main(*args, **kwargs)
            if _args:
                os.execlp(args[0], *args)
            else:
                self.bottom_halves_main(
                    enable_insecure_key=False, skip_startup_files=True,
                    skip_runit=True, log_level=my_init.LOG_LEVEL_WARN,
                    main_command=self.nscmd, run_as_cli=False,
                    kill_all_on_exit=False)
                self.default_bottom_halves_before_exit(
                    my_init.KILL_ALL_PROCESSES_TIMEOUT)
        else:
            if callable(self.func):
                self.func(*args, **kwargs)
            else:
                raise NamespaceSettingError()

    def default_top_halves_before_sync(self, *args, **kwargs):
        if self.setgroups == "allow" and self.maproot:
            raise NamespaceSettingError()

    def default_top_halves_half_sync(self, *args, **kwargs):
        if "user" in self.namespaces:
            workbench.setgroups_control(self.setgroups,
                                            self.bottom_halves_child_pid)
            _write_to_uid_and_gid_map(
                self.maproot, self.users_map,
                self.groups_map, self.bottom_halves_child_pid)

        if self.ns_bind_dir is not None and "mount" in self.namespaces:
            workbench.bind_ns_files(self.bottom_halves_child_pid,
                                        self.namespaces, self.ns_bind_dir)


def _richard_trigger(**kwargs):
    SpawnNamespacesConfig(**kwargs).entry_point()


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
        self.functions = {}
        self.available_c_functions = []
        self.namespaces = Namespaces()
        self._init_c_functions()
        self._namespaces_available_status_checked = False
        self._spawn_namespaces_triggers = {}
        self.register_spawn_namespaces_trigger('default', _richard_trigger)

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
                    "unchanged": [],},
                "private_propagation": ['mount_proc', 'unchanged', 'bind'],
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
        self.functions[exported_name] = CFunction(
            exported_name=exported_name,
            argtypes=[c_char_p, c_size_t])

        #begin: python 2.6 need functions
        exported_name = 'getresuid'
        self.functions[exported_name] = CFunction(
            exported_name=exported_name,
            argtypes=[POINTER(c_int), POINTER(c_int), POINTER(c_int)])

        exported_name = 'getresgid'
        self.functions[exported_name] = CFunction(
            exported_name=exported_name,
            argtypes=[POINTER(c_int), POINTER(c_int), POINTER(c_int)])

        exported_name = 'setresuid'
        self.functions[exported_name] = CFunction(
            exported_name=exported_name,
            argtypes=[c_int, c_int, c_int])

        exported_name = 'setresgid'
        self.functions[exported_name] = CFunction(
            exported_name=exported_name,
            argtypes=[c_int, c_int, c_int])
        #end: python 2.6 need functions

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
                    if c_int_errno.value == errno.EPERM:
                        raise NamespaceRequireSuperuserPrivilege()
                    else:
                        raise CFunctionCallFailed(os.strerror(c_int_errno.value))
                return res

            return c_func_wrapper
        else:
            raise AttributeError("'CFunction' object has no attribute '%s'"
                                     % name)


    def register_spawn_namespaces_trigger(self, key, trigger, strict=None):
        if strict and key in self._spawn_namespaces_triggers:
            raise NamespaceSettingError('%s %s' %
                ('in strict mode you cannot register',
                     'an already registered trigger'))
        self._spawn_namespaces_triggers[key] = trigger


    def unregister_spawn_namespace_trigger(self, key):
        del self._spawn_namespaces_triggers[key]


    def trigger_spawn_namespaces(self, **kwargs):
        extra = None

        if 'extra' in kwargs:
            extra = kwargs['extra']

        if extra and isinstance(extra, dict) and 'trigger_key' in extra:
            key = extra['trigger_key']
        else:
            key = 'default'

        return (self._spawn_namespaces_triggers[key])(**kwargs)


    def get_available_propagations(self):
        func_obj = self.functions['mount']
        propagation = func_obj.extra['propagation']
        private_propagation = func_obj.extra['private_propagation']
        return [p for p in propagation.keys() if p not in private_propagation]

    def getresuid(self):
        try:
            os.getresuid
        except AttributeError:
            pass
        else:
            return os.getresuid()

        ruid = c_int()
        euid = c_int()
        suid = c_int()
        self._c_func_getresuid(ruid, euid, suid)

        return (ruid.value, euid.value, suid.value)

    def getresgid(self):
        try:
            os.getresgid
        except AttributeError:
            pass
        else:
            return os.getresgid()

        rgid = c_int()
        egid = c_int()
        sgid = c_int()
        self._c_func_getresgid(rgid, egid, sgid)

        return (rgid.value, egid.value, sgid.value)

    def setresuid(self, ruid, euid, suid):
        try:
            os.setresuid
        except AttributeError:
            pass
        else:
            return os.setresuid(ruid, euid, suid)

        return self._c_func_setresuid(ruid, euid, suid)

    def setresgid(self, rgid, egid, sgid):
        try:
            os.setresgid
        except AttributeError:
            pass
        else:
            return os.setresgid(rgid, egid, sgid)

        return self._c_func_setresgid(rgid, egid, sgid)

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
                        if _errno_c_int.value != errno.EINVAL:
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
        self.check_namespaces_available_status()
        return self.namespaces.cgroup_namespace_available

    def ipc_namespace_available(self):
        self.check_namespaces_available_status()
        return self.namespaces.ipc_namespace_available

    def net_namespace_available(self):
        self.check_namespaces_available_status()
        return self.namespaces.net_namespace_available

    def mount_namespace_available(self):
        self.check_namespaces_available_status()
        return self.namespaces.mount_namespace_available

    def pid_namespace_available(self):
        self.check_namespaces_available_status()
        return self.namespaces.pid_namespace_available

    def user_namespace_available(self):
        self.check_namespaces_available_status()
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
        hostname = to_bytes(hostname)
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
        domainname = to_bytes(domainname)
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


    def _namespace_available(self, namespace):
        ns_obj = self.get_namespace( namespace)
        return ns_obj.available


    def spawn_namespaces(self, **kwargs):
        """
        workbench.spawn_namespace(namespaces=["pid", "net", "mount"])
        """
        self.trigger_spawn_namespaces(**kwargs)


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

def get_available_propagations():
    return workbench.get_available_propagations()

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

def spawn_namespaces(**kwargs):
    return workbench.spawn_namespaces(**kwargs)

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


def getresuid():
    return workbench.getresuid()


def getresgid():
    return workbench.getresgid()


def setresuid(ruid, euid, suid):
    return workbench.setresuid(ruid, euid, suid)


def setresgid(rgid, egid, sgid):
    return workbench.setresgid(rgid, egid, sgid)


def get_current_users_and_groups(displayer=None):
    ruid, euid, suid = getresuid()
    rgid, egid, sgid = getresgid()
    supplementary_groups = os.getgroups()

    _supplementary_groups = []
    for _id in supplementary_groups:
        _name = get_name_by_gid(_id)
        _supplementary_groups.append({'name': _name, 'id': _id})

    return {
        'users': {
            'real user': {'name': get_name_by_uid(ruid), 'id': ruid},
            'effective user': {'name': get_name_by_uid(euid), 'id': euid},
            'saved user': {'name': get_name_by_uid(suid), 'id': suid},},
        'groups': {
            'real group': {'name': get_name_by_gid(rgid), 'id': rgid},
            'effective group': {'name': get_name_by_gid(rgid), 'id': rgid},
            'saved group': {'name': get_name_by_gid(rgid), 'id': rgid},},
        'supplementary_groups': _supplementary_groups,
        }


if __name__ == "__main__":
    try:
        spawn_namespaces()
    except NamespaceRequireSuperuserPrivilege():
        warn(e)
        sys.exit(1)
