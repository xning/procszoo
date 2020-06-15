'''
This module extends the richard_parker command line by add network
support.
'''
import os
import re
import tempfile
import random
from procszoo.c_functions import *
from procszoo.utils import *
from procszoo.network.exceptions import *
try:
    from procszoo.network import *
except (Pyroute2ModuleUnvailable, Pyroute2NetNSUnvailable) as e:
    printf(e)
    raise SystemExit('cannot support network function')

__all__ = ['build_extra']


def build_extra(args):
    extra = {}
    extra['trigger_key'] = 'richard+network'
    extra['dhcp'] = args.dhcp
    extra['interface'] = args.interface
    extra['network'] = args.network
    extra['nameservers'] = args.nameservers
    extra['hostname'] = args.hostname
    extra['bridge'] = args.bridge
    return extra


def _richard_parker_and_network(**kwargs):
    SpawnNSAndNetwork(**kwargs).entry_point()


class SpawnNSAndNetwork(SpawnNamespacesConfig):
    def __init__(self, **kwargs):
        super(SpawnNSAndNetwork, self).__init__(**kwargs)
        if 'net' in self.namespaces:
            self.netns_enable = True
        else:
            raise NamespaceSettingError(
                'net namespace is disabled or unavailable')

        self.dhcp = self.extra['dhcp']
        self.interface = self.extra['interface']
        self.network = self.extra['network']
        self.nameservers = self.extra['nameservers']
        self.hostname = self.extra['hostname']

        self.bridge = self.extra['bridge']

        if self.bridge and self.network == 'macvtap':
            raise NamespaceSettingError('macvtap do not need a bridge')

        if self.dhcp is None:
            if  get_all_oifindexes_of_default_route(wifi=False):
                self.dhcp = True
            else:
                self.dhcp = False

        self.tmpdir = tempfile.gettempdir()
        if self.netns_enable:
            self.netns_fmt = 'richard_parker%d'

            self._leases_dir = '/var/run'
            self._dhclient_pid_dir = '/var/run'
            self._resolv_conf_dir = self.tmpdir

            self.ifnames = []
            self.ifnames.append(self._if_name())
            if self.network == 'veth':
                self.ifnames.append(self._if_name())
            self.ifname = self.ifnames[0]

            if self.network == 'macvtap':
                self.ifname_to_ns = self.ifname
            elif self.network == 'veth':
                self.ifname_to_ns = self.ifnames[1]

            ifname = self.ifname
            self._leases = '%s/dhclient-%s.leases' % (self._leases_dir, ifname)
            self._dhclient_pid_file = '%s/dhclient-%s.pid' % (
                self._dhclient_pid_dir, ifname)
            self.resolv_conf = '%s/.%s' % (self._resolv_conf_dir, ifname)
            if self.bridge:
                if self.bridge not in get_all_ifnames() and not self.interface:
                    self.dhcp = False

        self.top_halves_before_fork = self._top_halves_before_fork
        self.top_halves_half_sync = self._top_halves_half_sync
        self.top_halves_before_exit = self._cleaner
        self.bottom_halves_after_sync = self._bottom_halves_after_sync

    def _if_name(self, ifname=None):
        _max_tries = 9999
        _max_if_count = 9999
        if ifname is not None:
            return ifname
        _ifnames = get_all_ifnames()
        for i in range(_max_tries):
            n = random.randint(0, _max_if_count)
            _if = '%s%d' % (self.extra['network'], n)
            if _if not in _ifnames:
                return _if

        raise SystemExit('failed to get a interface')

    def need_super_privilege(self):
        return os.geteuid() != 0

    def _top_halves_before_fork(self, *args, **kwargs):
        if not self.interface:
            if not get_all_oifnames_of_default_route(wifi=False):
                raise NamespaceSettingError(
                    'cannot determine a interface to create %s' %
                    self.network)
        self.default_top_halves_before_fork(*args, **kwargs)

    def _cleaner(self, *args, **kwargs):
        if not self.netns_enable:
            return

        for p in self._leases, self.resolv_conf, self._dhclient_pid_file:
            if os.path.exists(p):
                os.unlink(p)

        if self.need_up_ifnames:
            for _if in self.need_up_ifnames:
                if _if in get_all_ifnames():
                    down_if_by_name(_if)

        if self.manual_created_ifnames:
            for _if in self.manual_created_ifnames:
                if _if in get_all_ifnames():
                    del_if_by_name(_if)

        if is_netns_existed(self.netns):
            del_netns_by_name(self.netns)

        self.default_top_halves_before_exit(*args, **kwargs)

    def _top_halves_half_sync(self, *args, **kwargs):
        self.manual_created_ifnames = []
        self.need_up_ifnames = []

        if self.netns_enable:
            ifname = self.ifname
            if self.network == 'macvtap':
                if self.interface:
                    if self.interface not in get_up_ifnames():
                        self.need_up_ifnames.append(self.interface)
                        up_if_by_name(self.interface)
                    if self.dhcp:
                        try:
                            dhcp_if(self.interface)
                        except DHCPFailed as e:
                            printf(e)
                            raise NamespaceSettingError
                try:
                    create_macvtap(ifname=ifname, link=self.interface)
                except NetworkSettingError:
                    raise NamespaceSettingError(
                        'cannot determine a interface for creating %s devices'
                        % self.network)

            elif self.network == 'veth':
                try:
                    create_veth(ifname, self.ifnames[1])
                except NetworkSettingError as e:
                    printf(e)
                    raise NamespaceSettingError

                self.manual_created_ifnames.append(ifname)
                self.need_up_ifnames.append(ifname)

                if self.bridge:
                    if self.bridge not in get_all_ifnames():
                        create_bridge(self.bridge)
                        self.manual_created_ifnames.append(self.bridge)
                        if not self.interface:
                            self.dhcp = False

                    if self.bridge not in get_up_ifnames():
                        self.need_up_ifnames.append(self.bridge)
                    if self.interface:
                        if self.interface in get_up_ifnames():
                            down_if_by_name(self.interface)
                        self.need_up_ifnames.append(self.interface)
                        add_ifname_to_bridge(self.interface, self.bridge)

                    if ifname in get_up_ifnames():
                        down_if_by_name(ifname)
                        self.need_up_ifnames.append(ifname)
                    add_ifname_to_bridge(ifname, self.bridge)

                    for _if in self.need_up_ifnames:
                        up_if_by_name(_if)
                    if self.bridge in self.need_up_ifnames and self.dhcp:
                        try:
                            dhcp_if(self.bridge)
                        except DHCPFailed as e:
                            printf(e)
                            raise NamespaceSettingError
                else:
                    up_if_by_name(ifname)

            self.netns = self.netns_fmt % self.bottom_halves_child_pid
            try:
                add_ifname_to_ns_by_pid(
                    ifname=self.ifname_to_ns, netns=self.netns,
                    pid=self.bottom_halves_child_pid)
            except NetworkSettingError:
                raise SystemExit('failed to add %s to netns %s' %
                                     (self.ifname_to_ns, self.netns))

        self.default_top_halves_half_sync(*args, **kwargs)

    def _bottom_halves_after_sync(self, *args, **kwargs):
        up_if_by_name('lo')
        if self.netns_enable:
            ifname = self.ifname_to_ns
            if ifname not in get_all_ifnames():
                raise SystemExit('%s interfaces not existed' % ifname)
            up_if_by_name(ifname)

            if self.dhcp:
                try:
                    dhcp_if(ifname, leases=self._leases,
                                pid=self._dhclient_pid_file)
                except DHCPFailed as e:
                    raise SystemExit('dhcp failed')
                if self.nameservers:
                    nameservers = self.nameservers
                else:
                    nameservers = None
                if nameservers is None and os.path.exists(self._leases):
                    regex = re.compile('^ +option domain-name-servers ')
                    hdr = open(self._leases, 'r')
                    for line in hdr:
                        if regex.match(line):
                            pieces = line.split()[2].split(',')
                            nameservers = [l.rstrip(';') for l in pieces]
                            break
                    hdr.close()
                self.nameservers = nameservers

            if self.nameservers:
                path = self.resolv_conf
                hdr = open(path, 'w+')
                hdr.write('# richard_parker created and edited this file\n')
                for nameserver in nameservers:
                    hdr.write('nameserver %s\n' % nameserver)
                hdr.close()
                mount(source=path, target='/etc/resolv.conf', mount_type='bind')
            if self.hostname:
                sethostname(self.hostname)

        self.default_bottom_halves_after_sync(*args, **kwargs)

workbench.register_spawn_namespaces_trigger(
    'richard+network', _richard_parker_and_network)
