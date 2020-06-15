%global with_python2 1

%if 0%{?rhel} >= 7 || 0%{?fedora} >= 13
%global with_python3 1
%endif

%global srcname procszoo
%global debug_package %{nil}
SOURCE10: VERSION
%global version %(tr -d '\n' < %{SOURCE10})
%global release 1
%global sum Python module to operate Linux namespaces
%global desc Procszoo aims to provide you a simple but complete tool and you can use it \
as a DSL or an embeded programming language which let you operate Linux namespaces by Python. \
Procszoo gives a smart init program. I get it from baseimage-docker. \
Thanks a lot, you guys. \
Procszoo does not require new version Python (but we support python3, too) and Linux kernel.

Name: python-%{srcname}
Summary: %{sum}
Version: %{version}
Release: %{release}%{?dist}
Source: %{srcname}-%{version}.tar.gz
License: GPL2+
Group: Development/Libraries
AutoReq: no
Prefix: %{_prefix}
Vendor: xning <anzhou94@gmail.com>
Packager: Rayson Zhu <vfreex+procszoo@gmail.com>
Url: https://github.com/procszoo/procszoo
Requires: dhclient
Requires(post): %{_sbindir}/update-alternatives
Requires(postun): %{_sbindir}/update-alternatives
BuildRequires: autoconf make gcc

%if 0%{?with_python2}
%{!?python2_version: %global python2_version %(%{__python2} -c "import sys; sys.stdout.write('\%s.\%s' \% (sys.version_info[0], sys.version_info[1]))")}
%if 0%{?rhel} <=7 || 0%{?fedora} <= 21
%{!?python2_pkgversion: %global python2_pkgversion ''}
%global python2_pkgprefix python
%else
%{!?python2_pkgversion: %global python2_pkgversion 2}
%global python2_pkgprefix python2
%endif
%endif

%if 0%{?with_python3}
%{!?python3_pkgversion: %global python3_pkgversion 3}
%global python3_pkgprefix python%{python3_pkgversion}
%endif

%if 0%{?rhel}
BuildRequires: epel-rpm-macros
%endif

%if 0%{?with_python2}
BuildRequires: %{python2_pkgprefix}-devel %{python2_pkgprefix}-setuptools python-rpm-macros python2-rpm-macros
%endif

%if 0%{?with_python3}
BuildRequires: %{python3_pkgprefix}-devel %{python3_pkgprefix}-setuptools python3-pkgversion-macros python-rpm-macros python3-rpm-macros 
%endif

%description
Procszoo aims to provide you a simple but complete tool and you can use it as a DSL or an embeded programming language which let you operate Linux namespaces by Python. Procszoo gives a smart init program. I get it from baseimage-docker. Thanks a lot, you guys. Procszoo does not require new version Python (but we support python3, too) and Linux kernel.

%if 0%{?with_python2}
%package -n python2-%{srcname}
AutoReq: no
Requires: python(abi) = %{python2_version} %{python2_pkgprefix}-setuptools
Summary: %{sum}
#%{?python_provide:%python_provide python2-%{srcname}}

%description -n python2-%{srcname}
%{desc}
%endif

%if 0%{?with_python3}
%package -n python%{python3_pkgversion}-%{srcname} 
AutoReq: no
Requires: python(abi) = %{python3_version} python%{python3_pkgversion}-setuptools
Summary: %{sum}
#%{?python_provide:%python_provide python%{python3_pkgversion}-%{srcname}}

%description -n python%{python3_pkgversion}-%{srcname}
%{desc}
%endif

%prep
%setup -n %{srcname}-%{version} -n %{srcname}-%{version}

%build
%if 0%{?with_python2}
%py2_build
%endif

%if 0%{?with_python3}
%py3_build
%endif

%install

%if 0%{?with_python3}
%py3_install
%endif

%if 0%{?with_python2}
%py2_install
%endif

rm -f "$RPM_BUILD_ROOT"/%{_bindir}/richard_parker
rm -f "$RPM_BUILD_ROOT"/%{_bindir}/mamaji

%clean
rm -rf "$RPM_BUILD_ROOT"

%if 0%{?with_python2}
%files -n python2-%{srcname}
%license LICENSE.txt
%doc README.first
%doc README.md
%{python2_sitearch}/*
%{_bindir}/*-%{python2_version}
%{_bindir}/*-2
%endif

%if 0%{?with_python3}
%files -n python%{python3_pkgversion}-%{srcname}
%license LICENSE.txt
%doc README.first
%doc README.md
%{python3_sitearch}/*
%{_bindir}/*-%{python3_version}
%{_bindir}/*-3
%endif

%if 0%{?with_python2}
%post -n python2-%{srcname}
%{_sbindir}/update-alternatives --install %{_bindir}/mamaji \
    mamaji %{_bindir}/mamaji-2 2
%{_sbindir}/update-alternatives --install %{_bindir}/richard_parker \
    richard_parker %{_bindir}/richard_parker-2 2

%postun -n python2-%{srcname}
if [ $1 -eq 0 ] ; then
    %{_sbindir}/update-alternatives --remove mamaji %{_bindir}/mamaji-2
    %{_sbindir}/update-alternatives --remove richard_parker %{_bindir}/richard_parker-2
fi
%endif

%if 0%{?with_python3}
%post -n %{python3_pkgprefix}-%{srcname}
%{_sbindir}/update-alternatives --install %{_bindir}/mamaji \
    mamaji %{_bindir}/mamaji-3 3
%{_sbindir}/update-alternatives --install %{_bindir}/richard_parker \
    richard_parker %{_bindir}/richard_parker-3 3

%postun -n %{python3_pkgprefix}-%{srcname}
if [ $1 -eq 0 ] ; then
    %{_sbindir}/update-alternatives --remove mamaji %{_bindir}/mamaji-3
    %{_sbindir}/update-alternatives --remove richard_parker %{_bindir}/richard_parker-3
fi
%endif

%changelog
* Tue Aug 30 2016 Rayson Zhu <vfreex@gmail.com> - 0.97.2a1-1
- first build
