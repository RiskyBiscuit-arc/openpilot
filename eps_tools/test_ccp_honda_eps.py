"""Offline transport regression tests; no vehicle or installed Panda required."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import dump_crv_a220 as capture


def load_ccp():
    spec = importlib.util.spec_from_file_location("ccp_under_test", Path(__file__).with_name("ccp_honda_eps.py"))
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"panda": types.SimpleNamespace(Panda=type("Panda", (), {}))}):
        spec.loader.exec_module(module)
    return module


ccp = load_ccp()


class TransportTests(unittest.TestCase):
    def test_lost_upload_resets_address(self):
        client = object.__new__(ccp.CCP)
        commands = []
        address = 0
        uploads = 0

        def xfer(body, **kwargs):
            nonlocal address, uploads
            commands.append(body[0])
            if body[0] == ccp.C_SET_MTA:
                address = int.from_bytes(bytes(body[4:]), "big")
                return 0x728, 1, b"\xff\x00\x01"
            self.assertEqual(kwargs["retries"], 1)
            self.assertEqual(kwargs["reply_size"], 8)
            data = bytes(range(address, address + body[2]))
            address += body[2]
            uploads += 1
            return (None, None, None) if uploads == 1 else (0x728, 1, b"\xff\x00\x01" + data)

        client.xfer = xfer
        self.assertEqual(client.read_at(10, 5), bytes(range(10, 15)))
        self.assertEqual(commands, [2, 4, 2, 4])

    def test_response_requires_locked_bus_id_counter_and_length(self):
        client = object.__new__(ccp.CCP)
        client.bus, client.cro, client.dto, client.dto_bus, client.ctr = 1, 0x727, 0x728, 1, 0
        client._drain = lambda: None

        class FakePanda:
            def can_send(self, *args):
                pass

            def can_recv(self):
                return [(0x728, b"\xff\x00\x01wrong", 2),
                        (0x729, b"\xff\x00\x01wrong", 1),
                        (0x728, b"\xff\x00\x02wrong", 1),
                        (0x728, b"\xff\x00\x01", 1),
                        (0x728, b"\xff\x00\x01right", 1)]

        client.p = FakePanda()
        self.assertEqual(client.short_up(0, 5), b"right")

    def test_unknown_health_restores_silent(self):
        modes = []

        class FakePanda:
            def set_safety_mode(self, mode, param=0):
                modes.append(mode)

            def health(self):
                return {}

            def close(self):
                pass

        with patch.object(ccp, "Panda", FakePanda), patch.object(ccp.time, "sleep"):
            with self.assertRaises(SystemExit):
                ccp.CCP(0)
        self.assertEqual(modes, [ccp.ELM327, ccp.SILENT])

    def test_transport_modes_and_cleanup(self):
        for safety, routing, expected in (("elm327", "obd", (3, 0)),
                                           ("elm327", "normal", (3, 1)),
                                           ("alloutput", "normal", (17, 0))):
            calls = []

            class FakePanda:
                mode, param = 19, 0

                def set_safety_mode(self, mode, param=0):
                    self.mode, self.param = mode, param
                    calls.append((mode, param))

                def health(self):
                    return {"safety_mode": self.mode, "safety_param": self.param}

                def can_clear(self, bus):
                    self.cleared = bus

                def close(self):
                    calls.append("closed")

            with self.subTest(safety=safety, routing=routing):
                with patch.object(ccp, "Panda", FakePanda), patch.object(ccp.time, "sleep"):
                    client = ccp.CCP(1, safety=safety, routing=routing)
                    self.assertEqual(client.p.cleared, 0xFFFF)
                    client.close()
                    client.close()
                self.assertEqual(calls, [expected, (0, 0), "closed"])

    def test_rejects_wrong_routing_parameter_before_can(self):
        class FakePanda:
            def set_safety_mode(self, mode, param=0):
                pass

            def health(self):
                return {"safety_mode": 3, "safety_param": 0}

            def close(self):
                pass

            def can_clear(self, bus):
                raise AssertionError("Must abort before CAN access")

        with patch.object(ccp, "Panda", FakePanda), patch.object(ccp.time, "sleep"):
            with self.assertRaisesRegex(SystemExit, "requested Panda mode/param 3/1"):
                ccp.CCP(1, routing="normal")

    def test_existing_dump_refused_before_panda(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "existing.bin"
            path.write_bytes(b"existing")
            with self.assertRaises(FileExistsError):
                ccp.do_dump(0, 100, str(path), [0], [0x727], [0])
            self.assertEqual(path.read_bytes(), b"existing")

    def test_compare_counts_all_differences(self):
        first = bytes(capture.ROM_SIZE)
        second = bytearray(first)
        second[0] = second[-1] = 1
        report = capture.compare_dumps(first, second)
        self.assertFalse(report["identical"])
        self.assertEqual(report["differing_byte_count"], 2)
        self.assertFalse(report["captures"][0]["nonuniform_application"])

    def test_short_dump_rejected(self):
        with self.assertRaises(ValueError):
            capture.inspect_dump(b"short")

    def test_checksum_checks_detect_corruption(self):
        data = bytearray(capture.ROM_SIZE)
        data[0x4000:0x4004] = b"test"
        for offset, sign in ((0x6FF80, 1), (0x6FFFE, -1)):
            total = sum(int.from_bytes(data[i:i + 2], "big") for i in range(0x4000, offset, 2))
            data[offset:offset + 2] = ((sign * total) & 0xFFFF).to_bytes(2, "big")
        report = capture.inspect_dump(data)
        self.assertTrue(all(item["matches"] for item in report["a040_layout_checksum_checks"]))
        data[0x4010] ^= 1
        report = capture.inspect_dump(data)
        self.assertTrue(all(not item["matches"] for item in report["a040_layout_checksum_checks"]))

    def test_upload_failures_are_bounded(self):
        client = object.__new__(ccp.CCP)
        with patch.object(client, "set_mta", return_value=True) as reset:
            with patch.object(client, "upload", return_value=None):
                self.assertIsNone(client.read_at(100, 5))
        self.assertEqual(reset.call_count, 6)

    def test_capture_preserves_two_reads_and_hash_bound_report(self):
        def fake_run(command, check):
            self.assertTrue(check)
            self.assertIn("--dump", command)
            self.assertEqual(command[command.index("--cro") + 1], "0x727")
            self.assertNotIn("--profile", command)
            self.assertEqual(command[command.index("--safety") + 1], "elm327")
            self.assertEqual(command[command.index("--routing") + 1], "obd")
            Path(command[command.index("--dump") + 1]).write_bytes(bytes(capture.ROM_SIZE))

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            output = Path(directory) / "capture"
            with patch.object(sys, "argv", ["dump", "--out-dir", str(output)]):
                with patch.object(capture.subprocess, "run", side_effect=fake_run) as run:
                    with patch.object(sys, "stdout", io.StringIO()):
                        self.assertEqual(capture.main(), 2)  # all-zero reads must be flagged
            self.assertEqual(run.call_count, 2)
            self.assertEqual(len(list(output.glob("*-DO_NOT_FLASH.bin"))), 2)
            report_path, = output.glob("capture-report-*.json")
            report = json.loads(report_path.read_bytes())
            self.assertTrue(report["identical"])
            self.assertIn(capture.sha256(report_path.read_bytes()), report_path.name)
            self.assertEqual(report["captures"][0]["application_sha256"],
                             capture.sha256(bytes(0x6C000)))


if __name__ == "__main__":
    unittest.main()
