#!/usr/bin/env python
#
# Copyright (C) 2020 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""Unit tests for apexer."""

import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
import unittest

from zipfile import ZipFile

logger = logging.getLogger(__name__)

TEST_APEX = "com.android.example.apex"
TEST_APEX_LEGACY = "com.android.example-legacy.apex"

TEST_PRIVATE_KEY = os.path.join("testdata", "com.android.example.apex.pem")
TEST_X509_KEY = os.path.join("testdata", "com.android.example.apex.x509.pem")
TEST_PK8_KEY = os.path.join("testdata", "com.android.example.apex.pk8")
TEST_AVB_PUBLIC_KEY = os.path.join("testdata", "com.android.example.apex.avbpubkey")


def run(args, verbose=None, **kwargs):
    """Creates and returns a subprocess.Popen object.

    Args:
      args: The command represented as a list of strings.
      verbose: Whether the commands should be shown. Default to the global
          verbosity if unspecified.
      kwargs: Any additional args to be passed to subprocess.Popen(), such as env,
          stdin, etc. stdout and stderr will default to subprocess.PIPE and
          subprocess.STDOUT respectively unless caller specifies any of them.
          universal_newlines will default to True, as most of the users in
          releasetools expect string output.

    Returns:
      A subprocess.Popen object.
    """
    if 'stdout' not in kwargs and 'stderr' not in kwargs:
        kwargs['stdout'] = subprocess.PIPE
        kwargs['stderr'] = subprocess.STDOUT
    if 'universal_newlines' not in kwargs:
        kwargs['universal_newlines'] = True
    # Don't log any if caller explicitly says so.
    if DEBUG_TEST:
        print("\nRunning: \n%s\n" % " ".join(args))
    if verbose:
        logger.info("  Running: \"%s\"", " ".join(args))
    return subprocess.Popen(args, **kwargs)


def run_host_command(args, verbose=None, **kwargs):
    host_build_top = os.environ.get("ANDROID_BUILD_TOP")
    if host_build_top:
        host_command_dir = os.path.join(host_build_top, "out/soong/host/linux-x86/bin")
        args[0] = os.path.join(host_command_dir, args[0])
    return run_and_check_output(args, verbose, **kwargs)


def run_and_check_output(args, verbose=None, **kwargs):
    """Runs the given command and returns the output.

    Args:
      args: The command represented as a list of strings.
      verbose: Whether the commands should be shown. Default to the global
          verbosity if unspecified.
      kwargs: Any additional args to be passed to subprocess.Popen(), such as env,
          stdin, etc. stdout and stderr will default to subprocess.PIPE and
          subprocess.STDOUT respectively unless caller specifies any of them.

    Returns:
      The output string.

    Raises:
      ExternalError: On non-zero exit from the command.
    """
    proc = run(args, verbose=verbose, **kwargs)
    output, _ = proc.communicate()
    if output is None:
        output = ""
    # Don't log any if caller explicitly says so.
    if verbose:
        logger.info("%s", output.rstrip())
    if proc.returncode != 0:
        raise RuntimeError(
            "Failed to run command '{}' (exit code {}):\n{}".format(
                args, proc.returncode, output))
    return output


def get_sha1sum(file_path):
    h = hashlib.sha256()

    with open(file_path, 'rb') as file:
        while True:
            # Reading is buffered, so we can read smaller chunks.
            chunk = file.read(h.block_size)
            if not chunk:
                break
            h.update(chunk)

    return h.hexdigest()


def get_current_dir():
    """Returns the current dir, relative to the script dir."""
    # The script dir is the one we want, which could be different from pwd.
    current_dir = os.path.dirname(os.path.realpath(__file__))
    return current_dir


# In order to debug test failures, set DEBUG_TEST to True and run the test from
# local workstation bypassing atest, e.g.:
# $ m apexer_test && out/host/linux-x86/nativetest64/apexer_test/apexer_test
#
# the test will print out the command used, and the temporary files used by the
# test. You need to compare e.g. /tmp/test_simple_apex_input_XXXXXXXX.apex with
# /tmp/test_simple_apex_repacked_YYYYYYYY.apex to check where they are
# different.
# A simple script to analyze the differences:
#
# FILE_INPUT=/tmp/test_simple_apex_input_XXXXXXXX.apex
# FILE_OUTPUT=/tmp/test_simple_apex_repacked_YYYYYYYY.apex
#
# cd ~/tmp/
# rm -rf input output
# mkdir input output
# unzip ${FILE_INPUT} -d input/
# unzip ${FILE_OUTPUT} -d output/
#
# diff -r input/ output/
#
# For analyzing binary diffs I had mild success using the vbindiff utility.
DEBUG_TEST = False


class ApexerRebuildTest(unittest.TestCase):
    def setUp(self):
        self._to_cleanup = []

    def tearDown(self):
        if not DEBUG_TEST:
            for i in self._to_cleanup:
                if os.path.isdir(i):
                    shutil.rmtree(i, ignore_errors=True)
                else:
                    os.remove(i)
            del self._to_cleanup[:]
        else:
            print(self._to_cleanup)


    def _get_container_files(self, apex_file_path):
        dir_name = tempfile.mkdtemp(prefix=self._testMethodName+"_container_files_")
        self._to_cleanup.append(dir_name)
        with ZipFile(apex_file_path, 'r') as zip_obj:
            zip_obj.extractall(path=dir_name)
        files = {}
        for i in ["apex_manifest.json", "apex_manifest.pb",
                  "apex_build_info.pb", "assets"]:
            file_path = os.path.join(dir_name, i)
            if os.path.exists(file_path):
                files[i] = file_path
        self.assertIn("apex_manifest.pb", files)
        self.assertIn("apex_build_info.pb", files)
        return files

    def _extract_payload(self, apex_file_path):
        dir_name = tempfile.mkdtemp(prefix=self._testMethodName+"_extracted_payload_")
        self._to_cleanup.append(dir_name)
        cmd = ["deapexer", "extract", apex_file_path, dir_name]
        run_host_command(cmd)

        # Remove payload files added by apexer and e2fs tools.
        for i in ["apex_manifest.json", "apex_manifest.pb"]:
            if os.path.exists(os.path.join(dir_name, i)):
                os.remove(os.path.join(dir_name, i))
        if os.path.isdir(os.path.join(dir_name, "lost+found")):
            shutil.rmtree(os.path.join(dir_name, "lost+found"))
        return dir_name

    def _run_apexer(self, container_files, payload_dir):
        os.environ["APEXER_TOOL_PATH"] = (
            "out/soong/host/linux-x86/bin:prebuilts/sdk/tools/linux/bin")
        cmd = ["apexer", "--force", "--include_build_info", "--do_not_check_keyname"]
        cmd.extend(["--manifest", container_files["apex_manifest.pb"]])
        if "apex_manifest.json" in container_files:
            cmd.extend(["--manifest_json", container_files["apex_manifest.json"]])
        cmd.extend(["--build_info", container_files["apex_build_info.pb"]])
        if "assets" in container_files:
            cmd.extend(["--assets_dir", "assets"])
        cmd.extend(["--key", os.path.join(get_current_dir(), TEST_PRIVATE_KEY)])
        cmd.extend(["--pubkey", os.path.join(get_current_dir(), TEST_AVB_PUBLIC_KEY)])
        fd, fn = tempfile.mkstemp(prefix=self._testMethodName+"_repacked_", suffix=".apex.unsigned")
        os.close(fd)
        self._to_cleanup.append(fn)
        cmd.extend([payload_dir, fn])

        run_host_command(cmd)
        return fn

    def _sign_apk_container(self, unsigned_apex):
        fd, fn = tempfile.mkstemp(prefix=self._testMethodName+"_repacked_", suffix=".apex")
        os.close(fd)
        self._to_cleanup.append(fn)
        cmd = [
            "prebuilts/jdk/jdk11/linux-x86/bin/java",
            "-Djava.library.path=out/soong/host/linux-x86/lib64",
            "-jar", "out/soong/host/linux-x86/framework/signapk.jar",
            "-a", "4096",
            os.path.join(get_current_dir(), TEST_X509_KEY),
            os.path.join(get_current_dir(), TEST_PK8_KEY),
            unsigned_apex, fn]
        run_and_check_output(cmd)
        return fn

    def _run_build_test(self, apex_name):
        apex_file_path = os.path.join(get_current_dir(), apex_name + ".apex")
        if DEBUG_TEST:
            fd, fn = tempfile.mkstemp(prefix=self._testMethodName+"_input_", suffix=".apex")
            os.close(fd)
            shutil.copyfile(apex_file_path, fn)
            self._to_cleanup.append(fn)
        container_files = self._get_container_files(apex_file_path)
        payload_dir = self._extract_payload(apex_file_path)
        repack_apex_file_path = self._run_apexer(container_files, payload_dir)
        resigned_apex_file_path = self._sign_apk_container(repack_apex_file_path)
        self.assertEqual(get_sha1sum(apex_file_path), get_sha1sum(resigned_apex_file_path))

    def test_simple_apex(self):
        self._run_build_test(TEST_APEX)

    def test_legacy_apex(self):
        self._run_build_test(TEST_APEX_LEGACY)


if __name__ == '__main__':
    unittest.main(verbosity=2)
