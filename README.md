About
=====

[![Join the chat at https://gitter.im/procszoo/Lobby](https://badges.gitter.im/procszoo/Lobby.svg)](https://gitter.im/procszoo/Lobby?utm_source=badge&utm_medium=badge&utm_campaign=pr-badge&utm_content=badge)

Procszoo is a small Python module that gives you full
power to manage your processes by Linux namespaces.

## Contents
- [Wiki](https://github.com/procszoo/procszoo/wiki)
- [Goals](#goals)
- [Resources](#resources)
- [Requirements](#requirements)
- [Install](#install)
- [Building](#building)
- [Try It](#try-it)
- [Getting Your Feet Wet with the *procszoo* Module](#getting-your-feet-wet-with-the-procszoo-module)
- [Networks](#networks)
- [Docs](#docs)
- [Known Issues](#known-issues)
- [Exported Functions, Objects, and Helpful CLI](#exported-functions-objects-and-helpful-cli)
- [Test Platforms](#test-platforms)

## Goals
--------

Procszoo aims to provide you a simple but complete tool and
you can use it as a **DSL** or an embedded programming language
which let you operate Linux namespaces by Python.

Procszoo gives a smart *init* program. I get it from
[baseimage-docker](https://github.com/phusion/baseimage-docker).
Thanks a lot, you guys.

Procszoo does not require new version Python (but we support python3, too)
and Linux kernel.

Resources
---------

- IRC channel: #procszoo on freenode.net

## Requirements
---------------

Procszoo only requires Python standard libraries and the following packages

    # if you want python3, please install following package's python3 version
    # on RHEL/CentOS >= 6
    sudo yum -y install autoconf gcc make glibc-headers
    sudo yum -y install python-devel python-setuptools
    sudo yum -y install wireless-tools dhclient
    # Debain/Ubuntu
    sudo apt-get -y install autoconf gcc make libc6-dev
    sudo apt-get -y install python-dev python-setuptools
    sudo apt-get -y install iw isc-dhcp-client


Install
-------
1. You can install the *procszoo* by [setuptools](https://pypi.python.org/pypi/setuptools)

        git clone https://github.com/procszoo/procszoo.git
        cd procszoo && sudo ./setup.py install

2. You can install the *procszoo* by [pip](https://pypi.python.org/pypi/pip)

        sudo yum -y install python-pip
        sudo pip install procszoo


Building
--------
If you don't want to install it, then you can just clone it and do as the following commands,

    git clone https://github.com/procszoo/procszoo.git
    cd procszoo && make

By default, the above commands will build the program for your default Python version.
If you want to build it for other Python version, just specify your desired Python interpretor
through the `PYTHON` variable of the `make` command.
Eg. To build for Python 3:

    make PYTHON=/usr/bin/python3

If you will clone the *procszoo* in your home directory, On
the RHEL/CentOS/Scientific Linux/Fedora, the default mode of your home
directory is 0400, this will cause trouble, hence change it

    chmod go+rx ${HOME}

Try It
------
Now you can try it in an interactive shell as follows (we suppose you have installed
the *procszoo*)

    richard_parker -l                       # what namsepaces are available?
    richard_parker --available-c-functions  # what C functions are available?
    richard_parker                          # get an interactive shell

If your Linux kernel doesn't support "user" namespaces, e.g., RHEL6/CentOS6,
RHEL7/CentOS7, you need *super user* privileges

    sudo richard_parker

And now, you can check things that we have in namespaces

* programs get small pid number, e.g., 1, 2, etc., and there is only *lo* device
and it is down

        ps -ef 
        ifconfig -a

* open another terminal, we can see that the namespaces entries are different
from last namespaces

        ls -l /proc/self/ns

* if the kernel support and enable "user" namespaces, we are *superuser* at the same time

        id

* if you have trouble to try the above steps, please refer to
[Known Issues](#known-issues).


## Getting Your Feet Wet with the *procszoo* module
---------------------------------------------------
If you want to enable each namespace that your kernel supports

    from procszoo.c_functions import *
    
    if __name__ == "__main__":
        spawn_namespaces()

If you need to run your own program instead of an interactive *shell*, 

    from procszoo.c_functionss import *
    
    if __name__ == "__main__":
        spawn_namespaces(nscmd=path_to_your_program)

## Networks
-----------

Let's add network function to the new namespaces.

Because we will mount namespaces entries by the *bind* flag, we have to
run *richard_parker* as the super user.

Except the shell that *richard_parker* will open, we need another
interactive shell to make *veth* devices and add them to the new
"net" namespace.

* create a mount point

        mkdir /tmp/ns

* create namespaces

        sudo richard_parker --ns-bind-dir=/tmp/ns

* in *richard_parker*, configure the *lo* device

        ip link set lo up

* in a new terminal, remount the */tmp/ns/net* to */var/run/netns/net*
so *ip* command could operate it

        [ -d /var/run/netns ] | sudo mkdir -p  /var/run/netns
        sudo touch /var/run/netns/ns
        sudo mount --bind /tmp/ns/net /var/run/netns/ns

* in the new terminal, create two devices and set one of them to the new
namespace in this new terminal

        sudo ip link add veth0 type veth peer name veth1
        sudo ip link set dev veth1 netns ns

* in this new terminal, configure *veth0* device

        sudo ip link set veth0 up
        sudo ip addr add 192.168.0.10/24 broadcast 192.168.0.255 dev veth0

* in *richard_parker*, configure *veth1*

        ip link set veth1 up
        ip addr add 192.168.0.11/24 broadcast 192.168.0.255 dev veth1

* let's say "hello" from the new terminal

        ping -c 3 192.168.0.11

* let's say "hello" from *richard_parker*

        ping -c 3 192.168.0.10

## Docs
-------

* [namespaces(7)](http://man7.org/linux/man-pages/man7/namespaces.7.html)

* [unshare(2)](http://man7.org/linux/man-pages/man2/unshare.2.html)

* [setns(2)](http://man7.org/linux/man-pages/man2/setns.2.html)

* [ip(8)](http://man7.org/linux/man-pages/man8/ip.8.html)

* [mount(2)](http://man7.org/linux/man-pages/man2/mount.2.html)

* [pivot_root(2)](http://man7.org/linux/man-pages/man2/pivot\_root.2.html)

* [Linux namespaces](https://en.wikipedia.org/wiki/Linux_namespaces)

* [Docker and the PID 1 zombie reaping problem](https://blog.phusion.nl/2015/01/20/docker-and-the-pid-1-zombie-reaping-problem/)

* [Resource management:Linux kernel Namespaces and cgroups](http://www.haifux.org/lectures/299/netLec7.pdf)

* [Containers and Namespaces in the Linux Kernel](https://events.linuxfoundation.org/slides/lfcs2010_kolyshkin.pdf)

## Known Issues
---------------

* os.execv complains "permission deny"

    If running *richard_parker* unsuccessfully on RHEL/CentOS/Fedora, and get
    the following error messages like those

    >         os.execv(...)
    >     OSError: [Errno 13] Permission denied

    That's not a bug, please see
    the [comment](https://bugzilla.redhat.com/show_bug.cgi?id=1349789#c7).

* "ip netns" failed on RHRL6/CentOS6 and gave error messages as follows

    >     Object "nets" is unknown, try "ip help".

    We need a more latest iproute package, to do that please refer to
    [here](https://github.com/procszoo/procszoo/wiki/How-to-build-iproute-and-python-pyroute2-that-supports-net-namespace%3F)

## Exported Functions, Objects, and Helpful CLI
-----------------------------------------------

The *procszoo.utils* exported following functions and objects, and I don't
think that you need learn them all

* objects
    - workbench
    - SpawnNamespacesConfig

* key functions
    - [spawn\_namespaces](https://github.com/procszoo/procszoo/wiki/The-spawn_namespace-method-workflow)
    - check\_namespaces\_available\_status

* helpful functions
    - atfork
    - sched\_getcpu
    - mount
    - umount
    - umount2
    - unshare
    - setns
    - gethostname
    - sethostname
    - getdomainname
    - setdomainname
    - pivot\_root
    - to\_unicode
    - to\_bytes
    - adjust\_namespaces
    - get_namespace
    - get\_available\_propagations
    - get\_current\_users\_and\_groups
    - getresuid
    - getresgid
    - setresuid
    - setresgid
    - show\_namespaces\_status
    - show\_available\_c\_functions
    - cgroup\_namespace\_available
    - ipc\_namespace\_available
    - net\_namespace\_available
    - mount\_namespace\_available
    - pid\_namespace\_available
    - user\_namespace\_available
    - uts\_namespace\_available
    - unregister\_fork\_handlers

* Exceptions
    - CFunctionBaseException
    - CFunctionNotFound
    - NamespaceGenericException
    - UnknownNamespaceFound
    - UnavailableNamespaceFound
    - NamespaceSettingError

* Helpful CLI
    - richard\_parker
    - [mamaji](https://github.com/procszoo/procszoo/wiki/mamaji-command-line)

## Test Platforms
----------------
I test the *richard_parker* and these scripts in *tests/* on following
archs

- [CentOS](https://www.centos.org) 6(x86)
- [CentOS](https://www.centos.org) 7(x86\_64)
- [Fedora](https://getfedora.org) 24(x86\_64)
- [ubuntu](www.ubuntu.com) 12.04(armv7l)
- [Ubuntu](www.ubuntu.com) 14.04(x86\_64)
- [Ubuntu](www.ubuntu.com) 16.04(x86\_64)
- [openSUSE](https://www.opensuse.org/) 42(x86_64) 
