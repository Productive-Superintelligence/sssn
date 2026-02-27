# sssn: System of Systems Supply Network

Sssn models a **distributed information supply chain** from source (the external world) to the sink (the end user/information consumers or another system outside sssn). It forms a **decentralized, peer-to-peer “holonic” non-hierarchical network**. It provides a **message-passing** architecture (using fast IPCWires for high-speed local communication) for agent-human-machine collaborations.

There are only two cases conceptually, for simplicity, local and public. Public is the domain for cross-(local)network communication (i.e., accessing resources on another network via the public internet, such as via a RESTful API). By saying "access the resource," it means accessing a channel within a (local) network. When publishing a network to the public net, it needs to be exposed via something like nginx so it can be found.

The conceptual participants/information suppliers in the network are:

* Humans: like social media, newspapers, reports, papers, etc., any human information  
* “Machines”: any computer programs, devices, robots, ML models, etc.  
* Agents: any LLM agents, it's also a machine, but just separate it for convenience

It's overall an agent-centric network, so many designs are optimized for agentic systems (otherwise, we can just use the network we already have today). There are only two core abstractions: **System (node) and Channel (edge)**. External information flows into the network and is delivered as AI-processed information or products.

## System

**System** is the unit or node in the network. It is a loose, "holonic", fractal container that can be nested or overlapped; it may encapsulate multiple systems (which can also be "systems") and channels. It's a very lightweight wrapper that imposes only minimal structure on the entities to make them "formal" citizens of the network, while leaving the developer with maximal freedom. It’s kind of like the 'nn.Module' in PyTorch that just organizes the objects into a framework recognizable form.

There are no hard constraints in structure, i.e., no policy for accessing the parent or children's resources. The network is fully plain, non-hierarchical among systems. Once a system is launched and connected to the network, it is considered a unique, self-contained entity (even if it may logically be a child of another system). The System is mainly for managerial purposes, which helps private channels for access control and improving the transparency of the **system supply chain**.

**Key properties**:

- **ID**: str, a unique identifier of this system. When go public, it will have an internet ID.  
- **Name**: str, alias of the system  
- **Description**: str, description  
- ***SystemDirectory***: The systems registered **under** this system. Can be empty if there is no system under it. It helps others in the network understand your composition, i.e., the systems that you work with. Like the partners in your “supply chain”. Also helps yourself.  
- ***ChannelDirectory***: the channels under the system. It also helps others to know your composition. Also helps yourself. Like, what do you ship/deliver, as the channel is the major way to deliver products in the network. Although you can still perform regular delivery by POST/GET/etc. While it is totally possible to build a “secret” channel between two systems, a registry is beneficial in multiple ways, like tracking status, avoiding redundancy, and being visible to other groups

Channels has no I/O separation, like it can just entirely do internal loops, while the system may still use regular POST/GET to provide service interface, SystemDirectory may not systems "under" a system, its just system in the chain (i.e., involved in a channel inside), like A can be on chain of B, B can still be on A, ideally, while the supply chain can be complicated, the directories should involve all the major channels, and the major systems that are involved in the channels, the directories are more descriptive than structural while can be very helpful for management. 

## Channel

Channel is the central data structure and interface, which provides a unified format for 

1. GSA to read (to perceivers or proxies) and write (from actuators)  
2. Cross-GSA, AI-human, AI-system, etc., communication (**private channels**)  
3. External systems to read, e.g., it can carry control signals (**high-speed channels)**

It's a general protocol for AI, Human, and Systems communication

**Classes: ChannelMessage, ChannelDB, Channel**

Each channel is a server that assumes there is a **raw message queue** (a conceptual model, it can be a news API, an internal KB, etc.), and the messages are indexed by unique id. A channel can have another system put data into it, it can also just host by itself, where the “source side” is some out-of-network entity, like a News API.

**Key methods:** 

- **Scan\_fn (abs, sync):** will be called every period, check the raw data queue, and simply sort and index them by chronicle order. It should be fast, no need to dump or parse it, just leave an address  
- **collect\_fn (abs, async) \-\> ChannelMessage:** given an index, convert it to a ChannelMessage, do all the heavy job  
- **run (default, background)**: default to call scan\_fn every while, and call multiple workers to collect unprocessed messages and automatically save them to ChannelDB, and put to MessageQueue, it will expose a **url** to access (can be local or remote)  
- **GET**: RESTful API, to get messages by time/other filters from the queue  
- **PUT** (optional): put data into the raw buffer, may not really have one if the writer is an API  
- **Auth** (optional): if a credential is needed to access this channel

**Key properties:**

- **State**: the server state  
- **Name**: str  
- **Description**: str  
- **ID**: str, a global unique ID  
- **DBClient**: **ChannelDBClient**   
- **MessageQueue**: **Queue\[ChannelMessage\],** a queue in memory for speed, if missed, find it in DB  
- **Url**: str|None, for RESTful access  
- **Scan\_period**: float, the period of scanning   
- **IPCWire**: **IPCWire**, high speed local communication lane for performance-demand applications like robotics, finance   
- **RawDataBuffer**: where to find the raw data  
- **Visibility**: List, which entities can access this channel if it's private, or “all”

## Example: Genesys ([pdf](https://arxiv.org/abs/2506.20249)) 

Genesys is a distributed system that runs LLM-based AlphaEvolve-style genetic programming to search for novel language model architectures; it has multiple designer agents, multiple evaluators, a knowledge engine, and an evolutionary master.

- The KE can be modeled as a standard tool calling  
- Each agent: designer, evaluator, is a system  
- The remaining part can be modeled by these channels  
  - The channels use Firebase as the backend  
  - Design channels: whenever idle, the designer will send a request to the Design Request (DR) channel and wait for a while, then check the Design Command (DC) channel. If there is one, start design, then send the product to the Design Delivery (DD) channel; if not, it will resend. When a design is done and delivered, it will CLEAR all design commands to IT first, then start a new cycle.  
    - DR channel: an agent uses PUT to write the artifact to it, which will be saved to Firebase by the channel worker  
  - Evaluation channels: similar to the design channels, one channel for requests, one for sending commands, and one for delivery.  
  - The master will make commands per request.  
- 6 core channels in total: DR, DC, DD, ER, EC, ED  
- Designers include proposer-reviewer, implementer; two systems  
  - Proposer-reviewer is modeled as an agent group (i.e., LLLM agent) that directly communicates by dialog, and it watches the DC channel for inputs  
  - Implementer is designed as another group, where an internal channel that keep pull non-repeat unimplemented from the evo tree as inputs  
  - Both directly send output to the DR channel (Implementer may even deliver every module in a module-by-module delivery)
