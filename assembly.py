# Copyright (C) 2014-2015  Codethink Limited
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

import os
from definitions import Definitions
import cache
from staging import StagingArea
import repos
import app
import buildsystem
import sandbox
from subprocess import check_output
from subprocess import call

build_steps = ['pre-configure-commands',
               'configure-commands',
               'post-configure-commands',
               'pre-build-commands',
               'build-commands',
               'post-build-commands',
               'pre-test-commands',
               'test-commands',
               'post-test-commands',
               'pre-install-commands',
               'install-commands',
               'post-install-commands']


def assemble(target):
    '''Assemble dependencies and contents recursively until target exists.'''
    defs = Definitions()
    this = defs.get(target)
    if cache.get_cache(this):
        app.log(this, 'Cache found', cache.get_cache(this))
        return

    if defs.lookup(this, 'repo') != [] and defs.lookup(this, 'tree') == []:
        this['tree'] = repos.get_tree(this)

    with app.timer(this, 'Starting assembly'):
        with sandbox.setup(this):
            for dependency in defs.lookup(this, 'build-depends'):
                assemble(defs.get(dependency))
                sandbox.install_artifact(dependency, this['assembly'])

            # if we're distbuilding, wait here for all dependencies to complete
            # how do we know when that happens?

            for component in defs.lookup(this, 'contents'):
                assemble(defs.get(component))
                sandbox.install_artifact(component, this['install'])

            build(this)


def build(this):
    ''' Do the actual creation of an artifact.

    By the time we get here, all dependencies for 'this' have been assembled.

    '''
    app.log(this, 'Start build')
    defs = Definitions()
    if defs.lookup(this, 'repo') != []:
        repos.checkout(this)

    get_build_system_commands(defs, this)
    for build_step in build_steps:
        if defs.lookup(this, build_step):
            app.log(this, 'Running', build_step)
        for command in defs.lookup(this, build_step):
            app.log(this, 'PATH', os.environ['PATH'])
            sandbox.just_run(this, command)

    cache.cache(this)


def get_build_system_commands(defs, this):
    build_system = None
    has_commands = False

    # if bs is unspecified and all steps are empty, detect bs & use its commands
    # if bs is specified, use its commands for empty steps

    # this logic is rather convoluted, because there are examples of morph files
    # where build-system is unspecified. it boils down to:
    #     if bs is specified, or all steps are empty, fill any empty steps

    for bs in buildsystem.build_systems:
        if this.get('build-system') == bs.name:
            build_system = bs

    if not build_system:
        for build_step in build_steps:
            if defs.lookup(this, build_step) != []:
                return

        files = check_output(['ls', this['build']]).decode("utf-8").splitlines()
        build_system = buildsystem.detect_build_system(files)

    for build_step in build_steps:
        if defs.lookup(this, build_step) == []:
            if build_system.commands.get(build_step):
                this[build_step] = build_system.commands.get(build_step)
