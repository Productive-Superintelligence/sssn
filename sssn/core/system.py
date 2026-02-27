import abc
import asyncio
from enum import Enum
from typing import List, Dict, Any, Callable, Optional

# --- 1. Lifecycle States ---
class SystemState(Enum):
    INIT = "INIT"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"

# --- 2. The Abstract System Base Class ---
class BaseSystem(abc.ABC):
    def __init__(
        self, 
        system_id: str, 
        name: str, 
        description: str = ""
    ):
        # Core Identity
        self.id = system_id
        self.name = name
        self.description = description
        self.state = SystemState.INIT
        
        # Holonic Descriptive Maps (Supply Chain Visibility)
        self.channel_directory: List[str] = []
        self.system_directory: List[str] = []
        
        # Direct Service Interfaces (e.g., {"/health": self.health_check})
        self.endpoints: Dict[str, Callable] = {}

    @property
    def is_atomic(self) -> bool:
        """Returns True if the system is atomic, i.e., not partitionable into smaller systems."""
        return len(self.channel_directory) == 0 and len(self.system_directory) == 0

    # --- Directory Management ---
    
    def register_channel(self, channel_id: str):
        """Descriptively log that this system participates in a channel."""
        if channel_id not in self.channel_directory:
            self.channel_directory.append(channel_id)

    def register_peer(self, peer_system_id: str):
        """Descriptively log that this system collaborates with another system."""
        if peer_system_id not in self.system_directory:
            self.system_directory.append(peer_system_id)

    def register_endpoint(self, route: str, handler: Callable):
        """Expose a standard sync/async direct API route."""
        self.endpoints[route] = handler


    # --- Core Framework Execution ---

    async def run(self, tick_rate: float = 1.0):
        """
        The infinite background loop that keeps the system alive.
        `tick_rate` defines how often the system wakes up to run a step.

        You may launch all your channels and systems here.
        """
        if self.state == SystemState.RUNNING:
            print(f"[{self.id}] is already running.")
            return

        self.state = SystemState.RUNNING
        print(f"System '{self.name}' ({self.id}) started. Tick rate: {tick_rate}s.")
        
        while self.state == SystemState.RUNNING:
            try:
                # Execute user-defined logic
                await self.step()
                
            except Exception as e:
                print(f"[{self.id}] Error during step execution: {e}")
                self.state = SystemState.ERROR
                # Depending on design, you might break here or attempt recovery
                break 
                
            # Sleep yields control back to the event loop, allowing other
            # systems or channels in the same process to run.
            await asyncio.sleep(tick_rate)

    def stop(self):
        """Gracefully halt the system loop."""
        self.state = SystemState.STOPPED
        print(f"System '{self.name}' ({self.id}) has been stopped.")