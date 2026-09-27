from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base


class ProblemRegionItem(Base):
    __tablename__ = "problem_region_items"

    id = Column(Integer, primary_key=True, index=True)
    region_id = Column(
        Integer, ForeignKey("problem_regions.id"), nullable=False, index=True
    )
    label = Column(String, nullable=False)
    order_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=True)
    latex = Column(Text, nullable=True)
    image_path = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
