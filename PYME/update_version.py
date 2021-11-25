#!/usr/bin/python

###############
# update_version.py
#
# Copyright David Baddeley, 2012
# d.baddeley@auckland.ac.nz
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
################
#!/usr/bin/python


from datetime import datetime
import os
import subprocess
import urllib
import json

def hook(ui, repo, **kwargs):
    update_version()
    return 0

def update_version_hg():
    now = datetime.now()
    
    p = subprocess.Popen('hg id -i', shell=True, stdout = subprocess.PIPE)
    id = p.stdout.readline().strip().decode()
    
    f = open(os.path.join(os.path.split(__file__)[0], 'version.py'), 'w')
    
    f.write('#PYME uses date based versions (yy.m.d)\n')    
    f.write("version = '%d.%02d.%02d'\n\n" % (now.year - 2000, now.month, now.day))
    f.write('#Mercurial changeset id\n')
    f.write("changeset = '%s'\n" % id)
    f.close()



version_template = """
# PYME uses date based versions (yy.mm.dd)
_release_version = '{version}'
_release_changeset = '{changeset}'

version = _release_version
changeset = _release_changeset # Git changeset ID

# if we are a development install, modify our version number to indicate this
# note this duplicates the logic in PYME.misc.check_for_updates, but is reproduced verbatim here
# so that the version.py works even if PYME is not already installed (ie when you are running python setup.py develop)
import os
pyme_parent_dir = os.path.dirname(os.path.dirname(__file__))
    
if os.path.exists(os.path.join(pyme_parent_dir, '.git')):
    print('Detected a .git folder, assuming a development install')
    dev_install = True
else:
    dev_install = False

if dev_install:
    # development install, flag this as a postrelease (means it should be given higher priority than an conda package of the same release version)
    version = version + '.post0.dev'

    try:
        import subprocess

        p = subprocess.Popen('git describe --abbrev=12 --always --dirty=+', shell=True, stdout=subprocess.PIPE, encoding='utf8')
        changeset = p.stdout.readline().strip()
    except:
        print('Development install detected, but could not get git hash, is git installed?')


_detailed_version = None
def detailed_version():
    '''
    Version to display in about dialogs, error dialogs, etc .... includes install type and commit hash (if modified from release commit). 
    
    Is NOT pep-0440 compliant, as it requires human interpretation of, e.g. commit hash ordering. 

    Example full_version strings:

    21.10.01[conda] - a conda package based install from an official release (also executable installers)
    21.10.01[pip] - a pip install from an official release
    21.10.01.post0.dev[git] - a development install of the exact release version
    21.10.01.post0.dev[git]f94cc30be308 - a development install which has been modified since the release (note, does not distinguish between remote commits to master and local commits)
    21.10.01.post0.dev[git]f94cc30be308+ - a development install with uncommitted local changes

    '''
    global _detailed_version
    if _detailed_version is None:
        from PYME.misc.check_for_updates import guess_install_type

        fv = version + '[' + guess_install_type() + ']'
        if changeset !=_release_changeset:
            # code has been modified since last release, append commit hash
            fv += changeset

        _detailed_version = fv

    return _detailed_version
"""



def update_version():
    now = datetime.utcnow()
    
    p = subprocess.Popen('git describe --abbrev=12 --always --dirty=+', shell=True, stdout=subprocess.PIPE, encoding='utf8')
    id = p.stdout.readline().strip()
    
    f = open(os.path.join(os.path.split(__file__)[0], 'version.py'), 'w')

    new_version = '%d.%02d.%02d' % (now.year - 2000, now.month, now.day)

    # check to see if there is already a release / tag with this version number,
    # if there is, this is a post-release, append post<n>
    p = subprocess.Popen('git tag', shell=True, stdout=subprocess.PIPE, encoding='utf8')
    git_tags = [l.strip() for l in p.stdout.readlines()]

    post_count=0
    nv = new_version
    while nv in git_tags:
        nv = '%s.post%d' %(new_version, post_count)
        post_count += 1

    new_version = nv

    f.write(version_template.format(version=new_version, changeset=id))

    f.close()
    
    print('PYMEVERSION=%s' % new_version)
    
if __name__ == '__main__':
    update_version()