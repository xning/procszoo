#!/usr/bin/env python
import os
import sys
from distutils.log import warn as printf
from setuptools import setup, find_packages, Extension, Command
from setuptools.command.build_py import build_py

here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "VERSION"), "r") as version_file:
    version = version_file.read().strip()

class ProcszooBuildPyCommand(build_py):
    def run(self):
        ret = os.system("make PYTHON=%s prepare" % sys.executable)
        if (ret != 0):
            raise RuntimeError("Failed to call `make`, exit code: %s" % ret)
        build_py.run(self)

setup(
    name='procszoo',
    version=version,
    description='python module to operate Linux namespaces',
    license='GPL2+',
    author='xning',
    author_email='anzhou94@gmail.com',
    packages = find_packages(),
    url='https://github.com/xning/procszoo',
    use_2to3=False,
    scripts=['bin/richard_parker', 'lib/procszoo/my_init'],
    ext_modules=[
        Extension(name='procszoo.c_functions.atfork',
            sources=['procszoo/c_functions/atfork/atfork.c',
                'procszoo/c_functions/atfork/atfork_module.c'],
            depends=['procszoo/c_functions/atfork/atfork.h'],
            ),
        ],
    package_data={'': ['*.txt', '*.md', 'README.first']},
    cmdclass={'build_py' : ProcszooBuildPyCommand},
    long_description="Procszoo aims to provide you a simple but complete tool "
        "and you can use it as a DSL or an embeded programming language "
        "which let you operate Linux namespaces by Python. "
        "Procszoo gives a smart init program. I get it from baseimage-docker. "
        "Thanks a lot, you guys. "
        "Procszoo does not require new version Python "
        "(but we support python3, too) and Linux kernel.",
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Console',
        'Intended Audience :: End Users/Desktop',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'Topic :: Software Development :: Libraries',
        'Topic :: System :: Systems Administration',
        'Intended Audience :: Information Technology',
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Operating System :: POSIX :: Linux',
        ],
    keywords='linux container namespace sandbox process',
)

