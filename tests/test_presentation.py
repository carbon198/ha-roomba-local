"""Verified V4 wire-code coverage, without Home Assistant or proprietary inputs."""

import unittest

from custom_components.roomba_local import presentation


class PresentationTests(unittest.TestCase):
    def test_all_verified_v4_error_codes_have_friendly_labels(self):
        groups = (
            (presentation.DOCK, {350, 351, 352, 353, 354, 360, 361, 362, 363, 364, 365, 399}),
            (presentation.REFILL, set(range(449, 465))),
            (
                presentation.WASH,
                {
                    649,
                    650,
                    651,
                    652,
                    653,
                    654,
                    660,
                    661,
                    662,
                    663,
                    664,
                    665,
                    668,
                    669,
                    670,
                    671,
                    672,
                },
            ),
            (presentation.DRY, set(range(749, 758))),
            (presentation.COMMON_DOCK_ERRORS, set(range(500, 514)) | set(range(515, 521))),
        )
        expected = {0}
        for labels, codes in groups:
            expected.update(codes)
            for code in codes:
                with self.subTest(code=code):
                    self.assertIn(code, labels)
                    for sensor in ("mission_error", "dock_error"):
                        self.assertEqual(presentation.display_value(sensor, code), labels[code])
        self.assertEqual(set(presentation.DOCK_ERROR_LABELS), expected)

    def test_corrected_descriptions(self):
        for code, label in {
            352: "Dock sealing issue",
            353: "Dust bag full",
            364: "Evacuation dock detected but not communicating",
            365: "Too-frequent evacuations",
            399: "Undefined evacuation error",
            453: "Refill alignment failure",
            464: "Detergent tank missing or empty",
            670: "Cleaning tray out of position",
            671: "Clean-water tank empty or missing",
            672: "Dirty-water tank full or missing",
        }.items():
            with self.subTest(code=code):
                self.assertEqual(presentation.display_value("mission_error", code), label)
                self.assertEqual(presentation.display_value("dock_error", code), label)
                self.assertEqual(presentation.display_value("dock_state", code), label)

    def test_states_and_unknown_values_do_not_become_errors_or_ok(self):
        for code in (301, 406, 601, 701):
            self.assertIn(code, presentation.DOCK_STATES)
            self.assertEqual(presentation.display_value("mission_error", code), f"Error {code}")
            self.assertEqual(presentation.display_value("dock_error", code), f"Dock error {code}")
        for code in (355, 655, 9999):
            self.assertEqual(
                presentation.display_value("dock_state", code), f"Unrecognized ({code})"
            )
            self.assertEqual(presentation.display_value("mission_error", code), f"Error {code}")
        self.assertEqual(
            presentation.display_value("dock_pad_wash_state", 353), "Unrecognized (353)"
        )
        self.assertEqual(
            presentation.display_value("dock_pad_dry_state", 353), "Unrecognized (353)"
        )
        for sensor in ("mission_error", "dock_error"):
            self.assertEqual(presentation.display_value(sensor, 0), "OK")
            self.assertIsNone(presentation.display_value(sensor, None))

    def test_verified_robot_faults_and_readiness_are_separate(self):
        robot_codes = {
            1,
            2,
            4,
            5,
            6,
            7,
            9,
            10,
            12,
            14,
            16,
            18,
            19,
            22,
            24,
            26,
            29,
            30,
            32,
            33,
            35,
            36,
            42,
            44,
            46,
            47,
            48,
            66,
            68,
            69,
            101,
            102,
            103,
            104,
            105,
            106,
            107,
            109,
            110,
            111,
            114,
            115,
            117,
            119,
            120,
            121,
            1000,
            1001,
            1008,
            1010,
            1025,
            1026,
            1027,
            1028,
            1029,
            1030,
            1034,
        }
        readiness_codes = {
            201,
            202,
            207,
            210,
            215,
            216,
            218,
            222,
            224,
            228,
            231,
            234,
            237,
            238,
            239,
            251,
            266,
            268,
            283,
            284,
            285,
            286,
            287,
            290,
        }
        self.assertEqual(set(presentation.ROBOT_ERRORS), robot_codes)
        self.assertEqual(set(presentation.READINESS), readiness_codes | {0})
        for code in robot_codes | readiness_codes:
            with self.subTest(code=code):
                self.assertFalse(
                    presentation.display_value("mission_error", code).startswith("Error ")
                )
                self.assertEqual(
                    presentation.display_value("dock_error", code), f"Dock error {code}"
                )
        self.assertEqual(presentation.display_value("mission_error", 7), "Left wheel sensor issue")
        self.assertEqual(
            presentation.display_value("not_ready_code", 7), "Readiness code 7 (meaning unverified)"
        )
        self.assertEqual(
            presentation.display_value("not_ready_code", 207), "Cannot start - bin missing"
        )
        self.assertEqual(presentation.display_value("not_ready_code", 0), "Ready")
        for code in (3, 8, 11, 3212, 3310, 4001):
            self.assertEqual(presentation.display_value("mission_error", code), f"Error {code}")

    def test_all_verified_dock_and_pad_states_remain_covered(self):
        for sensor, codes in (
            ("dock_state", set(range(300, 306)) | set(range(400, 407))),
            ("dock_pad_wash_state", {600, 601, 602, 603, 606, 607, 608}),
            ("dock_pad_dry_state", set(range(700, 708))),
        ):
            for code in codes:
                with self.subTest(sensor=sensor, code=code):
                    self.assertFalse(
                        presentation.display_value(sensor, code).startswith("Unrecognized")
                    )
        for key in ("audio_volume", "pad_wetness"):
            for level in (0, 1, 2, 3, 50):
                self.assertEqual(presentation.display_value(key, level), level)


if __name__ == "__main__":
    unittest.main()
