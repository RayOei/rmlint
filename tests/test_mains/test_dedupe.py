#!/usr/bin/env python3
# encoding: utf-8

from contextlib import contextmanager
import psutil
import pytest
import re

from tests.utils import *

REFLINK_CAPABLE_FILESYSTEMS = {'btrfs', 'xfs', 'ocfs2'}

@contextmanager
def assert_exit_code(status_code):
    """
    Assert that the with block yields a subprocess.CalledProcessError
    with a certain return code. If nothing is thrown, status_code
    is required to be 0 to survive the test.
    """
    try:
        yield
    except subprocess.CalledProcessError as exc:
        assert exc.returncode == status_code
    else:
        # No exception? status_code should be fine.
        assert status_code == 0


def up(path):
    while path:
        yield path
        if path == "/":
            break
        path = os.path.dirname(path)

def is_on_reflink_fs(path):
    parts = psutil.disk_partitions(all=True)

    # iterate up from `path` until mountpoint found
    for up_path in up(path):
        for part in parts:
            if up_path == part.mountpoint:
                print("{0} is {1} mounted at {2}".format(path, part.fstype, part.mountpoint))
                return (part.fstype in REFLINK_CAPABLE_FILESYSTEMS)

    print("No mountpoint found for {}".format(path))
    return False


@pytest.fixture
# fixture for tests dependent on reflink-capable testdir
def needs_reflink_fs():
    if not has_feature('btrfs-support'):
        pytest.skip("btrfs not supported")
    elif not is_on_reflink_fs(TESTDIR_NAME):
        pytest.skip("testdir is not on reflink-capable filesystem")
    yield

def test_equal_files(usual_setup_usual_teardown, needs_reflink_fs):
    path_a = create_file('1234', 'a')
    path_b = create_file('1234', 'b')

    with assert_exit_code(0):
        run_rmlint(
            '--dedupe',
            path_a, path_b,
            use_default_dir=False,
            with_json=False,
            verbosity="")

    with assert_exit_code(0):
        run_rmlint(
            '--dedupe',
            path_a, '//', path_b,
            use_default_dir=False,
            with_json=False)


def test_different_files(usual_setup_usual_teardown, needs_reflink_fs):
    path_a = create_file('1234', 'a')
    path_b = create_file('4321', 'b')

    with assert_exit_code(1):
        run_rmlint(
            '--dedupe',
            path_a, path_b,
            use_default_dir=False,
            with_json=False,
            verbosity="")


def test_bad_arguments(usual_setup_usual_teardown, needs_reflink_fs):
    path_a = create_file('1234', 'a')
    path_b = create_file('1234', 'b')
    path_c = create_file('1234', 'c')
    for paths in [
            path_a,
            ' '.join((path_a, path_b, path_c)),
            ' '.join((path_a, path_a + ".nonexistent"))
    ]:
        with assert_exit_code(1):
            run_rmlint(
                '--dedupe',
                paths,
                use_default_dir=False,
                with_json=False,
                verbosity="")


def test_directories(usual_setup_usual_teardown, needs_reflink_fs):
    path_a = os.path.dirname(create_dirs('dir_a'))
    path_b = os.path.dirname(create_dirs('dir_b'))

    with assert_exit_code(1):
        run_rmlint(
            '--dedupe',
            path_a, path_b,
            use_default_dir=False,
            with_json=False,
            verbosity="")


def test_dedupe_works(usual_setup_usual_teardown, needs_reflink_fs):

    # test files need to be larger than btrfs node size to prevent inline extents
    path_a = create_file('1' * 100000, 'a')
    path_b = create_file('1' * 100000, 'b')

    # confirm that files are not reflinks
    with assert_exit_code(1):
        run_rmlint(
            '--is-reflink', path_a, path_b,
            use_default_dir=False,
            with_json=False,
            verbosity=""
        )

    # reflink our files
    with assert_exit_code(0):
        run_rmlint(
            '--dedupe', path_a, path_b,
            use_default_dir=False,
            with_json=False,
            verbosity=""
        )

    # confirm that they are now reflinks
    with assert_exit_code(0):
        run_rmlint(
            '--is-reflink', path_a, path_b,
            use_default_dir=False,
            with_json=False,
            verbosity=""
        )


def test_clone_handler(usual_setup_usual_teardown, needs_reflink_fs):
    # test files need to be larger than btrfs node size to prevent inline extents
    path_a = create_file('1' * 100000, 'a')
    path_b = create_file('1' * 100000, 'b')

    sh_path = os.path.join(TESTDIR_NAME, 'rmlint.sh')

    # generate rmlint.sh and check that it correctly selects files for cloning
    with assert_exit_code(0):
        run_rmlint(
            '-S a -o sh:{p} -c sh:clone'.format(p=sh_path),
            path_a, path_b,
            use_default_dir=False,
            with_json=False
        )

    # parse output file for expected clone command
    counts = pattern_count(sh_path, ["^clone *'", "^skip_reflink *'"])
    assert counts[0] == 1
    assert counts[1] == 0

    # now reflink the two files and check again
    with assert_exit_code(0):
        run_rmlint(
            '--dedupe', path_a, path_b,
            use_default_dir=False,
            with_json=False,
            verbosity=""
        )
    with assert_exit_code(0):
        run_rmlint(
            '-S a -o sh:{p} -c sh:clone'.format(p=sh_path),
            path_a, path_b,
            use_default_dir=False,
            with_json=False
        )

    counts = pattern_count(sh_path, ["^clone *'", "^skip_reflink *'"])
    assert counts[0] == 0
    assert counts[1] == 1
