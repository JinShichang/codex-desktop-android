"""Landlock preflight and startup-error propagation regressions (no phone)."""
import asyncio
import ctypes
import errno
import importlib
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
processes = importlib.import_module("tools.executor.bionic-supervisor.processes")
from tools.executor.exec_server import RpcError

BUILD = os.environ.get("CODEX_BIONIC_TEST_BUILD")


class SandboxCapabilityTests(unittest.TestCase):
    def query(self, abi, error=0):
        libc = Mock()
        libc.syscall.return_value = abi
        ctypes.set_errno(error)
        with patch.object(processes.os, "uname", return_value=Mock(machine="aarch64")), \
                patch.object(processes.ctypes, "CDLL", return_value=libc):
            processes.require_kernel_sandbox()
        return libc

    def test_supported_abi_stays_on_managed_path(self):
        for abi in (6, 7, 8):
            self.query(abi)

    def test_missing_or_old_abi_requests_native_approval_without_start(self):
        for abi, error in ((-1, errno.ENOSYS), (-1, errno.EOPNOTSUPP), (0, 0), (5, 0)):
            with self.subTest(abi=abi, error=error), self.assertRaises(RpcError) as caught:
                self.query(abi, error)
            self.assertEqual(caught.exception.code, -32042)

    def test_other_failures_are_not_retryable_capability_errors(self):
        for error in (errno.EPERM, errno.EACCES, errno.EFAULT, errno.EINVAL):
            with self.subTest(error=error), self.assertRaises(RpcError) as caught:
                self.query(-1, error)
            self.assertEqual(caught.exception.code, -32603)

    def test_unknown_architecture_fails_closed_without_query(self):
        with patch.object(processes.os, "uname", return_value=Mock(machine="unknown")), \
                patch.object(processes.ctypes, "CDLL") as library, self.assertRaises(RpcError) as caught:
            processes.require_kernel_sandbox()
        self.assertEqual(caught.exception.code, -32603)
        library.assert_not_called()


@unittest.skipUnless(BUILD, "optional compiled host fixture was not supplied")
class SandboxStartupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.support = importlib.import_module("tools.executor.bionic-supervisor.test_factory")
        self.support.BUILD = Path(BUILD)
        await self.support.FactoryTests.asyncSetUp(self)

    async def asyncTearDown(self):
        await self.support.FactoryTests.asyncTearDown(self)

    async def notify(self, *args):
        await self.support.FactoryTests.notify(self, *args)

    async def call(self, *args):
        return await self.support.FactoryTests.call(self, *args)

    async def test_missing_sandbox_preserves_rpc_error_and_releases_workspace_without_spawn(self):
        failure = RpcError(-32042, "Landlock unavailable; command not started")
        with patch.object(processes, "require_kernel_sandbox", side_effect=failure), \
                patch.object(processes.asyncio, "create_subprocess_exec") as spawn:
            with self.assertRaises(RpcError) as caught:
                await self.support.FactoryTests.start(self, "printf bad > should-not-exist")
        self.assertIs(caught.exception, failure)
        spawn.assert_not_called()
        self.assertFalse((self.workspace / "should-not-exist").exists())
        self.assertFalse(self.backend.files.lock.locked())
        self.assertFalse(self.backend.processes.quarantined)
        record = self.backend.processes.failed[-1]
        self.assertIsNone(record.process)
        self.assertTrue(record.closed)
        self.assertTrue(record.finished.done())

    async def test_invalid_policy_is_rejected_before_capability_probe(self):
        context = self.support.kernel.context(self.workspace)
        context["permissions"]["file_system"]["entries"][0]["access"] = "invalid"
        with patch.object(processes, "require_kernel_sandbox") as probe, \
                patch.object(processes.asyncio, "create_subprocess_exec") as spawn:
            with self.assertRaises(RpcError) as caught:
                await self.support.FactoryTests.start(self, "true", sandbox=context)
        self.assertNotEqual(caught.exception.code, -32042)
        probe.assert_not_called()
        spawn.assert_not_called()

    @unittest.skipUnless(os.environ.get("CODEX_TEST_LANDLOCK_ENOSYS") == "1",
                         "requires the isolated kernel ENOSYS test launcher")
    async def test_kernel_enosys_is_reported_before_any_worker_is_created(self):
        # The separate test launcher installs an actual seccomp ERRNO filter
        # for this one syscall. Neither the probe nor native records are mocked.
        with self.assertRaises(RpcError) as caught:
            await self.support.FactoryTests.start(self, "printf bad > should-not-exist")
        self.assertEqual(caught.exception.code, -32042)
        self.assertIn("require_escalated", caught.exception.message)
        self.assertFalse((self.workspace / "should-not-exist").exists())
        self.assertFalse(self.backend.files.lock.locked())
        self.assertFalse(self.backend.processes.quarantined)
        record = self.backend.processes.failed[-1]
        self.assertIsNone(record.process)
        self.assertTrue(record.finished.done())


if __name__ == "__main__":
    unittest.main()
