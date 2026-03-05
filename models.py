from sqlalchemy import Column, Integer, String, DateTime, Float
from sqlalchemy.orm import declarative_base
import datetime

Base = declarative_base()

class Event(Base):
    __tablename__ = 'events'

    id = Column(Integer, primary_key=True)
    event_name = Column(String(50), nullable=False) # e.g., 'visitedLandingPage', 'clickedctabutton', 'visitedThankYouPage'
    variant = Column(String(10), nullable=False) # 'A' or 'B'
    utm_source = Column(String(100))
    utm_medium = Column(String(100))
    utm_campaign = Column(String(100))
    ip_address = Column(String(50))
    user_agent = Column(String(500))
    fbp = Column(String(100)) # Facebook browser ID
    fbc = Column(String(100)) # Facebook click ID
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<Event {self.event_name} (Variant: {self.variant})>"
