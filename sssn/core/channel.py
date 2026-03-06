# TODO: add security layer to the channel.

import abc
import asyncio
import time
import uuid
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass
from fastapi import FastAPI, HTTPException, Request, Security, Depends, Header
from fastapi.security import APIKeyHeader
from contextlib import asynccontextmanager
import uvicorn

import sssn.utils.general as U
    


@dataclass
class ChannelMessage:
    id: str
    timestamp: float
    sender_id: str
    content: Any
    metadata: Dict[str, Any]
    raw_data: Optional[Any] = None


class ChannelDBClient(abc.ABC):
    """
    Abstract base class for channel databases. It does not matter what the actual DB is, 
    it can be a file, a database, a cloud storage, etc.

    It simply saves the metadata of the channel, and the messages in a chronological order.

    A channel is expected to be unique, plain structured, while system should have its own way to log channel id, 
    and channel should create its own space in the db and maintain itself. *The uniqueness is guaranteed by the system.*
    """

    @abc.abstractmethod
    async def create_db(self, channel_metadata: Dict[str, Any]) -> bool:
        """
        Initialize the database structure with the channel metadata.
        """
        pass

    @abc.abstractmethod
    async def save(self, message: 'ChannelMessage') -> bool:
        """
        Persist a single ChannelMessage to the database.
        Returns True if the save was successful.
        """
        pass

    @abc.abstractmethod
    async def get(self, message_id: str) -> Optional['ChannelMessage']:
        """
        Retrieve a specific message by its ID.
        Necessary for fallback if a message drops from the in-memory queue.
        """
        pass

    @abc.abstractmethod
    async def get_range(self, start_time: float, end_time: float) -> List['ChannelMessage']:
        """
        Retrieve a batch of messages within a specific time window.
        Crucial for systems that need to "catch up" after being offline.
        """
        pass


    @abc.abstractmethod
    async def get_latest(self, limit: int) -> List['ChannelMessage']:
        """
        Retrieve the latest messages.
        """
        pass



class BaseChannel(abc.ABC):
    """
    Abstract base class for channels.
    """
    def __init__(
        self,
        channel_id: str,
        name: str,
        description: str,
        period: float = 60.0,
        db_client: ChannelDBClient = None,
        ipc_wire: Any = None,
        max_queue_size: int = 1000,
        max_workers: int = 10,
        host: str = "0.0.0.0",  
        port: Optional[int] = None,  
        # vary naive whitelist access control, Need to be improved.
        readable_by: Optional[List[str]] = None, 
        writable_by: Optional[List[str]] = None,      
    ):
        # Identity & Access
        self.id = channel_id
        self.name = name
        self.description = description
        self.max_workers = max_workers
        self.max_queue_size = max_queue_size
        self._semaphore = None

        # Connections & State
        self.db_client = db_client
        self.ipc_wire = ipc_wire
        self.raw_data_buffer: Dict[str, Any] = {}
        self.url = f"/channels/{self.id}"
        
        # Async Mechanics
        self.period = period
        self.message_queue: asyncio.Queue[ChannelMessage] = None
        self._is_running = False

        # FastAPI Server Config
        self.host = host
        self.port = port or U.find_free_port()
        self.app = FastAPI(lifespan=self._lifespan)
        self._setup_builtin_routes()

        # Access Control TODO: improve this.
        self.readable_by = readable_by or ["*"] 
        self.writable_by = writable_by or ["*"] 


    @property
    def metadata(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "description": self.description}

    # --- Abstract Methods ---

    @abc.abstractmethod
    async def pull_fn(self):
        """Pulls data from the source and puts it into the message queue.
        
        There are two ways how information comes into the channel:
        1. The channel actively pulls data from the source. This is usually used for like pulling data from a database, a file, or API.
        2. The channel passively waits for data to be pushed to it. In this case, the channel is mostly for communication or content delivery.
        """
        pass

    @abc.abstractmethod
    async def convert_fn(self, raw_item: Any) -> Optional[ChannelMessage]:
        """Converts the raw item into a ChannelMessage."""
        pass

    # --- FastAPI Web Server Integration ---
    @asynccontextmanager
    async def _lifespan(self, app: FastAPI):
        """Manages the background loop tied to the FastAPI server lifecycle."""
        self._semaphore = asyncio.Semaphore(self.max_workers)
        self.message_queue = asyncio.Queue(maxsize=self.max_queue_size)

        self._is_running = True
        if self.db_client:
            await self.db_client.create_db(self.metadata)
            
        print("="*50)
        print(f"🚀 Channel {self.name} ({self.id}) Started!")
        print("="*50)
        
        # Start the background polling task
        loop_task = asyncio.create_task(self._background_loop())
        print(f"Channel {self.name} ({self.id}) started. Scanning every {self.period}s.")
        
        yield  # The web server runs here
        
        # Shutdown gracefully
        self.stop()
        loop_task.cancel()

    def _setup_builtin_routes(self):
        """Maps the get and put methods to HTTP endpoints."""

        @self.app.get(self.url)
        async def api_get(request: Request, limit: int = 10):
            requester_id = request.headers.get("X-Sssn-Requester-Id", "anonymous")
            try:
                messages = await self.get(requester_id, limit)
                return {"messages": messages}
            except PermissionError as e:
                raise HTTPException(status_code=403, detail=str(e))

        @self.app.put(self.url)
        async def api_put(request: Request):
            """Must need a write key to put data into the channel."""
            requester_id = request.headers.get("X-Sssn-Requester-Id", "anonymous")
            
            try:
                data = await request.json()
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid JSON payload")
                
            try:
                item_id = await self.put(sender_id=requester_id, data=data)
                return {"status": "accepted", "item_id": item_id}
            except PermissionError as e:
                raise HTTPException(status_code=403, detail=str(e))

    async def run(self):
        """Starts the FastAPI server (which automatically triggers the background loop)."""
        config = uvicorn.Config(self.app, host=self.host, port=self.port)
        server = uvicorn.Server(config)
        await server.serve()

    # --- Core Framework Methods ---

    async def _process_item(self, item_id: str, raw_data: Any) -> Optional[ChannelMessage]:
        """A bounded pipeline that collects AND saves a single item."""
        async with self._semaphore: 
            try:
                # 1. Async Collect
                message = await self.convert_fn(raw_data)
                if not isinstance(message, ChannelMessage):
                    # If it fails, optionally put it back into the buffer for retry
                    self.raw_data_buffer[item_id] = raw_data
                    return None
                
                # 2. Async Persistence
                if self.db_client:
                    save_success = await self.db_client.save(message)
                    if not save_success:
                        print(f"[{self.id}] Critical: Failed to save message {message.id} to DB.")
                        self.raw_data_buffer[item_id] = raw_data # Put back on failure
                        return None 
                
                return message
            except Exception as e:
                print(f"[{self.id}] Error processing item: {e}")
                self.raw_data_buffer[item_id] = raw_data # Put back on failure
                return None

    async def _background_loop(self):
        """The main background loop of the channel."""
        while self._is_running:
            try:
                await self.pull_fn()
            except Exception:
                pass

            try:
                # FIX: Pop the items safely so they aren't processed twice concurrently
                items_to_process = {}
                keys = list(self.raw_data_buffer.keys())
                for k in keys:
                    items_to_process[k] = self.raw_data_buffer.pop(k)

                if items_to_process:
                    tasks = [self._process_item(k, v) for k, v in items_to_process.items()]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    for result in results:
                        if isinstance(result, ChannelMessage):
                            try:
                                self.message_queue.put_nowait(result)
                            except asyncio.QueueFull:
                                print(f"[{self.id}] Queue full! Dropping item from memory.")
            except Exception as e:
                print(f"Error in Channel {self.id} loop: {e}")
                
            await asyncio.sleep(self.period)

    def stop(self):
        self._is_running = False

    # --- Interfaces ---

    async def get(self, requester_id: str, limit: int = 10) -> List[ChannelMessage]:
        if "*" not in self.readable_by and requester_id not in self.readable_by:
            raise PermissionError(f"{requester_id} lacks access to {self.id}")
        
        messages = []
        while not self.message_queue.empty() and len(messages) < limit:
            messages.append(self.message_queue.get_nowait())
        return messages

    async def put(self, sender_id: str, data: Any) -> str:
        if "*" not in self.writable_by and sender_id not in self.writable_by:
            raise PermissionError(f"{sender_id} lacks write access to {self.id}")
        
        _id = f"{time.time()}_{uuid.uuid4()}"
        self.raw_data_buffer[_id] = data
        return _id