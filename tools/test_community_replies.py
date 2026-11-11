"""차유진 담당 답글 기능 회귀 검사. 실제 DB 대신 메모리 DB를 사용해요.

    python -m unittest tools.test_community_replies
"""
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from backend.routers import community as community


class ReplyTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        # 기존 댓글이 있는 DB에도 테이블 추가만으로 적용할 수 있는지 확인해요.
        tables = [t for t in SQLModel.metadata.sorted_tables if t.name != "comment_reply"]
        SQLModel.metadata.create_all(self.engine, tables=tables)
        with Session(self.engine, expire_on_commit=False) as session:
            self.users = {}
            for role in ("author", "member", "admin"):
                user = community.User(id=role, email=f"{role}@reply.example", nickname=role,
                                      role="admin" if role == "admin" else "user")
                session.add(user)
                self.users[role] = user
            session.add(community.Board(id="public", name="public", status="운영 중"))
            session.commit()
            for pid in ("p1", "p2"):
                session.add(community.Post(id=pid, board_id="public", user_id="author", title=pid))
            session.commit()
            session.add(community.Comment(id="legacy", post_id="p1", user_id="author", body="기존 댓글"))
            session.get(community.Post, "p1").comments = 1
            session.commit()
        SQLModel.metadata.create_all(self.engine)

        def db_session():
            with Session(self.engine) as session:
                yield session

        def viewer(request: Request):
            return self.users.get(request.headers.get("x-test-user"))

        def member(request: Request):
            user = viewer(request)
            if not user:
                raise HTTPException(401, "로그인이 필요해요.")
            return user

        app = FastAPI()
        app.include_router(community.router)
        app.dependency_overrides[community.get_session] = db_session
        app.dependency_overrides[community.optional_user] = viewer
        app.dependency_overrides[community.require_user] = member
        self.settings = patch.object(community, "settings_data", return_value={"banned": ["금칙어"]})
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.addCleanup(self.engine.dispose)

    def add(self, body="답글", parent="legacy", post="p1", user="member"):
        return self.client.post(f"/posts/{post}/comments", json={"body": body, "parent_id": parent},
                                headers={"x-test-user": user})

    def comments(self):
        response = self.client.get("/posts/p1/comments")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def count(self):
        with Session(self.engine) as session:
            return session.get(community.Post, "p1").comments

    def test_existing_comments_and_reply_persist(self):
        self.assertIsNone(self.comments()[0]["parent_id"])
        response = self.add()
        self.assertEqual(response.status_code, 200, response.text)
        cid = response.json()["id"]
        self.assertEqual(response.json()["parent_id"], "legacy")
        with Session(self.engine) as session:
            self.assertEqual(session.get(community.CommentReply, cid).parent_id, "legacy")
            self.assertEqual(session.get(community.Comment, cid).body, "답글")
        self.assertEqual([c["id"] for c in self.comments()], ["legacy", cid])
        self.assertEqual(self.count(), 2)
        self.assertEqual(self.add(body="일반 댓글", parent=None).status_code, 200)

    def test_only_one_level_and_same_post(self):
        reply = self.add().json()["id"]
        self.assertEqual(self.add(parent=reply).status_code, 409)
        self.assertEqual(self.add(post="p2").status_code, 404)
        self.assertEqual(self.add(parent="missing").status_code, 404)
        self.assertEqual(self.count(), 2)

    def test_parent_deletion_preserves_replies_but_hides_original(self):
        reply = self.add().json()["id"]
        response = self.client.delete("/comments/legacy", headers={"x-test-user": "author"})
        self.assertEqual(response.status_code, 200)
        rows = self.comments()
        self.assertTrue(rows[0]["deleted"])
        self.assertEqual(rows[0]["body"], "")
        self.assertEqual(rows[0]["user"], "")
        self.assertIsNone(rows[0]["author"])
        self.assertEqual(rows[1]["id"], reply)
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.add().status_code, 404)
        self.assertEqual(self.client.delete(f"/comments/{reply}", headers={"x-test-user": "member"}).status_code, 200)
        self.assertEqual(self.comments(), [])
        self.assertEqual(self.count(), 0)

    def test_reply_validation_and_delete_permissions(self):
        for body in ("", " ", "금칙어", "a" * 301):
            with self.subTest(body=body[:10]):
                self.assertEqual(self.add(body=body).status_code, 422)
        self.assertEqual(self.add(user="guest").status_code, 401)
        reply = self.add().json()["id"]
        self.assertEqual(self.client.delete(f"/comments/{reply}", headers={"x-test-user": "author"}).status_code, 403)
        self.assertEqual(self.client.delete(f"/comments/{reply}", headers={"x-test-user": "admin"}).status_code, 200)
        self.assertEqual(self.client.delete(f"/comments/{reply}", headers={"x-test-user": "admin"}).status_code, 404)
        self.assertEqual(self.count(), 1)

    def test_board_rules_and_read_permissions_apply_to_replies(self):
        with Session(self.engine) as session:
            board = session.get(community.Board, "public")
            board.perm = {"read": "관리자", "comment": "회원"}
            session.add(board)
            session.commit()
        self.assertEqual(self.add().status_code, 403)
        self.assertEqual(self.client.get("/posts/p1/comments").status_code, 403)
        with Session(self.engine) as session:
            board = session.get(community.Board, "public")
            board.perm = {"read": "모두", "comment": "관리자"}
            session.add(board)
            session.commit()
        self.assertEqual(self.add().status_code, 403)
        self.assertEqual(self.add(user="admin").status_code, 200)
        with Session(self.engine) as session:
            board = session.get(community.Board, "public")
            board.rules = {"comments": False}
            session.add(board)
            session.commit()
        self.assertEqual(self.add(user="admin").status_code, 409)

    def test_soft_delete_and_author_reassignment_keep_links(self):
        reply = self.add().json()["id"]
        with Session(self.engine) as session:
            # 기존 탈퇴 흐름처럼 작성자를 다른 계정으로 넘겨도 연결은 유지돼요.
            for comment in session.exec(select(community.Comment)).all():
                comment.user_id = "admin"
            session.commit()
        self.assertEqual(self.comments()[1]["parent_id"], "legacy")
        with Session(self.engine) as session:
            # 관리자 게시글 삭제 흐름과 같은 소프트 삭제는 외래키와 충돌하지 않아요.
            for comment in session.exec(select(community.Comment)).all():
                comment.deleted = True
            session.get(community.Post, "p1").deleted = True
            session.commit()
            self.assertIsNotNone(session.get(community.CommentReply, reply))
        self.assertEqual(self.client.get("/posts/p1/comments").status_code, 404)


if __name__ == "__main__":
    unittest.main()
