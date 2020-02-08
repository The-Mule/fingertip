# Licensed under GNU General Public License v3 or later, see COPYING.
# Copyright (c) 2019 Red Hat, Inc., see CONTRIBUTORS.

import fasteners
import git

import os
import tarfile


from fingertip.util import log, path, temp


OFFLINE = os.getenv('FINGERTIP_OFFLINE', '0') != '0'
DIR = path.downloads('git')


class Repo(git.Repo):
    def __init__(self, url, *path_components):
        self.url = url
        self.path = os.path.join(DIR, *path_components)
        lock_path = self.path + '-lock'
        self.lock = fasteners.process_lock.InterProcessLock(lock_path)
        self.lock.acquire()
        if not os.path.exists(self.path):
            log.info(f'cloning {url}...')
            r = git.Repo.clone_from(url, self.path, mirror=True)  # TODO: bare
            super().__init__(self.path)
        else:
            super().__init__(self.path)
            if not OFFLINE:
                log.info(f'updating {url}...')
                self.remote().fetch()
        self.lock.release()

    def __enter__(self):
        self.lock.acquire()
        return self

    def __exit__(self, *_):
        self.lock.release()


def cached_clone(m, url, path_in_m, rev=None):
    # TODO: improve for guaranteed fresh copy
    assert hasattr(m, 'ssh')
    with m:
        with Repo(url, url.replace('/', '::')) as repo:
            tar = temp.disappearing_file()
            tar_in_m = f'/tmp/{os.path.basename(tar)}'
            extracted_in_m = f'/tmp/{os.path.basename(tar)}-extracted'
            log.info(f'packing {url} checkout...')
            with tarfile.open(tar, 'w') as tf:
                tf.add(repo.path, arcname=extracted_in_m)
            log.info(f'uploading {url} checkout...')
            m.ssh.upload(tar, tar_in_m)
        log.info(f'performing {url} checkout...')
        m(f'''
            set -uex
            tar xmvf {tar_in_m} -C /
            mkdir -p {path_in_m}
            git clone -n {extracted_in_m} {path_in_m}
            cd {path_in_m}
            git remote set-url origin {url}
            git checkout {f'{rev}' if rev else 'origin/HEAD'}
            rm -rf {extracted_in_m}
            rm -f {tar_in_m}
        ''')
    return m
