# Copyright (C) 2011-2015  Codethink Limited
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# =*= License: GPL-2 =*=

import contextlib
import os
from subprocess import call
import app
import cache
from definitions import Definitions
import shutil
import utils


@contextlib.contextmanager
def setup(this):

    currentdir = os.getcwd()
    currentenv = dict(os.environ)

    this['assembly'] = os.path.join(app.settings['assembly'], this['name'])
    this['build'] = os.path.join(this['assembly'], this['name']+ '.build')
    this['install'] = os.path.join(this['assembly'], this['name'] + '.inst')
    for directory in ['assembly', 'build', 'install']:
        os.makedirs(this[directory])

    build_env = create_env(this)

    try:
        for key, value in (currentenv.items() + build_env.items()):
            if key in build_env:
                os.environ[key] = build_env[key]
            else:
                os.environ.pop(key)

        os.chdir(this['build'])

        yield

    finally:
        os.environ = currentenv
        os.chdir(currentdir)


def install_artifact(component, installdir):
    app.log(component, 'Installing artifact in', installdir)
    unpackdir = unpack_artifact(component)
    utils.hardlink_all_files(unpackdir, installdir)


def unpack_artifact(component):
    cachefile = cache.get_cache(component)
    if cachefile:
        unpackdir = cachefile + '.unpacked'
        if not os.path.exists(unpackdir):
            os.makedirs(unpackdir)
            call(['tar', 'xf', cachefile, '--directory', unpackdir])
        return unpackdir

    app.log(component, 'Cached artifact not found')
    raise SystemExit


def cleanup(this):
    if this['build'] and this['install']:
        shutil.rmtree(this['build'])
        shutil.rmtree(this['install'])


def just_run(this, command):
    cmd_list = ['sh', '-c', command]
    log = os.path.join(app.settings['assembly'], this['cache'] + '.build-log')
    with open(log, "a") as logfile:
        logfile.write("# # %s\n" % command)
    app.log_env(log, '\n'.join(cmd_list))
    with open(log, "a") as logfile:
        if call(cmd_list, stdout=logfile, stderr=logfile):
            app.log(this, 'ERROR: in directory', os.getcwd())
            app.log(this, 'ERROR: command failed:\n\n', cmd_list)
            app.log(this, 'ERROR: log file at', log)
            raise SystemExit
    call(['mv', log, app.settings['artifacts']])


def run_cmd(this, command):
    argv = ['sh', '-c', command]
    use_chroot = True if this.get('build-mode') != 'bootstrap' else False
    do_not_mount_dirs = [this['build'], this['install']]

    if use_chroot:
        chroot_dir = this['assembly']
        chdir = os.path.join('/', os.path.basename(this['build']))
        do_not_mount_dirs += [os.path.join(app.settings['assembly'], d)
                              for d in  ["dev", "proc", 'tmp']]
        mounts = ('dev/shm', 'tmpfs', 'none'),
    else:
        chroot_dir = '/'
        chdir = this['build']
        do_not_mount_dirs += [app.settings.get("TMPDIR", "/tmp")]
        mounts = []

    binds = get_binds(this)

    container_config = dict(
        cwd=chdir,
        root=chroot_dir,
        mounts=mounts,
        mount_proc=use_chroot,
        binds=binds,
        writable_paths=do_not_mount_dirs)

    cmd_list = utils.containerised_cmdline(argv, **container_config)

    log = os.path.join(app.settings['assembly'], this['cache'] + '.build-log')
    with open(log, "a") as logfile:
        logfile.write("# # %s\n" % command)
    app.log_env(log, '\n'.join(cmd_list))
    with open(log, "a") as logfile:
        if call(cmd_list, stdout=logfile, stderr=logfile):
            app.log(this, 'ERROR: in directory', os.getcwd())
            app.log(this, 'ERROR: command failed:\n\n', cmd_list)
            app.log(this, 'ERROR: log file at', log)
            raise SystemExit
    call(['mv', log, app.settings['artifacts']])


def get_binds(this):
    if app.settings['no-ccache']:
        binds = ()
    else:
        ccache_dir = os.path.join(app.settings['ccache_dir'],
                                  os.path.basename(this['name']))
        ccache_target = os.path.join(this['assembly'],
                                     os.environ['CCACHE_DIR'].lstrip('/'))
        if not os.path.isdir(ccache_dir):
            os.mkdir(ccache_dir)
        if not os.path.isdir(ccache_target):
            os.mkdir(ccache_target)
        binds = ((ccache_dir, ccache_target),)

    return binds


def create_env(this):
    _base_path = ['/sbin', '/usr/sbin', '/bin', '/usr/bin']
    env = {}
    extra_path = []
    defs = Definitions()

    prefixes = [this.get('prefix', '/usr')]
    for name in defs.lookup(this, 'build-depends'):
        dependency = defs.get(name)
        prefixes.append(dependency.get('prefix'))
    prefixes = set(prefixes)
    for prefix in prefixes:
        if prefix:
            bin_path = os.path.join(prefix, 'bin')
            extra_path += [bin_path]

    ccache_path = []
    if not app.settings['no-ccache']:
        ccache_path = ['/usr/lib/ccache']
        env['CCACHE_DIR'] = '/tmp/ccache'
        env['CCACHE_EXTRAFILES'] = ':'.join(
            f for f in ('/baserock/binutils.meta',
                        '/baserock/eglibc.meta',
                        '/baserock/gcc.meta') if os.path.exists(f))
        if not app.settings.get('no-distcc'):
            env['CCACHE_PREFIX'] = 'distcc'

    if this.get('build-mode', 'staging') == 'staging':
        path = extra_path + ccache_path + _base_path
    else:
        rel_path = extra_path + ccache_path
        full_path = [os.path.normpath(this['assembly'] + p) for p in rel_path]
        path = full_path + os.environ['PATH'].split(':')

    env['PATH'] = ':'.join(path)

    if this.get('build-mode') == 'bootstrap':
        env['DESTDIR'] = this.get('install')
    else:
        env['DESTDIR'] = os.path.join('/',
                                      os.path.basename(this.get('install')))

    env['TERM'] = 'dumb'
    env['SHELL'] = '/bin/sh'
    env['USER'] = env['USERNAME'] = env['LOGNAME'] = 'tomjon'
    env['LC_ALL'] = 'C'
    env['HOME'] = '/tmp/'
    env['DESTDIR'] = this.get('install')
    env['PREFIX'] = this.get('prefix') or '/usr'
    env['MAKEFLAGS'] = '-j%s' % (this.get('max_jobs') or app.settings['max_jobs'])
#    env['MAKEFLAGS'] = '-j1'

    arch = app.settings['arch']
    cpu = 'i686' if arch == 'x86_32' else arch
    abi = 'eabi' if arch.startswith('arm') else ''
    env['TARGET'] = cpu + '-baserock-linux-gnu' + abi
    env['TARGET_STAGE1'] = cpu + '-bootstrap-linux-gnu' + abi
    env['MORPH_ARCH'] = arch

    return env
