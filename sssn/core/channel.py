from enum import Enum
from pydantic import BaseModel
from datetime import datetime


class ChannelType(Enum):
    """
    A channel type is a type of channel.
    """
    public = "public"
    private = "private"


class ChannelMessage(BaseModel):
    """
    A channel message is a message sent between a sender and a receiver.
    """
    content: str
    sender: str
    receiver: str
    timestamp: datetime


class Channel:
    """
    A channel is a communication channel between a sender and a receiver.
    """
    pass


class ChannelCollector:
    """
    It assumes there is a raw message queue (an conceptual model, it can be a news API, an internal KB, etc.), 
    the worker will check the queue occasionally (with set collect rate), and if there is a new message 
    (thus needs a raw index or even just a timestamp or a way to check), it will convert to standard 
    ChannelMessage and put to the Channel queue. 
    """
    pass