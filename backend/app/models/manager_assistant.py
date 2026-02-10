from sqlalchemy import Column, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class ManagerAssistant(Base):
    __tablename__ = "manager_assistants"
    id = Column(Integer, primary_key=True, index=True)
    manager_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    assistant_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    percent = Column(Integer, nullable=False, default=0)

    __table_args__ = (UniqueConstraint("assistant_id", name="uq_manager_assistant_assistant_id"),)

    manager = relationship("User", foreign_keys=[manager_id])
    assistant = relationship("User", foreign_keys=[assistant_id])
