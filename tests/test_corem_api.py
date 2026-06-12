from __future__ import annotations

import unittest

from autobedge.corem_api import CoremApiManager
from autobedge.models import DailyAttendancePolicy


def _permit(start: str, end: str, name: str = "Permesso", tipo: str = "ORARIO", influisce: str = "NEGATIVAMENTE") -> dict:
    return {
        "dataInizio": start,
        "dataFine": end,
        "tipoEvento": tipo,
        "influisceTempiLavoro": influisce,
        "stato": "CONFERMATO",
        "localizzazioni": [{"lingua": "it", "nome": name}],
    }


class ApplyEventToPolicyTests(unittest.TestCase):
    def test_afternoon_permit_anticipates_badge_out(self) -> None:
        policy = DailyAttendancePolicy()
        CoremApiManager._apply_event_to_policy(policy, _permit("2026-06-12T14:00:00", "2026-06-12T18:00:00"), "2026-06-12")

        self.assertEqual(policy.badge_out_minutes, 14 * 60)
        self.assertFalse(policy.skip_badge_out)
        self.assertFalse(policy.skip_badge_in)
        self.assertEqual(policy.badge_in_minutes, -1)

    def test_partial_afternoon_permit_anticipates_to_its_start(self) -> None:
        policy = DailyAttendancePolicy()
        CoremApiManager._apply_event_to_policy(policy, _permit("2026-06-04T16:00:00", "2026-06-04T18:00:00"), "2026-06-04")

        self.assertEqual(policy.badge_out_minutes, 16 * 60)
        self.assertFalse(policy.skip_badge_out)

    def test_morning_permit_postpones_badge_in(self) -> None:
        policy = DailyAttendancePolicy()
        CoremApiManager._apply_event_to_policy(policy, _permit("2026-06-01T09:00:00", "2026-06-01T13:00:00"), "2026-06-01")

        self.assertEqual(policy.badge_in_minutes, 13 * 60)
        self.assertFalse(policy.skip_badge_in)
        self.assertFalse(policy.skip_badge_out)

    def test_non_influisce_event_is_ignored(self) -> None:
        policy = DailyAttendancePolicy()
        item = _permit("2026-06-09T09:00:00", "2026-06-09T18:00:00", name="Richiesta correzione beggiatura", influisce="NON_INFLUISCE")
        CoremApiManager._apply_event_to_policy(policy, item, "2026-06-09")

        self.assertFalse(policy.skip_badge_in)
        self.assertFalse(policy.skip_badge_out)
        self.assertEqual(policy.badge_in_minutes, -1)
        self.assertEqual(policy.badge_out_minutes, -1)

    def test_overtime_after_hours_does_not_touch_badges(self) -> None:
        policy = DailyAttendancePolicy()
        item = _permit("2026-06-01T18:00:00", "2026-06-01T20:00:00", name="Straordinario", influisce="NON_INFLUISCE")
        CoremApiManager._apply_event_to_policy(policy, item, "2026-06-01")

        self.assertFalse(policy.skip_badge_out)
        self.assertEqual(policy.badge_out_minutes, -1)

    def test_full_day_holiday_skips_both_badges(self) -> None:
        policy = DailyAttendancePolicy()
        item = _permit("2026-06-08T00:00:00", "2026-06-12T23:59:59", name="Ferie", tipo="GIORNALIERO")
        CoremApiManager._apply_event_to_policy(policy, item, "2026-06-10")

        self.assertTrue(policy.skip_badge_in)
        self.assertTrue(policy.skip_badge_out)


class FlattenEventItemsTests(unittest.TestCase):
    def test_flat_response_is_returned_as_is(self) -> None:
        events = [_permit("2026-06-12T14:00:00", "2026-06-12T18:00:00")]

        flattened = CoremApiManager._flatten_event_items(events, 590)

        self.assertEqual(len(flattened), 1)
        self.assertEqual(flattened[0]["dataInizio"], "2026-06-12T14:00:00")

    def test_nested_site_response_keeps_only_requested_user(self) -> None:
        data = [
            [
                {"id": 100, "nome": "Ufficio", "timezone": "Europe/Rome"},
                [
                    {"utente": {"id": 554, "cognome": "Pepe"}, "assenze": [_permit("2026-06-01T09:00:00", "2026-06-01T18:00:00")]},
                    {
                        "utente": {"id": 590, "cognome": "Russo"},
                        "assenze": [
                            _permit("2026-06-12T14:00:00", "2026-06-12T18:00:00"),
                            _permit("2026-06-04T16:00:00", "2026-06-04T18:00:00"),
                        ],
                    },
                    {"utente": {"id": 562, "cognome": "Gestione"}, "assenze": []},
                ],
            ]
        ]

        flattened = CoremApiManager._flatten_event_items(data, 590)

        self.assertEqual(len(flattened), 2)
        self.assertEqual({event["dataInizio"] for event in flattened}, {"2026-06-12T14:00:00", "2026-06-04T16:00:00"})

    def test_nested_site_response_ignores_site_header(self) -> None:
        data = [[{"id": 100, "nome": "Ufficio", "timezone": "Europe/Rome"}, []]]

        self.assertEqual(CoremApiManager._flatten_event_items(data, 590), [])


if __name__ == "__main__":
    unittest.main()
