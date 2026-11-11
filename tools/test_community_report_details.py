"""차유진 담당: 신고 기타 설명 저장·관리자 조회 API 검사. 메모리 DB만 사용해요.

    python -m unittest tools.test_community_report_details
"""
import contextlib
import io
import unittest
from unittest.mock import patch

from sqlmodel import SQLModel, Session, select

from backend.community_models import ReportDetail
from backend.routers import community
from services import community_data
from tools import test_community_replies


class ReportDetailTests(unittest.TestCase):
    def setUp(self):
        fixture = test_community_replies.ReplyTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.engine = fixture.engine
        self.client = fixture.client

    def report(self, detail="기타 설명", reason="기타", post="p1", user="member"):
        return self.client.post(f"/posts/{post}/report", headers={"x-test-user": user},
                                json={"reason": reason, "detail": detail})

    def get(self, path="/admin/community/report-details", user="admin", **params):
        return self.client.get(path, headers={"x-test-user": user}, params=params)

    def report_count(self):
        with Session(self.engine) as session:
            return len(session.exec(select(community.Report)).all()), len(session.exec(select(ReportDetail)).all())

    def test_save_trim_and_admin_single_lookup(self):
        self.assertEqual(self.report("  입력한 설명  ").status_code, 200)
        rows = self.get().json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["detail"], "입력한 설명")
        self.assertEqual(rows[0]["reason"], "기타")
        self.assertEqual(rows[0]["post_id"], "p1")
        result = self.get(f"/admin/community/reports/{rows[0]['report_id']}/detail")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), rows[0])
        self.assertEqual(self.report_count(), (1, 1))

    def test_guests_and_members_cannot_read_any_detail(self):
        self.report("관리자만 볼 설명")
        report_id = self.get().json()[0]["report_id"]
        for path in ("/admin/community/report-details", f"/admin/community/reports/{report_id}/detail"):
            for user, status in (("guest", 401), ("member", 403), ("author", 403)):
                with self.subTest(path=path, user=user):
                    result = self.get(path, user=user)
                    self.assertEqual(result.status_code, status)
                    self.assertNotIn("관리자만 볼 설명", result.text)
        self.assertNotIn("관리자만 볼 설명", self.client.get("/posts/p1").text)

    def test_optional_and_non_other_descriptions(self):
        self.assertEqual(self.report("  ").status_code, 200)
        self.assertEqual(self.report_count(), (1, 0))
        self.assertEqual(self.get().json()[0]["detail"], "")
        self.assertEqual(self.report("선택한 사유와 무관한 값", reason="스팸", post="p2").status_code, 200)
        self.assertEqual(self.get(post_id="p2").json()[0]["detail"], "")
        self.assertEqual(self.report_count(), (2, 0))

    def test_length_validation_and_self_report_rejection(self):
        self.assertEqual(self.report("가" * 101).status_code, 422)
        self.assertEqual(self.report(user="author").status_code, 409)
        self.assertEqual(self.report_count(), (0, 0))
        self.assertEqual(self.report("가" * 100).status_code, 200)
        self.assertEqual(self.get().json()[0]["detail"], "가" * 100)

    def test_duplicate_does_not_overwrite_original(self):
        self.report("처음 설명")
        self.assertEqual(self.report("덮어쓰면 안 되는 설명").status_code, 409)
        self.assertEqual(self.report_count(), (1, 1))
        self.assertEqual(self.get().json()[0]["detail"], "처음 설명")

    def test_detail_failure_rolls_back_report_and_post_count(self):
        with patch.object(community, "ReportDetail", side_effect=RuntimeError("test failure")), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.report().status_code, 500)
        self.assertEqual(self.report_count(), (0, 0))
        with Session(self.engine) as session:
            self.assertEqual(session.get(community.Post, "p1").report_count, 0)

    def test_auto_hide_and_report_status_are_preserved(self):
        with patch.object(community, "settings_data", return_value={"report_hide": 1}):
            self.assertEqual(self.report().status_code, 200)
        with Session(self.engine) as session:
            self.assertTrue(session.get(community.Post, "p1").hidden)
            report = session.exec(select(community.Report)).one()
            report.status = "문제없음"
            session.add(report)
            session.commit()
        self.assertEqual(self.get().json()[0]["detail"], "기타 설명")
        self.assertEqual(self.get().json()[0]["status"], "문제없음")

    def test_filter_pagination_and_missing_report(self):
        self.report("글 1")
        self.report("글 2", post="p2")
        self.assertEqual([r["post_id"] for r in self.get().json()], ["p2", "p1"])
        self.assertEqual(self.get(limit=1, offset=1).json()[0]["post_id"], "p1")
        self.assertEqual(self.get(post_id="p2").json()[0]["detail"], "글 2")
        self.assertEqual(self.get(post_id="missing").json(), [])
        for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
            self.assertEqual(self.get(**params).status_code, 422)
        self.assertEqual(self.get("/admin/community/reports/999999/detail").status_code, 404)

    def test_legacy_reports_survive_table_creation(self):
        with Session(self.engine) as session:
            session.add(community.Report(post_id="p1", user_id="member", reason="기타"))
            session.commit()
        ReportDetail.__table__.drop(self.engine)
        SQLModel.metadata.create_all(self.engine)
        self.assertEqual(self.report_count(), (1, 0))
        self.assertEqual(self.get().json()[0]["detail"], "")

    def test_deleted_report_cascades_detail(self):
        self.report()
        with Session(self.engine) as session:
            session.delete(session.exec(select(community.Report)).one())
            session.commit()
        self.assertEqual(self.report_count(), (0, 0))

    def test_service_helpers_connect_to_admin_api(self):
        self.report()
        with patch.object(community_data.api, "_client", self.client), \
                patch.object(community_data.api, "_headers", return_value={"x-test-user": "admin"}):
            rows = community_data.report_details("p1", limit=1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(community_data.report_detail(rows[0]["report_id"])["detail"], "기타 설명")


if __name__ == "__main__":
    unittest.main()
