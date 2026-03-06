# Simple System of Systems Network

A simple and light-weight network layer for a hybrid of agentic systems, other systems, and other information sources. It provides a message-passing architecture for agent-human-machine hybrid systems. This is for creating complex multi-system agentic systems in a simple way.

## Overview

Sssn models a **distributed information supply chain** from source (the external world) to the sink (the end user/information consumers or another system outside sssn). It forms a **decentralized, peer-to-peer “holonic” non-hierarchical network**. It provides a **message-passing** architecture (using fast IPCWires for high-speed local communication) for agent-human-machine collaborations.

There are only two cases conceptually, for simplicity, local and public. Public is the domain for cross-(local)network communication (i.e., accessing resources on another network via the public internet, such as via a RESTful API). By saying "access the resource," it means accessing a channel within a (local) network. When publishing a network to the public net, it needs to be exposed via something like nginx so it can be found.

The conceptual participants/information suppliers in the network are:

* Humans: like social media, newspapers, reports, papers, etc., any human information  
* “Machines”: any computer programs, devices, robots, ML models, etc.  
* Agents: any LLM agents, it's also a machine, but just separate it for convenience

It's overall an agent-centric network, so many designs are optimized for agentic systems (otherwise, we can just use the network we already have today). There are only two core abstractions: **System (node) and Channel (edge)**. External information flows into the network and is delivered as AI-processed information or products.


## Setup (Developer)

```bash
conda create -n sssn python=3.14 -y &&\
conda activate sssn &&\
pip install -r requirements.txt &&\
python -m ipykernel install --user --name "sssn" --display-name "Python (sssn)"
```

## Setup (Install package from Git)

```bash
pip install "git+https://github.com/Productive-Superintelligence/sssn.git"
```
