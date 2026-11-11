"""차유진 담당: 사진 만료 후 재업로드 회귀 검사. 실제 데이터는 바꾸지 않아요.

    python -m unittest tools.test_community_photos
"""
import ast
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from sqlmodel import Session, select

from backend.routers import community
from services.api import ApiError
from services import community_data
from tools import test_community_replies


def expired():
    return community_data.Problem(422, "사진이 만료됐어요.", "photo_expired",
                                  {"errors": {"photo": "사진이 만료됐어요."}})


class PhotoRetryTests(unittest.TestCase):
    def setUp(self):
        self.state = {"write_photo_0": SimpleNamespace(file_id="selected"),
                      "write_photo_id": ("selected", "expired-id"), "write_consent": True,
                      "write_title": "입력한 제목", "write_body": "입력한 본문", "extra": {"depth": 5}}
        self.cd = SimpleNamespace(Problem=community_data.Problem, write_errors=community_data.write_errors,
                                  upload_photo=Mock(return_value="fresh-id"),
                                  create_post=Mock(return_value="new-post"), update_post=Mock())
        fields = SimpleNamespace(read=lambda *a: self.state["extra"], to_store=lambda fields, value: value,
                                 clear=lambda *a: None, validate=lambda *a: {})
        db = SimpleNamespace(board=lambda bid: {"fields": []}, boards=lambda **kw: [])
        source = ast.parse((Path(__file__).resolve().parents[1] / "views/write.py").read_text(encoding="utf-8"))
        functions = [n for n in source.body if isinstance(n, ast.FunctionDef)
                     and n.name in ("check", "photo_key", "selected_photo", "photo_id", "submit", "reset", "ask_cancel")]
        self.env = {"S": self.state, "cd": self.cd, "ApiError": ApiError, "fields": fields, "db": db,
                    "FP": "write_f", "TEXT_KEYS": ("write_title", "write_body", "write_consent", "write_photo_id")}
        exec(compile(ast.Module(body=functions, type_ignores=[]), "views/write.py", "exec"), self.env)

    def submit(self, pid=None):
        self.env["submit"]("public", pid)

    def test_valid_cached_photo_is_reused(self):
        self.submit()
        self.cd.upload_photo.assert_not_called()
        self.assertEqual(self.cd.create_post.call_args.args[4], "expired-id")
        self.assertEqual(self.state["write_new_post"], "new-post")
        self.assertIsNone(self.env["selected_photo"]())
        self.assertNotIn("write_photo_id", self.state)

    def test_expired_photo_reuploads_once_then_creates(self):
        self.cd.create_post.side_effect = [expired(), "new-post"]
        self.submit()
        self.cd.upload_photo.assert_called_once()
        calls = self.cd.create_post.call_args_list
        self.assertEqual([c.args[4] for c in calls], ["expired-id", "fresh-id"])
        self.assertEqual(calls[0].args[1:4], calls[1].args[1:4])
        self.assertEqual(self.state["write_new_post"], "new-post")

    def test_edit_reuploads_without_creating_another_post(self):
        self.cd.update_post.side_effect = [expired(), {}]
        self.submit("existing-post")
        self.cd.create_post.assert_not_called()
        self.assertEqual(self.cd.update_post.call_count, 2)
        self.assertEqual(self.cd.update_post.call_args.args[4], "fresh-id")
        self.assertEqual(self.state["write_new_post"], "existing-post")

    def test_repeated_expiry_stops_and_discards_bad_id(self):
        self.cd.create_post.side_effect = expired()
        self.submit()
        self.assertEqual(self.cd.create_post.call_count, 2)
        self.cd.upload_photo.assert_called_once()
        self.assertNotIn("write_photo_id", self.state)
        self.assertIn("photo", self.state["write_errors"])
        self.assertEqual(self.state["write_title"], "입력한 제목")
        self.assertEqual(self.state["extra"], {"depth": 5})
        self.assertNotIn("write_new_post", self.state)

    def test_other_errors_do_not_retry_post_creation(self):
        for error in (ApiError(0, "통신 오류"),
                      community_data.Problem(422, "제목 오류", "invalid_fields", {"errors": {"title": "제목 오류"}})):
            with self.subTest(error=error):
                self.cd.create_post.reset_mock(side_effect=True)
                self.cd.create_post.side_effect = error
                self.submit()
                self.cd.create_post.assert_called_once()
                self.cd.upload_photo.assert_not_called()
                self.assertEqual(self.state["write_photo_id"][1], "expired-id")
                self.assertEqual(self.state["write_body"], "입력한 본문")

    def test_failed_reupload_preserves_input_and_manual_retry_works(self):
        self.cd.create_post.side_effect = [expired(), "new-post"]
        self.cd.upload_photo.side_effect = [ApiError(0, "업로드 통신 오류"), "fresh-id"]
        self.submit()
        self.assertNotIn("write_photo_id", self.state)
        self.assertEqual(self.state["write_errors"]["_other"], "업로드 통신 오류")
        self.assertEqual(self.state["write_title"], "입력한 제목")
        self.submit()
        self.assertEqual(self.state["write_new_post"], "new-post")

    def test_no_consent_never_uploads_or_submits(self):
        self.state["write_consent"] = False
        self.submit()
        self.cd.upload_photo.assert_not_called()
        self.cd.create_post.assert_not_called()
        self.assertIn("photo", self.state["write_errors"])

    def test_reset_replaces_uploader_and_clears_photo_metadata(self):
        old_key = self.env["photo_key"]()
        self.env["reset"]()
        self.assertNotEqual(self.env["photo_key"](), old_key)
        self.assertIsNone(self.env["selected_photo"]())
        self.assertNotIn("write_consent", self.state)
        self.assertNotIn("write_photo_id", self.state)
        self.assertIsNone(self.env["photo_id"]())
        self.cd.upload_photo.assert_not_called()

    def test_new_photo_after_reset_never_reuses_previous_upload(self):
        self.env["reset"]()
        self.state[self.env["photo_key"]()] = SimpleNamespace(file_id="selected")
        self.assertEqual(self.env["photo_id"](), "fresh-id")
        self.cd.upload_photo.assert_called_once()

    def test_cancel_prompt_preserves_photo_until_discarded(self):
        photo = self.env["selected_photo"]()
        self.env["ask_cancel"]("public", None)
        self.assertTrue(self.state["write_cancel"])
        self.assertIs(self.env["selected_photo"](), photo)
        # 확인 창에서 그만두기를 선택할 때 호출하는 동일한 reset이에요.
        self.env["reset"]()
        self.assertIsNone(self.env["selected_photo"]())

    def test_real_api_expiry_reupload_saves_exactly_one_post(self):
        fixture = test_community_replies.ReplyTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        cache = {}
        image = io.BytesIO()
        Image.new("RGB", (16, 16), "blue").save(image, format="PNG")
        selected = SimpleNamespace(file_id="selected", name="photo.png", type="image/png", getvalue=image.getvalue)
        self.state["write_photo_0"] = selected

        def result(response):
            if response.status_code >= 400:
                detail = response.json()["detail"]
                raise community_data.Problem(response.status_code, detail["message"], detail["code"], detail)
            return response.json()

        def upload(photo):
            return result(fixture.client.post("/posts/photos", headers={"x-test-user": "member"},
                          files={"file": (photo.name, photo.getvalue(), photo.type)}))["id"]

        def create(board, title, body, extra, photo, consent):
            return result(fixture.client.post("/posts", headers={"x-test-user": "member"}, json={
                "board": board, "title": title, "body": body, "extra": extra,
                "photo_id": photo, "photo_consent": consent}))["id"]

        self.cd.upload_photo.side_effect = upload
        self.cd.create_post.side_effect = create
        with tempfile.TemporaryDirectory() as folder:
            # Redis TTL이 지난 상태를 즉시 재현해요. 실제 Redis나 업로드 폴더는 건드리지 않아요.
            Path(folder, "expired-id.jpg").write_bytes(b"old")
            settings = SimpleNamespace(upload_dir=folder, max_upload_mb=10)
            with patch.object(community, "get_settings", return_value=settings), \
                    patch.object(community.redis_store, "cache_get", side_effect=cache.get), \
                    patch.object(community.redis_store, "cache_set", side_effect=lambda k, v, ttl: cache.update({k: v})), \
                    patch.object(community.redis_store, "gap_ok", return_value=True):
                self.submit()
                self.assertIn("write_new_post", self.state)
                self.assertEqual(self.cd.create_post.call_count, 2)
                self.cd.upload_photo.assert_called_once()
                with Session(fixture.engine) as session:
                    posts = session.exec(select(community.Post)).all()
                    self.assertEqual(len(posts), 3)  # 예시 글 2개 + 새 글 1개
                    saved = session.get(community.Post, self.state["write_new_post"])
                    self.assertEqual(saved.title, "입력한 제목")
                    self.assertTrue(Path(folder, saved.photo_path).exists())


if __name__ == "__main__":
    unittest.main()
