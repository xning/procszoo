"""Export libc functions that operate Linux namespaces."""

import os
if os.uname()[0] != "Linux":
        raise ImportError("only support Linux platform")

import sys
import re
import json

from .exceptions import *

if os.uname()[0] != "Linux":
    raise ImportError("only support Linux platform")
__all__ = [
    "Namespace", "Namespaces", "NamespaceRequireSuperuserPrivilege",
    "NamespaceGenericException", "UnknownNamespaceFound",
    "UnavailableNamespaceFound", "NamespaceSettingError"]

_NAMESPACES = ["cgroup", "ipc", "net", "mount", "pid", "user", "uts"]

class Namespace(object):
    """
    Wrapper of namespace. You can check whether a namespace is available or
    not by workbench.is_namespace_name_available. E.g.,
    workbench.is_user_namespace_available. For namespaces name, pls
    reference namespaces(7). In the module, namespaces names are all
    lower-cases: user, net, mount, ipc, pid, uts.
    """
    def __init__(self, name, available=None, capabilities=None,
                     macro=None, value=0, entry=None, extra=None):
        self.name = name
        self.available = available
        self.capabilities=['CAP_SYS_ADMIN']
        if capabilities is not None:
            self.capabilities = capabilities
        self.macro = macro
        self.value = value
        self.entry = name.lower()
        if entry:
            self.entry = entry
        self.extra = extra
        self.init_available_status()

    def init_available_status(self):
        if self.available in [True, False]:
            return

        pid = os.getpid()
        path = "/proc/%d/ns/%s" % (pid, self.entry)
        if os.path.exists(path):
            self.available = True
        else:
            self.available = False

        if isinstance(self.available, bool):
            return

        kernel_config = "/boot/config-%s" % os.uname()[2]
        if os.path.exists(kernel_config):
            regex = re.compile('^CONFIG_%s_NS=(y|m)$' % self.entry.upper())
            hdr = open(kernel_config, 'r')
            for line in hdr:
                if regex.match(line):
                    if self.available is None:
                        self.available = True
                    break
            hdr.close()
        if self.available is None:
            self.available = False

    def __str__(self):
        return json.dumps({
            "name": self.name, "available": self.available,
            "capabilities": self.capabilities,
            "macro": self.macro, "macro value": self.value,
            "entry": "/proc/pid/ns/%s" % self.entry})

class Namespaces(object):
    def __init__(self):
        self.namespaces = _NAMESPACES
        self.init_namespaces()

    def init_namespaces(self):
        self.cgroup = Namespace(
            name="cgroup", macro='CLONE_CGROUP',
            value=0x02000000, entry='cgroup')

        self.ipc = Namespace(
            name="ipc", macro='CLONE_NEWIPC', value=0x08000000, entry='ipc')

        self.net = Namespace(
            name="net", macro='CLONE_NEWNET',
            value=0x40000000, entry="net")

        self.mount = Namespace(
            name="mount", entry="mnt", macro='CLONE_NEWNS',
            value=0x00020000, available=True)

        self.pid = Namespace(
            name="pid", macro='CLONE_NEWPID', value=0x20000000, entry='pid')

        self.user = Namespace(
            name="user", macro='CLONE_NEWUSER', value=0x10000000,
            entry='user', extra = ["allow", "deny"])

        self.uts = Namespace(
            name="uts", macro='CLONE_NEWUTS', value=0x04000000, entry='uts')

    def __str__(self):
        return json.dumps([json.loads(getattr(self, ns).__str__())
                               for ns in self.namespaces])

    def __getattr__(self, name):
        if name.endswith("_namespace_available"):
            ns_name = name.replace("_namespace_available", "")
            ns = getattr(self, ns_name)
            return ns.available
        elif name.startswith("get_") and name.endswith("_namespace"):
            ns_name = name.replace("get_", "")
            ns_name = ns_name.replace("_namespace")
            return getattr(self, ns_name)
        else:
            raise AttributeError("'Namespaces' object has no attribute '%s'"
                                     % name)
