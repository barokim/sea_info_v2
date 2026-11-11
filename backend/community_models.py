"""커뮤니티 전용 DB 모델 (차유진 담당).

기존 공통 테이블은 그대로 사용하고, 답글 연결과 신고의 기타 설명을 저장해요.
커뮤니티 라우터가 이 모델을 불러오면 서버 시작 시 create_all이 테이블을 만들어요.
"""
from sqlmodel import Field, SQLModel


class CommentReply(SQLModel, table=True):
    __tablename__ = "comment_reply"

    comment_id: str = Field(primary_key=True, foreign_key="comment.id", ondelete="CASCADE")
    parent_id: str = Field(index=True, foreign_key="comment.id", ondelete="CASCADE")


class ReportDetail(SQLModel, table=True):
    __tablename__ = "report_detail"

    report_id: int = Field(primary_key=True, foreign_key="report.id", ondelete="CASCADE")
    detail: str
