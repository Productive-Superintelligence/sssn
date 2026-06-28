# Getting Started

## Install

```bash
python -m pip install -e ".[dev,server]"
```

For documentation work:

```bash
python -m pip install -e ".[docs]"
mkdocs serve
```

## Run Tests

```bash
python -m pytest
```

## Create A Channel

```bash
sssn --store .sssn create-channel events --schema demo.Event
sssn --store .sssn append events '{"text":"hello"}' --kind message --source demo
sssn --store .sssn query-events events
```

## Serve A Store

```bash
sssn --store .sssn serve --host 127.0.0.1 --port 7700
```
