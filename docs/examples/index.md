# Examples

Complete programs you can copy and adapt. Each one is a single file that
combines several parts of SSSN into a small application, with its output
and a short explanation of why it is built that way. The guide pages teach
one feature at a time; these show how the features fit together.

| Example | What it shows |
| --- | --- |
| [An order pipeline](order-pipeline.md) | Two tactics in a chain over typed events, bad orders recorded as error events, lineage from a shipment back to its order, and a snapshot that commits its own progress |
| [Processes sharing a store](shared-store.md) | A store served over HTTP to a gateway, a worker, and a pager, with safe retries, a worker restart, and a different delivery choice for each consumer |

## Running them

The order pipeline needs only `sssn`. The shared store also needs the
store server and the HTTP client:

```bash
pip install "sssn[server,client]"
python order_pipeline.py
python shared_store.py
```

The tactics are plain Python, so the programs run without a model or an
API key, and the outputs on these pages come from the docs test suite.
Replace a tactic with one whose `call()` asks an agent
([Tactics](https://lllm.one/tactics/)), and the rest of the program stays
the same.

More examples live next to the features they teach: a
[triage worker](../processing.md) runs a tactic over a support inbox,
[custom endpoints](../http.md#custom-endpoints) add a tail route to a
store server, and [Packages and refs](../packages.md) wires a worker to its
tactic and store by `lllm://` ref.
