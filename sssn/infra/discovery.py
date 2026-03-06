# discovery service for the network. Implemented as a discovery chennel

from sssn.core.channel import BaseChannel
from typing import Any, Optional
from sssn.core.channel import ChannelMessage

class DiscoveryChannel(BaseChannel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def pull_fn(self):
        pass

    async def convert_fn(self, raw_item: Any) -> Optional[ChannelMessage]:
        pass