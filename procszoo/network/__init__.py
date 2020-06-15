'''
This module gives us a lot functions to maintain and to operate interfaces.

To understand following abbreviated worlds please reference rtnetlink(7)
'''
import os
import sys
import errno
import logging
logging.basicConfig(level=logging.FATAL)

from procszoo.c_functions import mount
from procszoo.namespaces import *
from procszoo.utils import printf
from procszoo.network.exceptions import *
from procszoo.network.dhcp import *

__all__ = [
    'Pyroute2ModuleUnvailable', 'Pyroute2NetNSUnvailable',
    'NetworkSettingError', 'InterfaceNotFound',
    'UnkonwnInterfaceFound', 'DHCPFailed',
    'get_all_ifnames', 'get_all_ifindexes', 'get_all_ifnames_and_ifindexes',
    'is_ifindex_wireless', 'is_ifname_wireless',
    'is_all_ifindexes_wireless', 'is_all_ifnames_wireless',
    'get_all_oifindexes_of_default_route', 'get_all_oifnames_of_default_route',
    'create_macvtap', 'add_ifindex_to_ns', 'dhcp_if',
    'add_ifname_to_ns', 'add_ifname_to_ns_by_pid', 'del_netns_by_name',
    'del_if_by_name', 'del_if_by_index',
    'down_if_by_name', 'up_if_by_name',
    'down_if_by_index', 'up_if_by_index',
    'get_up_ifindexes', 'get_up_ifnames',
    'create_veth', 'create_bridge', 'DHCPFailed',
    'add_ifname_to_bridge', 'is_netns_existed',
    ]


try:
    import pyroute2
except ImportError:
    raise Pyroute2ModuleUnvailable('pyroute2 module unavailable')

try:
    from pyroute2 import netns
except AttributeError:
    raise Pyroute2NetNSUnvailable('pyroute2 netns function unavailable')

from pyroute2 import IPRoute
from pyroute2 import netns
from pyroute2 import IW
try:
    from pyroute2.netlink.exceptions import NetlinkError
except ImportError:
    from pyroute2.netlink import NetlinkError


def get_all_ifnames():
    '''get all interface names'''
    ipr = IPRoute()
    ret = [l.get_attr('IFLA_IFNAME') for l in ipr.get_links()]
    ipr.close()
    return ret


def get_all_ifindexes():
    '''get all interface indexes'''
    ipr = IPRoute()
    ret = [l.get('index') for l in ipr.get_links()]
    ipr.close()
    return ret


def get_all_ifnames_and_ifindexes():
    '''get all interface names and their indexes'''
    ipr = IPRoute()
    ret = [(l.get_attr('IFLA_IFNAME'), l.get('index'))
               for l in ipr.get_links()]
    ipr.close()
    return dict(ret)


def get_up_ifindexes():
    ipr = IPRoute()
    links = ipr.get_links()
    index_list = [l.get('index') for l in links
                     if (l.get('flags') & 1) == 1]
    ipr.close()
    return index_list


def get_up_ifnames():
    ipr = IPRoute()
    links = ipr.get_links()
    name_list = [l.get_attr('IFLA_IFNAME') for l in links
                     if (l.get('flags') & 1) == 1]
    ipr.close()
    return name_list


def is_ifindex_wireless(ifindex):
    '''check whether a interface is wireless or not by the its index'''
    retval = True

    try:
        iw = IW()
    except NetlinkError as e:
        if e.args[0] == errno.ENOENT:
            return False

    try:
        iw.get_interface_by_ifindex(ifindex)
    except NetlinkError:
        retval = False
    finally:
        iw.close()
    return retval



def is_ifname_wireless(ifname):
    '''check whether a interface is wireless or not by its name'''
    retval = True
    ipr = IPRoute()

    try:
        iw = IW()
    except NetlinkError as e:
        if e.args[0] == errno.ENOENT:
            return False
    finally:
        ipr.close()

    index = ipr.link_lookup(ifname=ifname)[0]
    try:
        iw.get_interface_by_ifindex(index)
    except NetlinkError:
        retval = False
    finally:
        iw.close()
        ipr.close()
    return retval


def is_all_ifindexes_wireless(ifindexes):
    try:
        iw = IW()
    except NetlinkError as e:
        if e.args[0] == errno.ENOENT:
            return False

    ret = {}

    for idx in ifindexes:
        try:
            iw.get_interface_by_ifindex(idx)
        except NetlinkError:
            ret[idx] = False
        else:
            ret[idx] = True

    iw.close()
    return ret


def is_all_ifnames_wireless(ifnames):
    ipr = IPRoute()

    try:
        iw = IW()
    except NetlinkError as e:
        if e.args[0] == errno.ENOENT:
            return False
    finally:
        ipr.close()

    ret = {}
    links = {}

    for l in ipr.get_links():
        links[l.get_attr('IFLA_IFNAME')] = l.get('index')

    unkown_ifnames = [n for n in ifnames if n not in links.keys()]
    if unkown_ifnames:
        raise UnkonwnInterfaceFound(unkown_ifnames)

    for n in ifnames:
        idx = links[n]

        try:
            iw.get_interface_by_ifindex(idx)
        except NetlinkError:
            ret[n] = False
        else:
            ret[n] = True

    return ret


def add_ifname_to_bridge(ifname, bridge):
    ipr = IPRoute()
    ipr.link('set', index=ipr.link_lookup(ifname=ifname)[0],
                master=ipr.link_lookup(ifname=bridge)[0])
    ipr.close()


def get_all_oifindexes_of_default_route(wifi=None):
    '''return list of all out interface names'''
    ipr = IPRoute()
    _idx_list = [r.get_attr('RTA_OIF') for r in ipr.get_default_routes()]
    if wifi:
        idx_list = _idx_list
    else:
        idx_list = [idx for idx in _idx_list if not is_ifindex_wireless(idx)]
    ipr.close()
    return idx_list


def get_all_oifnames_of_default_route(wifi=None):
    '''return list of all out interface index'''
    ipr = IPRoute()
    _idx_list = [r.get_attr('RTA_OIF') for r in ipr.get_default_routes()]
    if wifi:
        idx_list = _idx_list
    else:
        idx_list = [idx for idx in _idx_list if not is_ifindex_wireless(idx)]
    if not idx_list:
        return []
    links = ipr.get_links(*idx_list)
    name_list = [l.get_attr('IFLA_IFNAME') for l in links]
    ipr.close()
    return name_list

def create_bridge(bridge=None):
    if bridge is None:
        bridge = 'br0'
    ipr = IPRoute()
    ipr.link('add', ifname=bridge, kind='bridge')
    ipr.close()


def create_veth(ifname=None, peer=None):
    if ifname is None:
        ifname = 'veth0'
    if peer is None:
        peer = 'veth1'
    ipr = IPRoute()
    try:
        ipr.link('add', ifname=ifname, kind='veth', peer=peer)
    except Exception as e:
        printf(e)
        raise NetworkSettingError('failed to create veth pairs')
    finally:
        ipr.close()

def create_macvtap(ifname=None, link=None, mode=None, **kwargs):
    if 'kind' in kwargs:
        if kwargs.get('kind') != 'macvtap':
            raise NetworkSettingError('network need be macvtap')
    else:
        kwargs['kind'] = 'mactap'

    if ifname is None:
        ifname = 'nth%d' % os.getpid()
    if mode is None:
        mode = 'vepa'

    ipr = IPRoute()
    if link is None:
        ifs = [idx for idx in get_all_oifindexes_of_default_route()
                   if not is_ifindex_wireless(idx)]
        if not ifs:
            raise NetworkSettingError(
                'no default route for us to determine interface')
        else:
            index = ifs[0]
    else:
        try:
            index=int(link)
        except ValueError:
            index = ipr.link_lookup(ifname=link)[0]
        except Exception:
            raise NetworkSettingError(
                'failed to get the index of %s' % self.interface)
    try:
        ipr.link('add', ifname=ifname, kind='macvtap',
                     link=index, macvtap_mode=mode)
    except Exception as e:
        printf(e)
        raise NetworkSettingError(
            '%s %s' %  ('failed to create a macvtap device',
                            'perhaps you need a latest pyroute2 module'))
    finally:
        ipr.close()


def is_netns_existed(ns):
    return ns in netns.listnetns()


def add_ifindex_to_ns(ifindex, ns):
    ipr = IPRoute()
    try:
        ipr.link('set', index=ifindex, net_ns_fd=ns)
    except NetlinkError:
        raise NetworkSettingError('failed to add %d to netns' % ifindex)
    except Exception as e:
        printf(e)
        raise NetworkSettingError('failed to add %d to netns' % ifindex)
    finally:
        ipr.close()


def add_ifname_to_ns(ifname, ns):
    '''add a interface to the ns net namespace'''
    ipr = IPRoute()
    ifindex = ipr.link_lookup(ifname=ifname)[0]
    try:
        ipr.link('set', index=ifindex, net_ns_fd=ns)
    except NetlinkError:
        raise NetworkSettingError('failed to add %s to netns' % ifname)
    except Exception as e:
        printf(e)
        raise NetworkSettingError('failed to add %s to netns' % ifname)
    finally:
        ipr.close()


def add_ifname_to_ns_by_pid(ifname, pid=None, path=None, netns=None):
    if pid is None:
        pid = os.getpid()
    try:
        pid = int(pid)
    except ValueError:
        raise NetworkSettingError('unavailable pid')
    netns_dir = '/var/run/netns'
    if netns is None:
        netns = 'net%d' % pid
    target = '%s/%s' % (netns_dir, netns)

    if not os.path.exists(netns_dir):
        os.makedirs(netns_dir)
    if not os.path.isdir(netns_dir):
        raise NetworkSettingError('%s is not a dir' % netns_dir)
    if not os.path.exists(target):
        open(target, 'w+').close()

    if path is None:
        path = '/proc/%d/ns/net' % pid
    mount(source=path, target=target, mount_type="bind")
    add_ifname_to_ns(ifname, netns)

def del_netns_by_name(ns):
    netns.remove(ns)


def del_if_by_name(ifname):
    ipr = IPRoute()
    ipr.link('remove', ifname=ifname)
    ipr.close()


def del_if_by_index(ifindex):
    ifindex = int(ifindex)
    ipr = IPRoute()
    ipr.link_remove(ifindex)
    ipr.close()


def down_if_by_name(ifname):
    ipr = IPRoute()
    ifindex = ipr.link_lookup(ifname=ifname)[0]
    ipr.link('set', index=ifindex, state='down')
    ipr.close()


def up_if_by_name(ifname):
    ipr = IPRoute()
    ifindex = ipr.link_lookup(ifname=ifname)[0]
    ipr.link('set', index=ifindex, state='up')
    ipr.close()

def down_if_by_index(ifindex):
    ipr = IPRoute()
    ipr.link('set', index=ifindex, state='down')
    ipr.close()


def up_if_by_index(ifindex):
    ipr = IPRoute()
    ipr.link('set', index=ifindex, state='up')
    ipr.close()


def remove_netns(ns_name):
    netns = NetNS(ns_name)
    netns.remove()
    netns.close()
