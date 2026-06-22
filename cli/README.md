# ros2bag-convert — command-line tools

Terminal versions of the [ROS 2 Bag Converter](https://wuisabel-gif.github.io/ros2bag_converter/)
web app. Inspect ROS 2 `.db3` bags and export topics to **CSV** / **JSON** without a
ROS 2 install — same CDR decoder and built-in schemas as the browser tool.

Two implementations, identical CLI:

| | Install | Dependencies |
|---|---|---|
| [**Node.js**](node/) | `npm install -g ./cli/node` (or `npx`) | `sql.js` (pure WASM, no native build) |
| [**Python**](python/) | `pip install ./cli/python` | none — standard library only |

## Commands

```bash
ros2bag-convert <bag.db3> [options]   # export (default)
ros2bag-convert info <bag.db3>        # summary, like `ros2 bag info`
ros2bag-convert list <bag.db3>        # topics, types, message counts
```

Options: `-f/--format csv|json`, `-o/--output FILE`, `-t/--topic NAME` (repeatable),
`-m/--metadata metadata.yaml`, `--max-rows N`.

```bash
ros2bag-convert info my_bag.db3
ros2bag-convert my_bag.db3 -f csv -t /odom -o odom.csv
ros2bag-convert my_bag.db3 -f json > all_topics.json
```

Data is written to **stdout** (use `-o` for a file); the one-line status note goes to
**stderr**, so piping/redirecting stdout always gives you clean CSV/JSON.

## Behaviour notes

- **Topics** default to all non-empty topics; pass `-t` one or more times to pick a subset.
- **CSV** flattens nested fields into columns (`pose.position.x`, …). With multiple topics
  it adds a `topic` column and unions the columns across topics.
- **Large binary arrays** (point-cloud / image `data`) are summarized, not dumped — same caps
  as the web app (1024 bytes / 8192 primitives).
- **Custom message types** are decoded automatically when the bag embeds a
  `message_definitions` table (ROS 2 Iron and newer); otherwise the built-in schemas apply.
- **Undecodable / unknown** messages export as raw byte-length placeholders instead of failing.
- The Node output is byte-for-byte identical to the web app. The Python output is semantically
  identical; numeric formatting can differ slightly (e.g. `2.0` vs `2`).

## Programmatic use

```js
// Node
const { openBag, eachMessage } = require('ros2bag-convert/bag');
const { decodeMessage } = require('ros2bag-convert');
```

```python
# Python
from ros2bag_converter import open_bag, decode_message, flatten
```
